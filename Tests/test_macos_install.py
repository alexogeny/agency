import importlib.machinery
import json
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class MacOSInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = {**os.environ, "HOME": str(self.home)}

    def tearDown(self):
        self.temporary.cleanup()

    def run_installer(self, *args):
        return subprocess.run(
            ["/bin/bash", str(ROOT / "install.sh"), *args],
            env=self.environment, text=True, capture_output=True,
        )

    def test_macos_preview_is_non_mutating_and_excludes_linux_operations(self):
        result = self.run_installer("--platform", "macos", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertIn("Homebrew", result.stdout)
        self.assertIn("Library/Application Support/Firefox", result.stdout)
        self.assertIn("podman machine init", result.stdout)
        self.assertIn("retain installed", result.stdout)
        self.assertNotIn("pacman -", result.stdout)
        self.assertNotIn("/etc/resolv.conf", result.stdout)
        self.assertIn(".local/bin/sandbox ->", result.stdout)
        self.assertIn("Seatbelt", result.stdout)
        self.assertNotIn("powerdevilrc", result.stdout)

    def test_macos_update_plan_is_explicit(self):
        result = self.run_installer("--platform", "macos", "--dry-run", "--update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("upgrade installed", result.stdout)
        self.assertIn("Run ./install.sh", result.stdout)
        self.assertIn(" --update to apply this plan on a Mac.", result.stdout)

    def test_invalid_platform_fails_before_mutation(self):
        for args in (("--platform",), ("--platform", "windows")):
            result = self.run_installer(*args)
            self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_mismatched_platform_refuses_real_installation(self):
        platform = "linux" if os.uname().sysname == "Darwin" else "macos"
        result = self.run_installer("--platform", platform)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("does not match", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_case_insensitive_scratch_is_preserved(self):
        scratch = self.home / "Scratch"
        scratch.mkdir()
        (scratch / "keep.txt").write_text("keep")
        legacy = self.home / "scratch"
        if not legacy.exists():
            legacy.symlink_to(scratch, target_is_directory=True)
        result = subprocess.run(
            ["/bin/bash", "-c", 'source "$1"; agency_prepare_scratch', "bash", str(ROOT / "scripts/lib.sh")],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((scratch / "keep.txt").read_text(), "keep")
        self.assertNotIn("conflicting", result.stderr)

    def test_firefox_profiles_with_spaces_receive_preferences(self):
        base = self.home / "Library/Application Support/Firefox"
        base.mkdir(parents=True)
        (base / "profiles.ini").write_text("[Profile0]\r\nIsRelative=1\r\nPath=Profiles/test profile\r\n")
        result = subprocess.run(
            ["/bin/bash", str(ROOT / "scripts/install-firefox.sh")],
            env={**self.environment, "AGENCY_PLATFORM": "macos"}, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((base / "Profiles/test profile/user.js").resolve(), ROOT / "firefox/user.js")

    def test_homebrew_installs_missing_formulae_and_retains_existing_casks(self):
        command = r'''set -euo pipefail
source "$1/scripts/install-macos.sh"
AGENCY_DIR=$1
brew() {
  case "$*" in
    "list --formula uv") return 1 ;;
    "list "*) return 0 ;;
    "--prefix rustup") printf '/brew/opt/rustup\n' ;;
    *) printf '%s\n' "$*" >> "$HOME/brew.log" ;;
  esac
}
agency_install_macos_packages false
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / "brew.log").read_text().splitlines(), ["install --formula uv"])

    def test_homebrew_update_upgrades_only_managed_installed_packages(self):
        command = r'''set -euo pipefail
source "$1/scripts/install-macos.sh"
AGENCY_DIR=$1
brew() {
  case "$*" in
    "list "*) return 0 ;;
    "--prefix rustup") printf '/brew/opt/rustup\n' ;;
    *) printf '%s\n' "$*" >> "$HOME/brew.log" ;;
  esac
}
agency_install_macos_packages true
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = (self.home / "brew.log").read_text().splitlines()
        self.assertEqual(len(commands), 5)
        self.assertTrue(commands[0].startswith("upgrade --formula bash python uv bun git gh"))
        self.assertEqual(commands[1:], ["upgrade --cask firefox", "upgrade --cask 1password", "upgrade --cask 1password-cli", "upgrade --cask font-fantasque-sans-mono-nerd-font"])

    def test_homebrew_prefix_failure_stops_before_cask_installation(self):
        command = r'''set -euo pipefail
source "$1/scripts/install-macos.sh"
AGENCY_DIR=$1
brew() {
  case "$*" in
    "list --formula "*) return 0 ;;
    "--prefix rustup") return 7 ;;
    *) printf '%s\n' "$*" >> "$HOME/unexpected-cask-calls" ;;
  esac
}
agency_install_macos_packages false
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertFalse((self.home / "unexpected-cask-calls").exists())

    def test_sandbox_runtime_installs_missing_and_only_updates_explicitly(self):
        for mode in ("missing", "existing", "update"):
            with self.subTest(mode=mode):
                command = r'''set -euo pipefail
source "$1/scripts/install-macos.sh"
mode=$2
command() {
  if [[ $* == '-v srt' ]]; then [[ $mode != missing ]]; else builtin command "$@"; fi
}
bun() { printf '%s\n' "$*"; }
update=false
[[ $mode != update ]] || update=true
agency_install_macos_sandbox_runtime "$update"
'''
                result = subprocess.run(
                    ["/bin/bash", "-c", command, "bash", str(ROOT), mode],
                    env=self.environment, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if mode == "existing":
                    self.assertNotIn("add --global", result.stdout)
                else:
                    self.assertIn("add --global --ignore-scripts @anthropic-ai/sandbox-runtime@0.0.77", result.stdout)

    def test_missing_terminal_font_is_installed_without_upgrading_apps(self):
        command = r'''set -euo pipefail
source "$1/scripts/install-macos.sh"
AGENCY_DIR=$1
brew() {
  case "$*" in
    "list --cask font-fantasque-sans-mono-nerd-font") return 1 ;;
    "list "*) return 0 ;;
    "--prefix rustup") printf '/brew/opt/rustup\n' ;;
    *) printf '%s\n' "$*" >> "$HOME/brew.log" ;;
  esac
}
agency_install_macos_packages false
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / "brew.log").exists(), "Missing terminal font was not installed")
        self.assertEqual((self.home / "brew.log").read_text(), "install --cask font-fantasque-sans-mono-nerd-font\n")

    def test_shell_path_installation_preserves_profile_and_is_idempotent(self):
        profile = self.home / ".zprofile"
        profile.write_text("export KEEP_ME=yes\n")
        command = r'''set -euo pipefail
AGENCY_DIR=$1
source "$1/scripts/lib.sh"
source "$1/scripts/install-macos.sh"
brew_prefix=/brew
brew() { printf '/brew/opt/rustup\n'; }
agency_as_root() { :; }
agency_link() { :; }
agency_configure_macos_terminal() { :; }
agency_configure_macos
agency_configure_macos
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(profile.read_text().startswith("export KEEP_ME=yes\n"))
        self.assertEqual(profile.read_text().count(" || . "), 1)
        self.assertIn("/brew/opt/rustup/bin", (self.home / ".config/agency/env.sh").read_text())
        self.assertTrue(list((self.home / ".local/state/agency/backups").rglob(".zprofile")))

    def test_firefox_policy_uses_shared_atomic_installer_and_propagates_failure(self):
        for install_status in (0, 71):
            with self.subTest(install_status=install_status):
                (self.home / "installed-policy").unlink(missing_ok=True)
                command = r'''set -euo pipefail
