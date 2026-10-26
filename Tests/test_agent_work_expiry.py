import concurrent.futures
import contextlib
import datetime as dt
import json
import os
import sqlite3
import sys
import unittest
from unittest import mock

from Tests import test_agent_work as base

sys.path.insert(0, str(base.ROOT / "Tools"))
import agent_work_messages as messages


class ClaimExpiryTests(base.AgentWorkFixture, unittest.TestCase):
    def core(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"AGENT_WORK_STATE_DIR": str(self.state)}).start()
        return messages.load_core()

    def age(self, task, hours=16):
        stamp = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
        with contextlib.closing(sqlite3.connect(self.state / "tasks.sqlite3")) as connection, connection:
            connection.execute("UPDATE tasks SET heartbeat_at=? WHERE id=?",
                               (stamp.isoformat(timespec="seconds"), task["id"]))

    def record(self, task):
        return json.loads(self.run_tool("status", task["id"], "--json").stdout)

    def test_status_expires_idle_active_and_waiting_tasks_across_repositories(self):
        first = self.start("Idle owner", "src")
        second = self.start("Waiting owner", "src", repo=self.other_repo)
        self.run_tool("heartbeat", second["id"], "--status", "waiting", "--json")
        for task in (first, second):
            self.age(task)
        self.assertEqual(json.loads(self.run_tool("status", "--json").stdout), [])
        for task in (first, second):
            record = self.record(task)
            self.assertEqual(record["status"], "abandoned")
            self.assertEqual(record["claims"], [])
            history = json.loads(self.run_tool("history", task["id"], "--json").stdout)
            expired = [event for event in history if event["kind"] == "claims-expired"]
            self.assertEqual(len(expired), 1)
            self.assertEqual(expired[0]["details"]["claims"], ["src"])
            self.assertEqual(expired[0]["details"]["reason"], "heartbeat-timeout")
            self.assertTrue(os.path.isdir(task["scratch"]))

    def test_six_hour_boundary_and_heartbeat_renewal(self):
        owner = self.start("Owner", "src")
        h = self.core()
        started = dt.datetime.fromisoformat(owner["heartbeat_at"].replace("Z", "+00:00"))
        with mock.patch.object(h, "utc_now", return_value=started + dt.timedelta(hours=6, seconds=-1)):
            with contextlib.closing(h.database()) as connection:
                self.assertEqual(h.task_record(connection, owner["id"])["status"], "active")
        self.age(owner, hours=5)
        renewed = json.loads(self.run_tool("heartbeat", owner["id"], "--json").stdout)
        heartbeat = dt.datetime.fromisoformat(renewed["heartbeat_at"].replace("Z", "+00:00"))
        with mock.patch.object(h, "utc_now", return_value=heartbeat + dt.timedelta(hours=6)):
            with contextlib.closing(h.database()) as connection:
                self.assertEqual(h.task_record(connection, owner["id"])["status"], "abandoned")

    def test_fresh_heartbeat_keeps_old_task_claimed_even_after_deadline(self):
        owner = self.start("Long running owner", "src")
        with contextlib.closing(sqlite3.connect(self.state / "tasks.sqlite3")) as connection, connection:
            connection.execute("UPDATE tasks SET started_at='2020-01-01T00:00:00Z', deadline_at=started_at WHERE id=?",
                               (owner["id"],))
        self.run_tool("heartbeat", owner["id"], "--json")
        self.assertEqual(self.record(owner)["claims"], ["src"])
        conflict = self.run_tool("start", "--task", "Competitor", "--scope", "src", "--json", check=False)
        self.assertEqual(conflict.returncode, 3)

    def test_expired_session_cannot_revive_or_write_and_scope_can_be_reclaimed(self):
        owner = self.start("Old session", "src")
        self.run_tool("session", owner["id"], "--client", "codex", "--session", "old-session", "--json")
        self.age(owner)
        denied = self.run_tool("check-write", owner["id"], "src/file", "--json", check=False)
        self.assertEqual(denied.returncode, 3)
        self.assertFalse(json.loads(denied.stdout)["allowed"])
        self.assertNotEqual(self.run_tool("heartbeat", owner["id"], "--json", check=False).returncode, 0)
        self.assertIsNone(self.record(owner)["transport"])
        replacement = self.start("Replacement", "src")
        self.assertEqual(replacement["claims"], ["src"])

    def test_reboot_clears_fresh_claims_and_sessions_in_all_repositories(self):
        owners = [self.start("First", "src"), self.start("Other", "src", repo=self.other_repo)]
        self.run_tool("session", owners[0]["id"], "--client", "codex", "--session", "previous-boot", "--json")
        h = self.core()
        boot_time = h.utc_now() + dt.timedelta(seconds=1)
        with mock.patch.object(h, "boot_session", return_value=("next-boot", boot_time)):
            with contextlib.closing(h.database()) as connection:
                for owner in owners:
                    self.assertEqual(h.task_record(connection, owner["id"])["status"], "abandoned")
                    event = connection.execute("SELECT details_json FROM task_events WHERE task_id=? AND kind='claims-expired'",
                                               (owner["id"],)).fetchone()
                    self.assertEqual(json.loads(event[0])["reason"], "reboot")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0], 0)
                # Opening again in the same boot must retain newly registered work.
                connection.execute("UPDATE tasks SET status='active', heartbeat_at=? WHERE id=?",
                                   (h.iso_time(h.utc_now()), owners[0]["id"]))
                connection.commit()
            with contextlib.closing(h.database()) as connection:
                self.assertEqual(h.task_record(connection, owners[0]["id"])["status"], "active")

    def test_first_upgrade_detects_claims_from_before_current_boot(self):
        owner = self.start("Legacy previous boot", "src")
        fresh = self.start("Current boot", "tests")
        h = self.core()
        boot_time = h.utc_now().replace(microsecond=0) - dt.timedelta(seconds=1)
        with contextlib.closing(sqlite3.connect(self.state / "tasks.sqlite3")) as connection, connection:
            connection.execute("DROP TABLE ledger_meta")
            connection.execute("PRAGMA user_version=1")
            connection.execute("UPDATE tasks SET started_at=? WHERE id=?",
                               (h.iso_time(boot_time - dt.timedelta(seconds=1)), owner["id"]))
        with mock.patch.object(h, "boot_session", return_value=("first-known-boot", boot_time)):
            with contextlib.closing(h.database()) as connection:
                self.assertEqual(h.task_record(connection, owner["id"])["status"], "abandoned")
                self.assertEqual(h.task_record(connection, fresh["id"])["status"], "active")

    def test_missing_boot_information_still_expires_idle_claims(self):
        owner = self.start("Idle", "src")
        fresh = self.start("Fresh", "tests")
        self.age(owner)
        h = self.core()
        with mock.patch.object(h, "boot_session", return_value=(None, None)):
            with contextlib.closing(h.database()) as connection:
                self.assertEqual(h.task_record(connection, owner["id"])["status"], "abandoned")
                self.assertEqual(h.task_record(connection, fresh["id"])["status"], "active")

    def test_existing_connection_sweeps_expiry_without_reopening(self):
        owner = self.start("Watcher owner", "src")
        h = self.core()
        with contextlib.closing(h.database()) as connection:
            self.age(owner)
            h.expire_claims(connection)
            self.assertEqual(h.task_record(connection, owner["id"])["status"], "abandoned")
            self.assertEqual(h.claims_by_task(connection, [owner["id"]])[owner["id"]], [])

    def test_concurrent_heartbeat_is_rechecked_after_taking_writer_lock(self):
        owner = self.start("Owner renewing", "src")
        h = self.core()
        with contextlib.closing(h.database()) as connection:
            self.age(owner)
            renewed = False
            def before_transaction(query):
                nonlocal renewed
                if query == "BEGIN IMMEDIATE" and not renewed:
                    renewed = True
                    with contextlib.closing(sqlite3.connect(self.state / "tasks.sqlite3")) as writer, writer:
                        writer.execute("UPDATE tasks SET heartbeat_at=? WHERE id=?", (h.iso_time(h.utc_now()), owner["id"]))
            connection.set_trace_callback(before_transaction)
            h.expire_claims(connection)
            self.assertTrue(renewed)
            self.assertEqual(h.task_record(connection, owner["id"])["status"], "active")
            self.assertEqual(h.claims_by_task(connection, [owner["id"]])[owner["id"]], ["src"])

    def test_expired_requester_releases_other_owners_pause(self):
        first = self.start("First", "src/a")
        second = self.start("Second", "src/b")
        worker = self.start("Requester", "tests")
        request = json.loads(self.run_tool("request-claim", worker["id"], "src", "--message", "Need scope", "--json").stdout)
        self.run_tool("respond", first["id"], request["id"], "--revision", "1", "--decision", "yield", "--quiesced", "--json")
        self.age(worker)
        result = json.loads(self.run_tool("request", first["id"], request["id"], "--json").stdout)
        self.assertEqual(result["status"], "cancelled")
        self.run_tool("check-write", first["id"], "src/a/file", "--json")

    def test_expiry_cancels_negotiation_and_unpauses_other_owner(self):
        first = self.start("First", "src/a")
        second = self.start("Second", "src/b")
        worker = self.start("Requester", "tests")
        request = json.loads(self.run_tool("request-claim", worker["id"], "src", "--message", "Need scope", "--json").stdout)
        self.run_tool("respond", second["id"], request["id"], "--revision", "1", "--decision", "yield", "--quiesced", "--json")
        self.age(first)
        result = json.loads(self.run_tool("request", worker["id"], request["id"], "--json").stdout)
        self.assertEqual(result["status"], "cancelled")
        self.run_tool("check-write", second["id"], "src/b/file", "--json")
        self.assertEqual(self.record(worker)["claims"], ["tests"])

    def test_simultaneous_reclaim_has_one_winner_and_one_expiry_event(self):
        owner = self.start("Idle owner", "src")
        self.age(owner)
        def compete(name):
            return self.run_tool("start", "--task", name, "--scope", "src", "--json", check=False).returncode
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(compete, ("First", "Second")))
        self.assertEqual(sorted(codes), [0, 3])
        history = json.loads(self.run_tool("history", owner["id"], "--json").stdout)
        self.assertEqual(sum(event["kind"] == "claims-expired" for event in history), 1)


if __name__ == "__main__":
    unittest.main()
