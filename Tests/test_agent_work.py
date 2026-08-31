import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "Tools/agent-work"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class AgentWorkTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.state = self.workspace / "state"
        self.repo = self.workspace / "repo"
        self.other_repo = self.workspace / "other"
        self.git("init", "--initial-branch=main", self.repo)
        self.git("init", "--initial-branch=main", self.other_repo)

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        return subprocess.run(
            ["git", *map(str, arguments)],
            check=True,
            text=True,
            capture_output=True,
        )

    def run_tool(self, *arguments, cwd=None, check=True):
        result = subprocess.run(
            [TOOL, *map(str, arguments)],
            cwd=cwd or self.repo,
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "AGENT_WORK_STATE_DIR": str(self.state)},
        )
        if check and result.returncode:
            self.fail(result.stderr or result.stdout)
        return result

    def start(self, description, scope, *, repo=None, owner=None):
        arguments = [
            "start",
            "--task",
            description,
            "--scope",
            scope,
            "--timebox",
            "45m",
        ]
        if owner:
            arguments.extend(("--owner", owner))
        arguments.append("--json")
        return json.loads(self.run_tool(*arguments, cwd=repo).stdout)

    def test_transcript_style_heartbeat_records_actor_and_note(self):
        task = self.start(
            "Integrate and verify recent HTTP RFC implementations",
            "integration/recent-http-rfcs",
        )

        heartbeat = self.run_tool(
            "heartbeat",
            "--task",
            task["id"],
            "--agent",
            "codex-root",
            "--note",
            "Focused suites green; preparing full validation.",
            "--json",
        )
        record = json.loads(heartbeat.stdout)
        history = json.loads(self.run_tool("history", task["id"], "--json").stdout)

        self.assertEqual(record["owner"], "codex-root")
        self.assertEqual(
            record["latest_note"],
            "Focused suites green; preparing full validation.",
        )
        self.assertEqual([event["kind"] for event in history], ["start", "heartbeat"])
        self.assertEqual(history[-1]["actor"], "codex-root")
        self.assertEqual(history[-1]["note"], record["latest_note"])

    def test_existing_positional_lifecycle_remains_supported(self):
        task = self.start("Repair parser", "src/parser", owner="codex-root")

        claimed = json.loads(
            self.run_tool("claim", task["id"], "tests/parser", "--json").stdout
        )
        heartbeat = json.loads(self.run_tool("--json", "heartbeat", task["id"]).stdout)
        finished = json.loads(
            self.run_tool(
                "finish",
                task["id"],
                "--summary",
                "Parser repaired",
                "--changed",
                "src/parser",
                "--check",
                "focused parser tests passed",
                "--json",
            ).stdout
        )

        self.assertEqual(claimed["claims"], ["src/parser", "tests/parser"])
        self.assertEqual(heartbeat["status"], "active")
        self.assertEqual(heartbeat["owner"], "codex-root")
        self.assertEqual(finished["status"], "complete")
        self.assertEqual(finished["summary"], "Parser repaired")

    def test_status_defaults_to_current_repo_and_accepts_repo_filter(self):
        current = self.start("Current repository task", "src/current")
        other = self.start("Other repository task", "src/other", repo=self.other_repo)

        default_board = json.loads(self.run_tool("status", "--json").stdout)
        filtered_board = json.loads(
            self.run_tool("status", "--repo", self.other_repo, "--json").stdout
        )
        global_board = json.loads(
            self.run_tool("status", "--all-repos", "--json").stdout
        )

        self.assertEqual([task["id"] for task in default_board], [current["id"]])
        self.assertEqual([task["id"] for task in filtered_board], [other["id"]])
        self.assertEqual(
            {task["id"] for task in global_board},
            {current["id"], other["id"]},
        )

    def test_status_history_is_bounded(self):
        tasks = [self.start(f"Task {index}", f"scope/{index}") for index in range(3)]
        for task in tasks:
            self.run_tool("finish", task["id"], "--summary", "done")

        board = json.loads(
            self.run_tool("status", "--all", "--limit", "2", "--json").stdout
        )

        self.assertEqual(len(board), 2)
        self.assertEqual(
            [task["id"] for task in board], [tasks[2]["id"], tasks[1]["id"]]
        )

    def test_stale_board_uses_the_same_repository_filter(self):
        current = self.start("Stale current task", "src/current")
        other = self.start("Stale other task", "src/other", repo=self.other_repo)
        database = sqlite3.connect(self.state / "tasks.sqlite3")
        database.execute("UPDATE tasks SET heartbeat_at = '2020-01-01T00:00:00Z'")
        database.commit()
        database.close()

        default_board = json.loads(
            self.run_tool("stale", "--after", "1m", "--json").stdout
        )
        filtered_board = json.loads(
            self.run_tool(
                "stale",
                "--after",
                "1m",
                "--repo",
                self.other_repo,
                "--json",
            ).stdout
        )

        self.assertEqual([task["id"] for task in default_board], [current["id"]])
        self.assertEqual([task["id"] for task in filtered_board], [other["id"]])

    def test_named_claim_is_retained_in_history(self):
        task = self.start("Expand parser repair", "src/parser")

        claimed = json.loads(
            self.run_tool(
                "claim",
                "--task",
                task["id"],
                "tests/parser",
                "--json",
            ).stdout
        )
        history = json.loads(
            self.run_tool("history", "--task", task["id"], "--json").stdout
        )

        self.assertEqual(claimed["claims"], ["src/parser", "tests/parser"])
        self.assertEqual([event["kind"] for event in history], ["start", "claim"])
        self.assertEqual(history[-1]["details"], {"claims": ["tests/parser"]})

    def test_linked_worktree_cannot_bypass_scope_conflicts(self):
        self.git("-C", self.repo, "config", "user.name", "Test Fixture")
        self.git("-C", self.repo, "config", "user.email", "fixture@example.invalid")
        self.git("-C", self.repo, "commit", "--allow-empty", "-m", "fixture")
        worktree = self.workspace / "worktree"
        self.git("-C", self.repo, "worktree", "add", "--detach", worktree)
        owner = self.start("Own parser", "src/parser")

        conflict = self.run_tool(
            "start",
            "--task",
            "Overlap parser",
            "--scope",
            "src/parser/nested",
            "--json",
            cwd=worktree,
            check=False,
        )

        self.assertEqual(conflict.returncode, 3)
        payload = json.loads(conflict.stdout)
        self.assertEqual(payload["error"], "scope conflict")
        self.assertEqual(payload["conflicts"][0]["task_id"], owner["id"])

    def test_legacy_database_migrates_without_losing_tasks(self):
        self.state.mkdir()
        database = sqlite3.connect(self.state / "tasks.sqlite3")
        database.executescript(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                repo_root TEXT NOT NULL,
                git_common_dir TEXT,
                task TEXT NOT NULL,
                worktree TEXT NOT NULL,
                branch TEXT,
                scratch TEXT NOT NULL,
                pid INTEGER,
                pid_started TEXT,
                started_at TEXT NOT NULL,
                deadline_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT,
                checks_json TEXT NOT NULL DEFAULT '[]',
                changed_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE claims (
                task_id TEXT NOT NULL REFERENCES tasks(id),
                path TEXT NOT NULL,
                PRIMARY KEY (task_id, path)
            );
            INSERT INTO tasks (
                id, repo_id, repo_root, task, worktree, scratch, started_at,
                deadline_at, heartbeat_at, status
            ) VALUES (
                'legacy-task', 'legacy-repo', '/legacy', 'Legacy task', '/legacy',
                '/legacy/scratch', '2026-01-01T00:00:00Z',
                '2099-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'active'
            );
            INSERT INTO claims (task_id, path) VALUES ('legacy-task', 'src');
            """
        )
        database.commit()
        database.close()

        record = json.loads(self.run_tool("status", "legacy-task", "--json").stdout)
        migrated = sqlite3.connect(self.state / "tasks.sqlite3")
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(tasks)")}
        tables = {
            row[0]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migrated.close()
        backups = list(self.state.glob("tasks.pre-migration-*.sqlite3"))
        backup = sqlite3.connect(backups[0])
        backed_up_tasks = backup.execute("SELECT id FROM tasks").fetchall()
        backup.close()

        self.assertEqual(record["id"], "legacy-task")
        self.assertIsNone(record["owner"])
        self.assertIsNone(record["latest_note"])
        self.assertIn("owner", columns)
        self.assertIn("latest_note", columns)
        self.assertIn("task_events", tables)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backed_up_tasks, [("legacy-task",)])


if __name__ == "__main__":
    unittest.main()