AGENCY_DIR=$1
install_status=$2
source "$1/scripts/lib.sh"
source "$1/scripts/install-macos.sh"
brew_prefix=/brew
brew() { printf '/brew/opt/rustup\n'; }
agency_link() { :; }
agency_backup_copy() { :; }
agency_configure_macos_terminal() { :; }
agency_as_root() { return 99; }
agency_install_policy() {
  [[ $1 == "$AGENCY_DIR/firefox/policies.json" ]] || return 72
  [[ $2 == /Applications/Firefox.app/Contents/Resources/distribution/policies.json ]] || return 73
  cp "$1" "$HOME/installed-policy"
  return "$install_status"
}
agency_configure_macos
'''
                result = subprocess.run(
                    ["/bin/bash", "-c", command, "bash", str(ROOT), str(install_status)],
                    env=self.environment, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, install_status, result.stderr)
                self.assertTrue((self.home / "installed-policy").is_file())
                self.assertEqual((self.home / "installed-policy").read_bytes(), (ROOT / "firefox/policies.json").read_bytes())

    def test_terminal_uses_fish_and_preserves_preferences_on_repeat(self):
        preferences = self.home / "Library/Preferences/com.apple.Terminal.plist"
        preferences.parent.mkdir(parents=True)
        preferences.write_text("existing preferences")
        command = r'''set -euo pipefail
