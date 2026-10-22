import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import unittest

from Tests import test_agent_work as base


class MessagingTests(unittest.TestCase):
    setUp = base.AgentWorkTests.setUp
    tearDown = base.AgentWorkTests.tearDown
    git = base.AgentWorkTests.git
    run_tool = base.AgentWorkTests.run_tool
    start = base.AgentWorkTests.start

    def empty_task(self, name="Requester"):
        return json.loads(self.run_tool("start", "--task", name, "--no-claims", "--json").stdout)

    def request(self, task, *paths, key=None):
        args = ["request-claim", task["id"], *paths, "--message", "Needed for the assigned fix"]
        if key:
            args.extend(("--key", key))
        return json.loads(self.run_tool(*args, "--json").stdout)

    def respond(self, task, request, decision="yield", *extra):
        return json.loads(self.run_tool("respond", task["id"], request["id"],
                                        "--revision", str(request["revision"]),
                                        "--decision", decision, *extra, "--json").stdout)

    def inbox(self, task):
        return json.loads(self.run_tool("inbox", task["id"], "--json").stdout)

    def status(self, task):
        return json.loads(self.run_tool("status", task["id"], "--json").stdout)

    def test_unclaimed_registration_and_repo_scoped_broadcast_snapshot(self):
        sender = self.empty_task()
        receiver = self.start("Receiver", "src/a")
        other = self.start("Other repo", "src/a", repo=self.other_repo)
        result = json.loads(self.run_tool("broadcast", sender["id"], "--message", "Interface changing", "--json").stdout)
        self.assertEqual(result["recipients"], [receiver["id"]])
        self.assertEqual(self.inbox(receiver)[-1]["body"]["note"], "Interface changing")
        self.assertEqual(self.inbox(other), [])
        late = self.empty_task("Late joiner")
        self.assertEqual(self.inbox(late), [])
        self.assertEqual(sender["claims"], [])

    def test_exact_transfer_requires_quiescence_and_records_both_histories(self):
        owner = self.start("Owner", "src/parser")
        worker = self.empty_task()
        request = self.request(worker, "src/parser", key="parser-fix")
        self.assertEqual(request["status"], "pending")
        self.assertEqual(self.request(worker, "src/parser", key="parser-fix")["id"], request["id"])
        refused = self.run_tool("respond", owner["id"], request["id"], "--revision", "1",
                                "--decision", "yield", "--json", check=False)
        self.assertNotEqual(refused.returncode, 0)
        granted = self.respond(owner, request, "yield", "--quiesced", "--message", "Edits stopped; existing diff retained")
        self.assertEqual(granted["status"], "granted")
        self.assertEqual(self.status(owner)["claims"], [])
        self.assertEqual(self.status(worker)["claims"], ["src/parser"])
        for task in (owner, worker):
            history = json.loads(self.run_tool("history", task["id"], "--json").stdout)
            self.assertIn("claim-transfer", [event["kind"] for event in history])

    def test_broad_claim_yields_hole_and_never_automatically_reclaims_it(self):
        owner = self.start("Broad owner", ".")
        worker = self.empty_task()
        request = self.request(worker, "src/parser")
        self.respond(owner, request, "yield", "--quiesced")
        self.assertEqual(self.status(owner)["exclusions"], [{"claim": ".", "path": "src/parser"}])
        denied = self.run_tool("check-write", owner["id"], "src/parser/file.py", "--json", check=False)
        self.assertEqual(denied.returncode, 3)
        allowed = json.loads(self.run_tool("check-write", owner["id"], "src/other.py", "--json").stdout)
        self.assertTrue(allowed["allowed"])
        self.run_tool("finish", worker["id"], "--summary", "done", "--json")
        denied = self.run_tool("check-write", owner["id"], "src/parser/file.py", "--json", check=False)
        self.assertEqual(denied.returncode, 3)
        reacquired = self.request(owner, "src/parser")
        self.assertEqual(reacquired["status"], "granted")
        self.run_tool("check-write", owner["id"], "src/parser/file.py", "--json")

    def test_multi_owner_barrier_and_cancellation_resume_paused_scope(self):
        first = self.start("First", "src/a")
        second = self.start("Second", "src/b")
        worker = self.empty_task()
        request = self.request(worker, "src")
        self.assertEqual(set(request["owners"]), {first["id"], second["id"]})
        self.assertEqual(self.respond(first, request, "yield", "--quiesced")["status"], "pending")
        self.assertEqual(self.status(worker)["claims"], [])
        self.assertEqual(self.run_tool("check-write", first["id"], "src/a/f", "--json", check=False).returncode, 3)
        self.run_tool("cancel-request", worker["id"], request["id"], "--json")
        self.run_tool("check-write", first["id"], "src/a/f", "--json")
        self.assertEqual(self.status(first)["claims"], ["src/a"])
        request = self.request(worker, "src")
        self.respond(first, request, "yield", "--quiesced")
        self.assertEqual(self.respond(second, request, "yield", "--quiesced")["status"], "granted")
        self.assertEqual(self.status(worker)["claims"], ["src"])

    def test_denial_deferral_and_wrong_actor_never_transfer(self):
        owner = self.start("Owner", "src")
        worker = self.empty_task()
        stranger = self.empty_task("Stranger")
        request = self.request(worker, "src")
        invalid = self.run_tool("respond", stranger["id"], request["id"], "--revision", "1",
                                "--decision", "yield", "--quiesced", "--json", check=False)
        self.assertNotEqual(invalid.returncode, 0)
        self.respond(owner, request, "defer", "--until", "2099-01-01T00:00:00Z")
        self.assertEqual(self.status(worker)["claims"], [])
        self.respond(owner, request, "deny", "--message", "Still modifying the entire subtree")
        self.assertEqual(self.status(owner)["claims"], ["src"])
        self.assertEqual(self.status(worker)["claims"], [])

    def test_revision_invalidates_approvals_and_counterproposal_is_advisory(self):
        owner = self.start("Owner", "src")
        worker = self.empty_task()
        request = self.request(worker, "src")
        offered = self.respond(owner, request, "counter", "--path", "src/parser", "--message", "Can spare this")
        self.assertEqual(offered["status"], "pending")
        revised = json.loads(self.run_tool("revise-request", worker["id"], request["id"], "src/parser", "--json").stdout)
        self.assertEqual(revised["revision"], 2)
        stale = self.run_tool("respond", owner["id"], request["id"], "--revision", "1",
                              "--decision", "yield", "--quiesced", "--json", check=False)
        self.assertNotEqual(stale.returncode, 0)
        self.assertEqual(self.respond(owner, revised, "yield", "--quiesced")["status"], "granted")

    def test_two_competitors_cannot_both_acquire_scope(self):
        first, second = self.empty_task("First"), self.empty_task("Second")
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda task: self.request(task, "src/shared"), (first, second)))
        self.assertEqual(sorted(result["status"] for result in results), ["granted", "pending"])
        claims = [self.status(task)["claims"] for task in (first, second)]
        self.assertEqual(sum("src/shared" in scope for scope in claims), 1)

    def test_changed_claims_invalidate_multi_owner_acceptances(self):
        first = self.start("First", "src/a")
        second = self.start("Second", "src/b")
        worker = self.empty_task()
        request = self.request(worker, "src")
        self.respond(first, request, "yield", "--quiesced")
        self.run_tool("claim", second["id"], "src/c", "--json")
        result = self.respond(second, request, "yield", "--quiesced")
        self.assertEqual(result["status"], "needs-review")
        self.assertEqual(self.status(worker)["claims"], [])
        self.run_tool("check-write", first["id"], "src/a/f", "--json")

    def test_wait_cycles_are_reported_without_seizing_claims(self):
        first = self.start("First", "src/a")
        second = self.start("Second", "src/b")
        self.request(first, "src/b")
        result = self.request(second, "src/a")
        self.assertTrue(result["wait_cycle"])
        self.assertEqual(self.status(first)["claims"], ["src/a"])

    def test_missing_or_foreign_token_cannot_respond_or_finish(self):
        owner = self.start("Owner", "src")
        worker = self.empty_task()
        request = self.request(worker, "src")
        self.tokens[owner["id"]] = self.tokens[worker["id"]]
        self.assertNotEqual(self.run_tool("respond", owner["id"], request["id"], "--revision", "1",
                                          "--decision", "yield", "--quiesced", "--json", check=False).returncode, 0)
        self.assertNotEqual(self.run_tool("finish", owner["id"], "--summary", "wrong actor", "--json", check=False).returncode, 0)

    def test_finish_cancels_requests_and_releases_other_owners_pause(self):
        first = self.start("First", "src/a")
        second = self.start("Second", "src/b")
        worker = self.empty_task()
        request = self.request(worker, "src")
        self.respond(first, request, "yield", "--quiesced")
        self.run_tool("finish", worker["id"], "--summary", "cancelled fix", "--json")
        self.run_tool("check-write", first["id"], "src/a/f", "--json")

    def test_external_paths_and_oversized_notes_are_rejected(self):
        worker = self.empty_task()
        self.assertNotEqual(self.run_tool("request-claim", worker["id"], "../outside", "--json", check=False).returncode, 0)
        self.assertNotEqual(self.run_tool("broadcast", worker["id"], "--message", "x" * 4097, "--json", check=False).returncode, 0)

    def test_credentials_survive_resume_without_exposing_token_in_status(self):
        task = self.empty_task()
        credential = Path(task["credential_file"])
        self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
        self.assertEqual(credential.read_text().strip(), task["task_token"])
        self.assertNotIn("task_token", self.status(task))
        result = subprocess.run([str(base.TOOL), "broadcast", task["id"], "--message", "Resumed", "--json"],
                                text=True, capture_output=True, env={**os.environ,
                                "AGENT_WORK_STATE_DIR": str(self.state), "AGENT_WORK_TOKEN": "",
                                "AGENT_WORK_TOKEN_FILE": str(credential)})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_request_across_an_existing_hole_reaches_every_effective_owner(self):
        broad = self.start("Broad", ".")
        first = self.empty_task("First")
        request = self.request(first, "src/parser")
        self.respond(broad, request, "yield", "--quiesced")
        second = self.empty_task("Second")
        request = self.request(second, "src")
        self.assertEqual(set(request["owners"]), {broad["id"], first["id"]})
        self.respond(broad, request, "yield", "--quiesced")
        self.assertEqual(self.respond(first, request, "yield", "--quiesced")["status"], "granted")
        self.run_tool("check-write", second["id"], "src/parser/a.py", "src/other.py", "--json")
        self.assertEqual(self.run_tool("check-write", broad["id"], "src/a.py", "--json", check=False).returncode, 3)

    def test_unknown_message_is_a_clean_cli_error(self):
        task = self.empty_task()
        result = self.run_tool("message", task["id"], "missing", "--json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_owner_can_reacquire_a_free_hole_through_explicit_claim(self):
        owner = self.start("Broad", ".")
        worker = self.empty_task()
        request = self.request(worker, "src/parser")
        self.respond(owner, request, "yield", "--quiesced")
        self.run_tool("finish", worker["id"], "--summary", "done", "--json")
        self.run_tool("claim", owner["id"], ".", "--json")
        self.run_tool("check-write", owner["id"], "src/parser/a", "--json")

    def test_routine_claim_updates_coalesce_without_fabricating_acknowledgement(self):
        observer = self.empty_task("Observer")
        owner = self.start("Owner", "src/a")
        self.run_tool("claim", owner["id"], "src/b", "--json")
        updates = [item for item in self.inbox(observer) if item["kind"] == "claim-changed"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["body"]["claims"], ["src/a", "src/b"])
        history = json.loads(self.run_tool("inbox", observer["id"], "--all", "--json").stdout)
        superseded = [item for item in history if item["state"] == "superseded"]
        self.assertEqual(len(superseded), 1)
        self.assertIsNone(superseded[0]["acknowledged_at"])

    def test_repo_root_request_does_not_take_a_task_external_scratch_claim(self):
        external_path = str(self.workspace / "outside-repository")
        owner = self.start("External scratch work", external_path)
        worker = self.empty_task()
        result = self.request(worker, ".")
        self.assertEqual(result["status"], "granted")
        self.assertEqual(result["owners"], [])
        self.assertEqual(self.status(owner)["claims"], [external_path])
        self.run_tool("finish", worker["id"], "--summary", "done", "--json")
        self.assertEqual(self.request(owner, ".")["status"], "granted")
        self.assertEqual(self.status(owner)["claims"], [".", external_path])

    def test_check_write_accepts_owned_external_scopes_and_rejects_unowned_paths(self):
        external = self.workspace / "external-scratch"
        additional = self.workspace / "additional-scratch"
        owner = self.start("External scratch work", str(external))
        self.run_tool("claim", owner["id"], str(additional), "--json")
        for path in (external, external / "result.txt", additional / "result.txt"):
            with self.subTest(path=path):
                result = self.run_tool("check-write", owner["id"], str(path), "--json")
                self.assertTrue(json.loads(result.stdout)["allowed"])
        for path in (self.workspace / "unclaimed" / "result.txt", "unowned.py"):
            with self.subTest(path=path):
                result = self.run_tool("check-write", owner["id"], str(path), "--json", check=False)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertFalse(json.loads(result.stdout)["allowed"])

    def test_transfer_refreshes_each_owner_snapshot_for_observers(self):
        observer = self.empty_task("Observer")
        broad = self.start("Broad owner", "src")
        exact = self.start("Exact owner", "assets/icon.svg")
        worker = self.empty_task()
        owners = (broad, exact)
        previous = {item["sender"]: item for item in self.inbox(observer)
                    if item["kind"] == "claim-changed"}
        self.assertEqual(set(previous), {owner["id"] for owner in owners})
        request = self.request(worker, "src/parser", "assets/icon.svg")
        self.assertEqual(set(request["owners"]), set(previous))
        self.respond(broad, request, "yield", "--quiesced")
        self.assertEqual(self.status(broad)["exclusions"], [])
        self.assertEqual(self.respond(exact, request, "yield", "--quiesced")["status"], "granted")
        updates = [item for item in self.inbox(observer) if item["kind"] == "claim-changed"]
        self.assertEqual(len(updates), 3)
        for owner in (*owners, worker):
            with self.subTest(owner=owner["id"]):
                notice, = [item for item in updates if item["sender"] == owner["id"]]
                status = self.status(owner)
                self.assertEqual(notice["body"]["claims"], status["claims"])
                self.assertEqual(notice["body"]["exclusions"], status["exclusions"])
        history = json.loads(self.run_tool("inbox", observer["id"], "--all", "--json").stdout)
        for prior in previous.values():
            notice, = [item for item in history if item["id"] == prior["id"]]
            self.assertEqual(notice["state"], "superseded")
            self.assertIsNone(notice["acknowledged_at"])


if __name__ == "__main__":
    unittest.main()
