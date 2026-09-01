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
        self.dev_root = self.workspace / "dev"
        self.bin_root = self.workspace / "bin"
        self.cache_root = self.workspace / "cache"
        self.procfs.mkdir()
        self.dev_root.mkdir()
        self.bin_root.mkdir()
        (self.procfs / "meminfo").write_text("MemTotal:       16777216 kB\n")

    def tearDown(self):
        self.temporary.cleanup()

    def run_context(self, *arguments):
        environment = {
            **os.environ,
            "AGENCY_SYSFS_ROOT": str(self.sysfs),
            "AGENCY_PROCFS_ROOT": str(self.procfs),
            "AGENCY_DEV_ROOT": str(self.dev_root),
            "AGENCY_CACHE_ROOT": str(self.cache_root),
            "AGENCY_LOGICAL_CPUS": "8",
            "PATH": f"{self.bin_root}:{os.environ.get('PATH', '')}",
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

    def add_command(self, name, body):
        command = self.bin_root / name
        command.write_text(f"#!/bin/sh\n{body}\n")
        command.chmod(0o755)

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

    def test_desktop_without_power_supply_telemetry_is_treated_as_ac(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("3\n")

        payload = json.loads(self.run_context("--json").stdout)

        self.assertEqual(payload["device_class"], "desktop")
        self.assertEqual(payload["power_source"], "ac")

    def test_nvidia_runtime_reports_model_vram_and_cuda_cores(self):
        (self.dev_root / "nvidia0").touch()
        self.add_command(
            "nvidia-smi",
            "printf '%s\\n' 'NVIDIA GeForce RTX 4090, 24564'",
        )
        self.add_command("nvidia-settings", "printf '%s\\n' '16384'")

        payload = json.loads(self.run_context("--json").stdout)

        self.assertEqual(
            payload["compute_accelerator"],
            "NVIDIA GeForce RTX 4090 (24 GiB VRAM, 16,384 CUDA cores)",
        )

    def test_nvidia_cache_refreshes_after_device_change_or_explicit_request(self):
        device = self.dev_root / "nvidia0"
        device.touch()
        calls = self.workspace / "nvidia-smi-calls"
        self.add_command(
            "nvidia-smi",
            f"printf '%s\\n' called >> '{calls}'\n"
            "printf '%s\\n' 'NVIDIA GeForce RTX 4090, 24564'",
        )
        self.add_command("nvidia-settings", "exit 1")

        self.run_context("--json")
        self.run_context("--json")
        self.assertEqual(calls.read_text().splitlines(), ["called"])

        device_stat = device.stat()
        os.utime(
            device,
            ns=(device_stat.st_atime_ns, device_stat.st_mtime_ns + 1_000_000_000),
        )
        self.run_context("--json")
        self.assertEqual(calls.read_text().splitlines(), ["called", "called"])

        self.run_context("--json", "--refresh")
        self.assertEqual(
            calls.read_text().splitlines(),
            ["called", "called", "called"],
        )

    def test_nvidia_runtime_query_failure_keeps_device_fallback(self):
        (self.dev_root / "nvidia0").touch()
        self.add_command("nvidia-smi", "exit 1")

        payload = json.loads(self.run_context("--json").stdout)

        self.assertEqual(
            payload["compute_accelerator"],
            "nvidia-device (runtime unverified)",
        )


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