source "$1/scripts/lib.sh"
source "$1/scripts/install-macos.sh"
brew_prefix="$HOME/brew"
mkdir -p "$brew_prefix/bin"
touch "$brew_prefix/bin/fish"
chmod +x "$brew_prefix/bin/fish"
defaults() {
  case "$1" in
    read) [[ -f $HOME/terminal-shell ]] && cat "$HOME/terminal-shell" ;;
    write)
      [[ $2 == com.apple.Terminal && $3 == Shell && $4 == -string ]]
      printf '%s\n' "$5" > "$HOME/terminal-shell"
      printf 'write\n' >> "$HOME/defaults.log"
      ;;
    *) return 9 ;;
  esac
}
agency_configure_macos_terminal
agency_configure_macos_terminal
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / "terminal-shell").read_text().strip(), str(self.home / "brew/bin/fish"))
        self.assertEqual((self.home / "defaults.log").read_text(), "write\n")
        backups = list((self.home / ".local/state/agency/backups").rglob("com.apple.Terminal.plist"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "existing preferences")

    def test_terminal_missing_fish_does_not_change_preferences(self):
        command = r'''set -euo pipefail
source "$1/scripts/install-macos.sh"
brew_prefix="$HOME/missing"
defaults() { touch "$HOME/unexpected-defaults-call"; }
agency_configure_macos_terminal
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fish is missing", result.stderr)
        self.assertFalse((self.home / "unexpected-defaults-call").exists())

    def test_firefox_link_uses_launcher_outside_app_bundle(self):
        command = r'''set -euo pipefail
AGENCY_DIR=$1
source "$1/scripts/lib.sh"
source "$1/scripts/install-macos.sh"
brew_prefix=/brew
brew() { printf '/brew/opt/rustup\n'; }
agency_as_root() { :; }
agency_configure_macos_terminal() { :; }
agency_configure_macos
'''
        result = subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT)],
            env=self.environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        launcher = self.home / ".local/bin/firefox"
        self.assertEqual(launcher.resolve(), ROOT / "scripts/firefox-macos.sh")

    def test_firefox_launcher_preserves_arguments_and_exit_status(self):
        binary = self.home / "Firefox App/firefox"
        binary.parent.mkdir()
        binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 7\n')
        binary.chmod(0o755)
        launcher = self.home / "launcher"
        launcher.write_text((ROOT / "scripts/firefox-macos.sh").read_text().replace(
            "/Applications/Firefox.app/Contents/MacOS/firefox", str(binary),
        ))
        result = subprocess.run(
            ["/bin/sh", str(launcher), "--profile", "profile with spaces", "about:blank"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["--profile", "profile with spaces", "about:blank"])


class HomebrewBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = {**os.environ, "HOME": str(self.home), "TMPDIR": str(self.home)}

    def tearDown(self):
        self.temporary.cleanup()

    def bootstrap(self, mode="success", existing=False):
        command = r'''set -euo pipefail
source "$1/scripts/platform.sh"
mode=$2
existing=$3
agency_find_brew() {
  if [[ $existing == true || -f $HOME/installed ]]; then
    printf '%s/bin/brew\n' "$HOME"
  else
    return 1
  fi
}
curl() {
  printf 'download\n' >> "$HOME/events"
  local output
  while (( $# )); do
    if [[ $1 == --output ]]; then output=$2; break; fi
    shift
  done
  if [[ $mode == installer-failure ]]; then
    printf 'exit 7\n' > "$output"
  elif [[ $mode == no-brew ]]; then
    printf ':\n' > "$output"
  else
    printf 'printf "install\\n" >> "$HOME/events"; touch "$HOME/installed"\n' > "$output"
  fi
  [[ $mode != download-failure ]]
}
shasum() {
  cat >/dev/null
  printf 'verify\n' >> "$HOME/events"
  [[ $mode != checksum-failure ]]
}
agency_ensure_homebrew
printf 'brew=%s\n' "$AGENCY_BREW"
'''
        return subprocess.run(
            ["/bin/bash", "-c", command, "bash", str(ROOT), mode, "true" if existing else "false"],
            env=self.environment, text=True, capture_output=True,
        )

    def test_existing_homebrew_on_path_is_discovered(self):
        fake_bin = self.home / "bin"
        fake_bin.mkdir()
        brew = fake_bin / "brew"
        brew.write_text("#!/bin/sh\nexit 0\n")
        brew.chmod(0o755)
        result = subprocess.run(
            ["/bin/bash", "-c", 'source "$1/scripts/platform.sh"; agency_find_brew', "bash", str(ROOT)],
            env={**self.environment, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]},
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(brew))

    def test_existing_homebrew_does_not_download_or_execute_installer(self):
        result = self.bootstrap(existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / "events").exists())
        self.assertIn(f"brew={self.home}/bin/brew", result.stdout)

    def test_missing_homebrew_is_downloaded_verified_installed_then_rediscovered(self):
        result = self.bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / "events").read_text().splitlines(), ["download", "verify", "install"])
        self.assertIn(f"brew={self.home}/bin/brew", result.stdout)
        self.assertEqual(list(self.home.glob("agency-homebrew.*")), [])

    def test_partial_download_is_never_executed(self):
        result = self.bootstrap("download-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / "events").read_text().splitlines(), ["download"])
        self.assertFalse((self.home / "installed").exists())
        self.assertEqual(list(self.home.glob("agency-homebrew.*")), [])

    def test_checksum_failure_is_never_executed(self):
        result = self.bootstrap("checksum-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / "events").read_text().splitlines(), ["download", "verify"])
        self.assertFalse((self.home / "installed").exists())
        self.assertEqual(list(self.home.glob("agency-homebrew.*")), [])

    def test_failed_installer_stops_setup(self):
        result = self.bootstrap("installer-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Homebrew installation failed", result.stderr)
        self.assertNotIn("brew=", result.stdout)
        self.assertEqual(list(self.home.glob("agency-homebrew.*")), [])

    def test_success_without_a_brew_binary_stops_setup(self):
        result = self.bootstrap("no-brew")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not find brew", result.stderr)
        self.assertNotIn("brew=", result.stdout)

    def test_dry_run_reports_resolved_homebrew_state(self):
        command = r'''set -euo pipefail
AGENCY_DIR=$1
AGENCY_PLATFORM=macos
expected_brew=$2
export PYTHONDONTWRITEBYTECODE=1
source "$1/scripts/lib.sh"
source "$1/scripts/platform.sh"
source "$1/scripts/install-dry-run.sh"
agency_find_brew() {
  [[ -n $expected_brew ]] || return 1
  printf '%s\n' "$expected_brew"
}
agency_print_install_plan false
'''
        for brew, expected in (("/opt/homebrew/bin/brew", "Homebrew found: /opt/homebrew/bin/brew"), ("", "Homebrew missing: install verified official installer")):
            with self.subTest(brew=brew):
                result = subprocess.run(
                    ["/bin/bash", "-c", command, "bash", str(ROOT), brew],
                    env=self.environment, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_dry_run_never_downloads_or_bootstraps(self):
        fake_bin = self.home / "bin"
        fake_bin.mkdir()
        curl = fake_bin / "curl"
        curl.write_text('#!/bin/sh\nprintf called > "$HOME/unexpected-download"\nexit 99\n')
        curl.chmod(0o755)
        result = subprocess.run(
            ["/bin/bash", str(ROOT / "install.sh"), "--platform", "macos", "--dry-run"],
            env={**self.environment, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]},
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"Homebrew (?:found:|missing: install verified official installer)")
        self.assertIn("Command Line Tools", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [fake_bin])


class FirefoxConfigurationRootTests(unittest.TestCase):
    def test_platform_defaults_and_explicit_override(self):
        source = (ROOT / "Tools/web-research").read_text()
        function = source[source.index("function firefoxConfigurationRoot()"):source.index("function parseIniSections(")]
        for platform, override, expected in (
            ("darwin", "", "/test/home/Library/Application Support/Firefox"),
            ("linux", "", "/test/home/.mozilla/firefox"),
            ("darwin", "/custom/profiles", "/custom/profiles"),
        ):
            script = (
                "import { join } from 'node:path';\n"
                "const homedir = () => '/test/home';\n"
                "const process = " + json.dumps({"platform": platform, "env": {"WEB_RESEARCH_FIREFOX_ROOT": override}}) + ";\n"
                + function + "\nconsole.log(firefoxConfigurationRoot());\n"
            )
            with self.subTest(platform=platform, override=override):
                with tempfile.TemporaryDirectory() as temporary:
                    harness = Path(temporary) / "firefox-root.ts"
                    harness.write_text(script)
                    result = subprocess.run(["bun", str(harness)], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)


class MacOSSystemContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("macos_system_context", str(ROOT / "Tools/system-context"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.module = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.module)

    def test_laptop_on_battery_uses_native_power_and_memory_data(self):
        with patch.object(self.module, "macos_output", side_effect=["Mac15,7", "Now drawing from 'Battery Power'\n -InternalBattery-0 73%; discharging;", "34359738368"]):
            result = self.module.macos_context()
        self.assertEqual(result["device_class"], "laptop")
        self.assertEqual(result["power_source"], "battery")
        self.assertEqual(result["battery_percent"], 73)
        self.assertEqual(result["memory_gib"], 32.0)

    def test_desktop_and_failed_commands_do_not_fabricate_battery_data(self):
        with patch.object(self.module, "macos_output", side_effect=["Macmini9,1", "Now drawing from 'AC Power'", ""]):
            result = self.module.macos_context()
        self.assertEqual(result["device_class"], "desktop")
        self.assertEqual(result["power_source"], "ac")
        self.assertIsNone(result["battery_percent"])
        self.assertIsNone(result["memory_gib"])


if __name__ == "__main__":
    unittest.main()
