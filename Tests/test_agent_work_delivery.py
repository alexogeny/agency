import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import time
import unittest

from Tests import test_agent_work as base


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "Tools/agent-work-hook"
WATCH = ROOT / "Tools/agent-work-watch"


class DeliveryTests(base.AgentWorkFixture, unittest.TestCase):
    def bind(self, task, client, session):
        return self.run_tool("session", task["id"], "--client", client, "--session", session, "--json")

    def hook(self, client, session, event="PostToolUse", **fields):
        payload = {**fields, "session_id": session, "hook_event_name": event, "cwd": str(self.repo)}
        result = subprocess.run([HOOK, "--client", client], input=json.dumps(payload),
                                capture_output=True, text=True, timeout=5,
                                env={**os.environ, "AGENT_WORK_STATE_DIR": str(self.state)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_two_sessions_receive_request_and_grant_without_manual_polling(self):
        owner = self.start("Owner", "src/parser")
        worker = self.start("Worker", "tests")
        self.bind(owner, "codex", "owner-session")
        self.bind(worker, "claude", "worker-session")
        request = json.loads(self.run_tool("request-claim", worker["id"], "src/parser", "--json").stdout)
        incoming = self.hook("codex", "owner-session")
        context = incoming["hookSpecificOutput"]["additionalContext"]
        self.assertIn(request["id"], context)
        self.assertIn("respond", context)
        self.assertIn("AGENT_WORK_TOKEN_FILE=", context)
        self.assertEqual(self.hook("codex", "owner-session"), {})
        self.run_tool("respond", owner["id"], request["id"], "--decision", "yield",
                      "--revision", "1", "--quiesced", "--json")
        receipt = self.hook("claude", "worker-session")
        self.assertIn("claim-granted", receipt["hookSpecificOutput"]["additionalContext"])
        progress = json.loads(self.run_tool("inbox", worker["id"], "--json").stdout)
        granted = next(item for item in progress if item["kind"] == "claim-granted")
        self.assertEqual(granted["state"], "delivered")
        self.run_tool("ack", worker["id"], granted["id"], "--json")
        self.assertNotIn(granted["id"], [item["id"] for item in json.loads(self.run_tool("inbox", worker["id"], "--json").stdout)])

    def test_stop_delivers_once_and_never_loops_on_unacknowledged_message(self):
        owner = self.start("Owner", "src")
        sender = self.start("Sender", "tests")
        self.bind(owner, "claude", "session")
        self.run_tool("broadcast", sender["id"], "--message", "Interface changing", "--json")
        result = self.hook("claude", "session", "Stop")
        self.assertEqual(result["decision"], "block")
        self.assertIn("Interface changing", result["reason"])
        self.assertEqual(self.hook("claude", "session", "Stop", stop_hook_active=True), {})
        self.assertEqual(self.hook("claude", "session", "Stop"), {})

    def test_registration_uses_start_token_and_actual_hook_session(self):
        owner = self.start("Owner", "src")
        self.hook("codex", "actual-session", tool_response={"stdout": json.dumps(owner)})
        status = json.loads(self.run_tool("status", owner["id"], "--json").stdout)
        self.assertEqual(status["transport"]["session_id"], "actual-session")
        forged = {**owner, "task_token": "not-the-task-credential"}
        self.hook("codex", "imposter", tool_response={"stdout": json.dumps(forged)})
        status = json.loads(self.run_tool("status", owner["id"], "--json").stdout)
        self.assertEqual(status["transport"]["session_id"], "actual-session")

    def test_large_image_event_still_delivers_pending_messages(self):
        for client in ("codex", "claude", "pi"):
            with self.subTest(client=client):
                owner = self.start("Image reviewer", f"{client}/assets")
                sender = self.start("Sender", f"{client}/tests")
                self.bind(owner, client, f"{client}-images")
                sent = json.loads(self.run_tool("broadcast", sender["id"], "--message",
                                                "Review the revised sprite", "--json").stdout)
                # Put routing metadata after the image to catch prefix-only reads.
                result = self.hook(client, f"{client}-images", tool_response={
                    "content": [{"type": "image", "data": "a" * (3 * 1024 * 1024)}]})
                self.assertNotIn("systemMessage", result)
                context = result["context"] if client == "pi" else result["hookSpecificOutput"]["additionalContext"]
                self.assertIn(sent["id"], context)
                self.assertIn("Review the revised sprite", context)
                record = json.loads(self.run_tool("message", sender["id"], sent["id"], "--json").stdout)
                delivery = next(item for item in record["deliveries"] if item["task_id"] == owner["id"])
                self.assertEqual(delivery["state"], "queued" if client == "pi" else "delivered")

    def test_registration_after_large_image_is_not_lost(self):
        owner = self.start("Image reviewer", "assets")
        result = self.hook("codex", "image-registration", tool_response={"content": [
            {"type": "image", "data": "a" * (3 * 1024 * 1024)},
            {"type": "text", "text": json.dumps(owner)},
        ]})
        self.assertNotIn("systemMessage", result)
        status = json.loads(self.run_tool("status", owner["id"], "--json").stdout)
        self.assertEqual(status["transport"]["session_id"], "image-registration")

    def test_offline_session_keeps_messages_queued_and_does_not_route_by_owner_label(self):
        owner = self.start("Owner", "src", owner="duplicate-label")
        sender = self.start("Sender", "tests", owner="duplicate-label")
        self.run_tool("broadcast", sender["id"], "--message", "Pending", "--json")
        self.assertEqual(self.hook("codex", "unregistered"), {})
        inbox = json.loads(self.run_tool("inbox", owner["id"], "--json").stdout)
        self.assertTrue(all(item["state"] == "queued" for item in inbox))
        self.bind(owner, "codex", "owner-session")
        self.assertIn("Pending", self.hook("codex", "owner-session")["hookSpecificOutput"]["additionalContext"])

    def test_watcher_requires_client_receipt_before_marking_delivery(self):
        owner = self.start("Owner", "src")
        sender = self.start("Sender", "tests")
        self.bind(owner, "pi", "push-session")
        for item in json.loads(self.run_tool("inbox", owner["id"], "--json").stdout):
            self.run_tool("ack", owner["id"], item["id"], "--json")
        process = subprocess.Popen([WATCH, "--client", "pi", "--session", "push-session"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env={**os.environ, "AGENT_WORK_STATE_DIR": str(self.state)})
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            ready = json.loads(process.stdout.readline())
            self.assertEqual(ready["event"], "ready")
            self.run_tool("broadcast", sender["id"], "--message", "Wake the idle session", "--json")
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            batch = json.loads(process.stdout.readline())
            self.assertIn("Wake the idle session", batch["context"])
            before = json.loads(self.run_tool("inbox", owner["id"], "--json").stdout)
            self.assertTrue(all(item["state"] == "queued" for item in before))
            process.stdin.write(json.dumps({"delivered": batch["id"]}) + "\n")
            process.stdin.flush()
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            self.assertEqual(json.loads(process.stdout.readline())["event"], "delivered")
            after = json.loads(self.run_tool("inbox", owner["id"], "--json").stdout)
            self.assertTrue(all(item["state"] == "delivered" for item in after))
        finally:
            process.terminate()
            process.communicate(timeout=5)

    def test_installation_includes_delivery_tools_and_unfiltered_hooks(self):
        for client in ("codex", "claude"):
            hooks = json.loads((ROOT / "config" / client / "hooks.json").read_text())["hooks"]
            for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
                groups = [group for group in hooks[event] if any("agent-work-hook" in item["command"] for item in group["hooks"])]
                self.assertEqual(len(groups), 1)
                self.assertNotIn("matcher", groups[0])
        source = (ROOT / "install.sh").read_text()
        user_setup = source.split('agency_prepare_scratch\n', 1)[1].split(
            'if [[ $platform == linux ]]; then\n  mapfile -t packages', 1)[0]
        for platform in ("linux", "macos"):
            home = self.workspace / f"install-{platform}"
            command = '''set -euo pipefail
AGENCY_DIR=$1
AGENCY_PLATFORM=$2
platform=$2
source "$1/scripts/lib.sh"
'''
            result = subprocess.run(["/bin/bash", "-c", command + user_setup, "bash", str(ROOT), platform],
                                    env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            preview = subprocess.run(["/bin/bash", str(ROOT / "install.sh"), "--platform", platform, "--dry-run"],
                                     env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            links = {f".local/bin/{name}": f"Tools/{name}" for name in (
                "agent-work-hook", "agent-work-watch", "agent-work-bridge")}
            links[".pi/agent/extensions/agency-work.ts"] = "Agents/pi/agency-work.ts"
            for target, managed_source in links.items():
                self.assertEqual((home / target).resolve(), ROOT / managed_source)
                self.assertIn(f"{home / target} -> {ROOT / managed_source}", preview.stdout)
            for target in (".codex/hooks.json", ".claude/settings.json"):
                hooks = json.loads((home / target).read_text())["hooks"]
                for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
                    groups = [group for group in hooks[event] if any(
                        "agent-work-hook" in item["command"] for item in group["hooks"])]
                    self.assertEqual(len(groups), 1)
                    self.assertNotIn("matcher", groups[0])

    def test_pi_extension_wakes_idle_session_and_stops_on_session_change(self):
        result = subprocess.run(["bun", ROOT / "Tests/fixtures/pi_agent_work.ts"],
                                capture_output=True, text=True, timeout=15,
                                env={**os.environ, "AGENT_WORK_STATE_DIR": str(self.state),
                                     "AGENCY_WORK_TEST_REPO": str(self.repo),
                                     "AGENCY_WORK_HOOK_COMMAND": str(HOOK),
                                     "AGENCY_WORK_WATCH_COMMAND": str(WATCH)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cleanup passed", result.stdout)

    def test_controlled_codex_and_claude_delivery_protocols(self):
        result = subprocess.run(["bun", ROOT / "Tests/fixtures/agent_work_bridges.ts"],
                                capture_output=True, text=True, timeout=20,
                                env={**os.environ, "AGENCY_WORK_TEST_REPO": str(self.repo),
                                     "AGENT_WORK_STATE_DIR": str(self.state)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Claude receipts passed", result.stdout)
        self.assertIn("WebSocket bridge and durable receipts passed", result.stdout)

    def test_unconfirmed_batch_survives_watcher_crash_and_reuses_message_ids(self):
        owner = self.start("Owner", "src")
        sender = self.start("Sender", "tests")
        self.bind(owner, "pi", "recover")
        first = self.hook("pi", "recover")
        self.assertEqual(first["event"], "messages")
        before = json.loads(self.run_tool("inbox", owner["id"], "--json").stdout)
        self.assertTrue(all(item["state"] == "queued" for item in before))
        with sqlite3.connect(self.state / "tasks.sqlite3") as connection:
            connection.execute("UPDATE message_deliveries SET lease_until='2000-01-01T00:00:00Z'")
        second = self.hook("pi", "recover")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual([item["message"]["id"] for item in first["items"]],
                         [item["message"]["id"] for item in second["items"]])
        confirmed = self.hook("pi", "recover", "DeliveryReceipt", batch_id=second["id"])
        self.assertTrue(confirmed["delivered"])
        after = json.loads(self.run_tool("inbox", owner["id"], "--json").stdout)
        self.assertTrue(all(item["state"] == "delivered" for item in after))

    def test_delivery_context_is_bounded_while_full_notes_remain_in_the_ledger(self):
        owner = self.start("Owner", ".")
        self.bind(owner, "pi", "bounded")
        for index in range(9):
            worker = json.loads(self.run_tool("start", "--task", f"Worker {index}", "--no-claims", "--json").stdout)
            self.run_tool("request-claim", worker["id"], f"src/{index}", "--message", "x" * 4096, "--json")
        result = self.hook("pi", "bounded")
        self.assertLessEqual(len(result["items"]), 8)
        self.assertLessEqual(len(result["context"]), 32768)
        messages = json.loads(self.run_tool("inbox", owner["id"], "--json").stdout)
        self.assertTrue(any(len(item["body"].get("note", "")) == 4096 for item in messages))

    def test_controlled_claude_process_confirms_replayed_input(self):
        session = "6f0b21dc-c068-44a7-85ad-147b564dfe82"
        owner = self.start("Owner", "src")
        sender = json.loads(self.run_tool("start", "--task", "Sender", "--no-claims", "--json").stdout)
        self.bind(owner, "claude", session)
        mock = self.workspace / "mock-claude"
        mock.write_text('#!/usr/bin/env python3\nimport json,sys\nassert "--replay-user-messages" in sys.argv\n'
                        'for line in sys.stdin:\n value=json.loads(line)\n print(json.dumps(value), flush=True)\n')
        mock.chmod(0o755)
        process = subprocess.Popen([ROOT / "Tools/agent-work-bridge", "--client", "claude", "--session", session,
                                    "--claude-command", mock], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, cwd=self.repo,
                                   env={**os.environ, "AGENT_WORK_STATE_DIR": str(self.state)})
        try:
            sent = json.loads(self.run_tool("broadcast", sender["id"], "--message", "Controlled Claude inbox", "--json").stdout)
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            event = json.loads(process.stdout.readline())
            self.assertEqual(event["session_id"], session)
            self.assertIn("Controlled Claude inbox", event["message"]["content"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                record = json.loads(self.run_tool("message", sender["id"], sent["id"], "--json").stdout)
                if record["deliveries"][0]["state"] == "delivered":
                    break
                time.sleep(0.02)
            self.assertEqual(record["deliveries"][0]["state"], "delivered")
        finally:
            process.terminate()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
