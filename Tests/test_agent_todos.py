import json
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import subprocess
import unittest

from Tests.test_agent_work import AgentWorkFixture, ROOT


class DurableTodoTests(AgentWorkFixture, unittest.TestCase):
    def test_start_with_acceptance_atomically_creates_linked_root(self):
        work = json.loads(self.run_tool("start", "--task", "Deliver parser repair", "--scope", "src",
                                        "--acceptance", "Reported input and regression checks pass", "--json").stdout)
        todo = json.loads(self.run_tool("todo", "show", work["todo_id"], "--json").stdout)
        self.assertEqual(todo["work_task"], work["id"])
        self.assertEqual(todo["acceptance"], "Reported input and regression checks pass")
        self.assertEqual(self.run_tool("finish", work["id"], "--summary", "Done", "--json", check=False).returncode, 3)
        self.assertEqual(self.update(todo, status="done", evidence="Reported input verified; regression checks passed").returncode, 0)
        self.run_tool("finish", work["id"], "--summary", "Verified", "--json")

    def add(self, title="Ship the feature", **fields):
        arguments = ["todo", "add", title, "--acceptance", "Focused checks pass"]
        for name, value in fields.items():
            arguments.extend(("--" + name.replace("_", "-"), value))
        return json.loads(self.run_tool(*arguments, "--json").stdout)

    def update(self, todo, **fields):
        arguments = ["todo", "update", todo["id"], "--revision", str(todo["revision"])]
        for name, value in fields.items():
            arguments.extend(("--" + name.replace("_", "-"), value))
        return self.run_tool(*arguments, "--json", check=False)

    def hook(self, client="codex", session="session", event="PostToolUse", **fields):
        result = subprocess.run([ROOT / "Tools/agent-work-hook", "--client", client],
                                input=json.dumps({"session_id": session, "cwd": str(self.repo),
                                                  "hook_event_name": event, **fields}),
                                env={**os.environ, "AGENT_WORK_STATE_DIR": str(self.state)},
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_nested_board_survives_claim_expiry_and_new_process(self):
        work = self.start("Implement", "src")
        parent = self.add(work_task=work["id"], owner="codex-root")
        child = self.add("Verify integration", parent=parent["id"], owner="claude-worker")
        with sqlite3.connect(self.state / "tasks.sqlite3") as connection:
            connection.execute("UPDATE tasks SET heartbeat_at='2000-01-01T00:00:00Z'")
        self.assertEqual(json.loads(self.run_tool("status", work["id"], "--json").stdout)["status"], "abandoned")
        board = json.loads(self.run_tool("todo", "list", "--json").stdout)
        self.assertEqual({row["id"] for row in board["items"]}, {parent["id"], child["id"]})
        self.assertEqual(board["open_count"], 2)
        self.assertEqual(next(row for row in board["items"] if row["id"] == child["id"])["parent_id"], parent["id"])
        self.assertEqual(list(self.repo.glob("*")), [self.repo / ".git"])

    def test_evidence_and_closed_descendants_required_for_completion(self):
        parent = self.add()
        child = self.add("Run integration", parent=parent["id"])
        self.assertNotEqual(self.update(parent, status="done").returncode, 0)
        self.assertNotEqual(self.update(parent, status="done", evidence="Parent checked").returncode, 0)
        self.assertEqual(self.update(child, status="done", evidence="Integration test: 3 passed").returncode, 0)
        result = self.update(parent, status="done", evidence="Acceptance verified")
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = self.run_tool("todo", "check", parent["id"], "--json")
        self.assertEqual(json.loads(checked.stdout)["open_count"], 0)
        self.assertNotEqual(self.run_tool("todo", "check", "missing", "--json", check=False).returncode, 0)

    def test_cannot_hide_open_children_by_cancelling_parent(self):
        parent = self.add()
        self.add("Still required", parent=parent["id"])
        result = self.update(parent, status="cancelled", evidence="User removed the parent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("descendant", result.stderr)

    def test_revision_conflict_does_not_overwrite_another_agent(self):
        todo = self.add()
        result = self.update(todo, owner="claude", note="Taking validation")
        self.assertEqual(result.returncode, 0, result.stderr)
        stale = self.update(todo, status="done", evidence="Old view")
        self.assertEqual(stale.returncode, 3)
        self.assertIn("revision", stale.stderr)
        shown = json.loads(self.run_tool("todo", "show", todo["id"], "--json").stdout)
        self.assertEqual(shown["owner"], "claude")
        self.assertEqual(len(shown["events"]), 2)

    def test_simultaneous_agent_updates_cannot_both_win(self):
        todo = self.add()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda owner: self.update(todo, owner=owner), ("codex", "claude")))
        self.assertEqual(sorted(result.returncode for result in results), [0, 3])
        shown = json.loads(self.run_tool("todo", "show", todo["id"], "--json").stdout)
        self.assertEqual(shown["revision"], 2)
        self.assertEqual(len(shown["events"]), 2)

    def test_reboot_expires_execution_without_removing_obligation(self):
        work = self.start("Implement", "src")
        todo = self.add(work_task=work["id"])
        with sqlite3.connect(self.state / "tasks.sqlite3") as connection:
            connection.execute("UPDATE ledger_meta SET value='previous-boot' WHERE key='boot_id'")
        status = json.loads(self.run_tool("status", work["id"], "--json").stdout)
        self.assertEqual(status["status"], "abandoned")
        self.assertEqual(json.loads(self.run_tool("todo", "show", todo["id"], "--json").stdout)["status"], "pending")

    def test_blocked_requires_executable_next_step_and_remains_open(self):
        todo = self.add()
        self.assertNotEqual(self.update(todo, status="blocked", note="No access").returncode, 0)
        result = self.update(todo, status="blocked", note="Needs user credentials", next_step="User connects test account")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_tool("todo", "check", "--json", check=False).returncode, 3)

    def test_linked_work_cannot_finish_complete_until_checklist_closed(self):
        work = self.start("Implement", "src")
        parent = self.add(work_task=work["id"])
        child = self.add("Validation", parent=parent["id"])
        result = self.run_tool("finish", work["id"], "--summary", "All done", "--json", check=False)
        self.assertEqual(result.returncode, 3)
        self.assertIn("todo", result.stderr)
        self.assertEqual(json.loads(self.run_tool("status", work["id"], "--json").stdout)["status"], "active")
        self.assertEqual(self.update(child, status="done", evidence="Verified").returncode, 0)
        self.assertEqual(self.update(parent, status="done", evidence="Verified all acceptance criteria").returncode, 0)
        self.run_tool("finish", work["id"], "--summary", "All done", "--json")

    def test_repository_isolation_and_worktree_federation(self):
        self.git("-C", self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-m", "Fixture")
        linked = self.workspace / "linked"
        self.git("-C", self.repo, "worktree", "add", "-b", "worker", linked)
        todo = self.add()
        board = json.loads(self.run_tool("todo", "list", "--json", cwd=linked).stdout)
        self.assertEqual(board["items"][0]["id"], todo["id"])
        self.assertEqual(json.loads(self.run_tool("todo", "list", "--json", cwd=self.other_repo).stdout)["open_count"], 0)
        self.assertNotEqual(self.run_tool("todo", "show", todo["id"], "--json", cwd=self.other_repo, check=False).returncode, 0)

    def test_child_cannot_be_added_under_closed_parent(self):
        todo = self.add()
        done = self.update(todo, status="done", evidence="Verified")
        self.assertEqual(done.returncode, 0, done.stderr)
        result = self.run_tool("todo", "add", "Hidden new work", "--parent", todo["id"],
                               "--acceptance", "Verified", "--json", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_session_start_restores_board_even_after_claims_expire(self):
        todo = self.add("Unfinished obligation")
        for client in ("codex", "claude", "pi"):
            with self.subTest(client=client):
                output = self.hook(client=client, event="SessionStart")
                context = output["task_context"] if client == "pi" else output["hookSpecificOutput"]["additionalContext"]
                self.assertIn(todo["id"], context)
                self.assertIn("Unfinished obligation", context)

    def test_stop_guard_targets_own_tree_and_handles_blocked_without_loop(self):
        work = self.start("Implement", "src")
        self.run_tool("session", work["id"], "--client", "codex", "--session", "session", "--json")
        todo = self.add(work_task=work["id"])
        self.add("Other agent's task")
        stopped = self.hook(event="Stop")
        self.assertEqual(stopped["decision"], "block")
        self.assertIn(todo["id"], stopped["reason"])
        self.assertEqual(self.hook(session="other-session", event="Stop"), {})
        self.assertEqual(self.hook(event="Stop", stop_hook_active=True), {})
        result = self.update(todo, status="blocked", note="Needs external access", next_step="User connects account")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hook(event="Stop"), {})

    def test_post_tool_reminder_is_deduplicated_but_new_revision_delivers(self):
        todo = self.add()
        self.assertIn(todo["id"], str(self.hook()))
        self.assertEqual(self.hook(), {})
        self.assertEqual(self.update(todo, note="Tests next").returncode, 0)
        self.assertIn("Tests next", str(self.hook()))

    def test_check_is_not_fooled_by_limit_or_empty_repository(self):
        closed = self.add("Closed")
        self.assertEqual(self.update(closed, status="done", evidence="Verified").returncode, 0)
        self.add("Still open")
        result = self.run_tool("todo", "check", "--limit", "1", "--json", check=False)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["open_count"], 1)
        empty = self.run_tool("todo", "check", "--json", cwd=self.other_repo, check=False)
        self.assertEqual(empty.returncode, 3)
        self.assertFalse(json.loads(empty.stdout)["tracked"])

    def test_worker_execution_tracks_assigned_child_and_parent_waits(self):
        parent_work = self.start("Integrate", "integration")
        worker = self.start("Validate", "tests")
        parent = self.add(work_task=parent_work["id"])
        child = self.add("Worker validation", parent=parent["id"], work_task=worker["id"])
        self.run_tool("session", worker["id"], "--client", "claude", "--session", "worker", "--json")
        output = self.hook(client="claude", session="worker", event="Stop")
        self.assertEqual(output["decision"], "block")
        self.assertIn(child["id"], output["reason"])
        self.assertNotIn(parent["id"] + " r", output["reason"])
        self.assertEqual(self.update(child, status="done", evidence="Worker checks passed").returncode, 0)
        self.run_tool("finish", worker["id"], "--summary", "Validation passed", "--json")
        self.assertEqual(self.run_tool("finish", parent_work["id"], "--summary", "Integrated", "--json", check=False).returncode, 3)

    def test_resume_relinks_existing_obligation_without_reviving_old_claims(self):
        old = self.start("Old run", "src")
        todo = self.add(work_task=old["id"])
        with sqlite3.connect(self.state / "tasks.sqlite3") as connection:
            connection.execute("UPDATE tasks SET heartbeat_at='2000-01-01T00:00:00Z' WHERE id=?", (old["id"],))
        self.assertEqual(json.loads(self.run_tool("status", old["id"], "--json").stdout)["status"], "abandoned")
        resumed = self.start("Resume", "src")
        result = self.update(todo, work_task=resumed["id"], note="Resumed from retained evidence")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["work_task"], resumed["id"])
        self.assertEqual(json.loads(self.run_tool("status", old["id"], "--json").stdout)["claims"], [])
        self.assertEqual(json.loads(self.run_tool("todo", "list", "--json").stdout)["total_count"], 1)

    def test_link_cannot_borrow_unauthenticated_or_other_repository_execution(self):
        work = self.start("Owner", "src")
        self.tokens.clear()
        result = self.run_tool("todo", "add", "Forge", "--acceptance", "Checked", "--work-task", work["id"], "--json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.tokens[work["id"]] = work["task_token"]
        result = self.run_tool("todo", "add", "Cross repo", "--acceptance", "Checked", "--work-task", work["id"], "--json", cwd=self.other_repo, check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_startup_guidance_does_not_create_runtime_files_in_repository(self):
        output = self.hook(event="SessionStart")
        self.assertIn("agent-work todo", output["hookSpecificOutput"]["additionalContext"])
        self.assertFalse((self.state / "tasks.sqlite3").exists())
        self.assertEqual(list(self.repo.glob("*")), [self.repo / ".git"])

    def test_blank_acceptance_and_oversized_note_are_rejected(self):
        result = self.run_tool("todo", "add", "Obligation", "--acceptance", "  ", "--json", check=False)
        self.assertNotEqual(result.returncode, 0)
        todo = self.add()
        self.assertNotEqual(self.update(todo, note="a" * 4097).returncode, 0)

    def test_checklist_context_and_inbox_are_delivered_together(self):
        work = self.start("Owner", "src")
        sender = self.start("Sender", "tests")
        self.run_tool("session", work["id"], "--client", "codex", "--session", "session", "--json")
        todo = self.add(work_task=work["id"])
        self.run_tool("broadcast", sender["id"], "--message", "Do not lose this inbox message", "--json")
        context = self.hook()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Do not lose this inbox message", context)
        self.assertIn(todo["id"], context)

    def test_hook_context_is_bounded_without_truncating_ledger_evidence(self):
        for number in range(15):
            todo = self.add(f"Obligation {number}")
            self.assertEqual(self.update(todo, note="界" * 1300).returncode, 0)
        output = self.hook(event="SessionStart")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(context.encode("utf-8")), 20000)
        board = json.loads(self.run_tool("todo", "list", "--limit", "1", "--json").stdout)
        self.assertEqual(board["open_count"], 15)
        self.assertTrue(board["truncated"])
        self.assertEqual(len(board["items"][0]["note"]), 1300)


if __name__ == "__main__":
    unittest.main()
