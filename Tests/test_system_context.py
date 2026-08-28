import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "Tools/system-context"
MERGER = ROOT / "scripts/merge-agent-hooks.py"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class SystemContextTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.sysfs = self.workspace / "sys"
        self.procfs = self.workspace / "proc"
        self.procfs.mkdir()
        (self.procfs / "meminfo").write_text("MemTotal:       16777216 kB\n")

    def tearDown(self):
        self.temporary.cleanup()

    def run_context(self, *arguments):
        environment = {
            **os.environ,
            "AGENCY_SYSFS_ROOT": str(self.sysfs),
            "AGENCY_PROCFS_ROOT": str(self.procfs),
            "AGENCY_LOGICAL_CPUS": "8",
        }
        return subprocess.run(
            [TOOL, *arguments],
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )

    def add_supply(self, name, supply_type, **values):
        supply = self.sysfs / "class/power_supply" / name
        supply.mkdir(parents=True)
        (supply / "type").write_text(f"{supply_type}\n")
        for key, value in values.items():
            (supply / key).write_text(f"{value}\n")

    def test_laptop_on_battery_gets_strict_high_load_guidance(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("10\n")
        self.add_supply("BAT0", "Battery", status="Discharging", capacity="61")
        self.add_supply(
            "hid-battery",
            "Battery",
            scope="Device",
            present="0",
            status="Unknown",
            capacity="0",
        )
        self.add_supply("AC", "Mains", online="0")

        payload = json.loads(self.run_context("--json").stdout)
        plain = self.run_context().stdout

        self.assertEqual(payload["device_class"], "laptop")
        self.assertEqual(payload["power_source"], "battery")
        self.assertEqual(payload["battery_percent"], 61)
        self.assertEqual(payload["logical_cpus"], 8)
        self.assertEqual(payload["memory_gib"], 16)
        self.assertIn("explicit approval", payload["resource_policy"])
        self.assertIn("laptop on battery (61%)", plain)
        self.assertIn("ML training", plain)

    def test_absent_device_battery_does_not_make_a_desktop_a_laptop(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("3\n")
        self.add_supply(
            "hid-battery",
            "Battery",
            scope="Device",
            present="0",
            status="Unknown",
            capacity="0",
        )

        payload = json.loads(self.run_context("--json").stdout)

        self.assertEqual(payload["device_class"], "desktop")
        self.assertIsNone(payload["battery_percent"])

    def test_laptop_on_ac_still_warns_about_sustained_local_work(self):
        self.add_supply("BAT0", "Battery", status="Charging", capacity="84")
        self.add_supply("ACAD", "Mains", online="1")

        payload = json.loads(self.run_context("--json").stdout)

        self.assertEqual(payload["device_class"], "laptop")
        self.assertEqual(payload["power_source"], "ac")
        self.assertIn("Do not assume server-class resources", payload["resource_policy"])

    def test_desktop_context_does_not_claim_laptop_constraints(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("3\n")
        self.add_supply("AC", "Mains", online="1")

        payload = json.loads(self.run_context("--json").stdout)

        self.assertEqual(payload["device_class"], "desktop")
        self.assertEqual(payload["power_source"], "ac")
        self.assertNotIn("thermally constrained laptop", payload["resource_policy"])


class HookMergeTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.target = self.workspace / "settings.json"
        self.fragment = self.workspace / "fragment.json"

    def tearDown(self):
        self.temporary.cleanup()

    def run_merger(self, *arguments):
        return subprocess.run(
            [MERGER, *arguments, self.target, self.fragment],
            text=True,
            capture_output=True,
        )

    def test_merger_preserves_settings_and_is_idempotent(self):
        self.target.write_text(
            json.dumps({"theme": "dark", "hooks": {"Stop": [{"hooks": []}]}})
        )
        session_hook = {
            "matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "command": "$HOME/.local/bin/system-context"}],
        }
        self.fragment.write_text(json.dumps({"hooks": {"SessionStart": [session_hook]}}))

        self.assertEqual(self.run_merger("--check").returncode, 0)
        self.assertEqual(self.run_merger().returncode, 0)
        self.assertEqual(self.run_merger("--check").returncode, 1)
        self.assertEqual(self.run_merger().returncode, 0)

        merged = json.loads(self.target.read_text())
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["hooks"]["Stop"], [{"hooks": []}])
        self.assertEqual(merged["hooks"]["SessionStart"], [session_hook])

    def test_merger_replaces_an_older_managed_hook_without_touching_others(self):
        command = "$HOME/.local/bin/system-context"
        unrelated = {"type": "command", "command": "keep-me"}
        self.target.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "matcher": "startup",
                                "hooks": [
                                    {"type": "command", "command": command},
                                    unrelated,
                                ],
                            }
                        ]
                    }
                }
            )
        )
        replacement = {
            "matcher": "startup|resume",
            "hooks": [{"type": "command", "command": command, "timeout": 5}],
        }
        self.fragment.write_text(
            json.dumps({"hooks": {"SessionStart": [replacement]}})
        )

        self.assertEqual(self.run_merger().returncode, 0)

        groups = json.loads(self.target.read_text())["hooks"]["SessionStart"]
        self.assertEqual(groups[-1], replacement)
        self.assertIn(unrelated, groups[0]["hooks"])
        self.assertEqual(
            sum(
                handler.get("command") == command
                for group in groups
                for handler in group["hooks"]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
