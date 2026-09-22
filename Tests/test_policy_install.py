import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AtomicPolicyInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source policy.json"
        self.source.write_text('new policy\n')
        self.target = self.root / "application" / "policies.json"
        self.target.parent.mkdir()
        self.target.write_text('old policy\n')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, body in {
            "install": 'if [ "$1" = -m644 ] && [ "$POLICY_FAILURE" = copy ]; then printf partial > "$3"; exit 71; fi\nexec /usr/bin/install "$@"',
            "mv": 'if [ "$POLICY_FAILURE" = rename ]; then exit 72; fi\nexec /bin/mv "$@"',
        }.items():
            executable = self.bin / name
            executable.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
            executable.chmod(0o755)

    def run_install(self, failure="none"):
        script = r'''set -euo pipefail
source "$1/scripts/lib.sh"
agency_as_root() {
  printf 'called\n' >> "$HOME/root-calls"
  printf '%s\n' "${@: -2:1}" > "$HOME/staged-source"
  [[ ${@: -2:1} != "$POLICY_ORIGINAL" ]] || return 90
  cmp "$POLICY_ORIGINAL" "${@: -2:1}" || return 91
  "$@"
}
agency_install_policy "$2" "$3"
'''
        return subprocess.run(
            ["/bin/bash", "-c", script, "bash", ROOT, self.source, self.target],
            env={**os.environ, "HOME": str(self.root), "POLICY_FAILURE": failure,
                 "POLICY_ORIGINAL": str(self.source),
                 "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                 "AGENCY_BACKUP_ROOT": str(self.root / "backups")},
            text=True, capture_output=True,
        )

    def assert_stages_cleaned(self):
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["policies.json"])
        stage = Path((self.root / "staged-source").read_text().strip())
        self.assertFalse(stage.exists())
        self.assertFalse(stage.parent.exists())

    def test_copy_failure_preserves_previous_policy(self):
        result = self.run_install("copy")
        self.assertEqual(result.returncode, 71, result.stderr)
        self.assertEqual(self.target.read_text(), 'old policy\n')
        self.assert_stages_cleaned()

    def test_rename_failure_preserves_previous_policy(self):
        result = self.run_install("rename")
        self.assertEqual(result.returncode, 72, result.stderr)
        self.assertEqual(self.target.read_text(), 'old policy\n')
        self.assert_stages_cleaned()

    def test_replaces_policy_and_keeps_original_backup(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.root / "backups/home/application/policies.json").read_text(), 'old policy\n')
        self.assertEqual((self.root / "root-calls").read_text(), 'called\n')
        self.assert_stages_cleaned()

    def test_identical_policy_needs_no_root_or_backup(self):
        self.target.write_bytes(self.source.read_bytes())
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "root-calls").exists())
        self.assertFalse((self.root / "backups").exists())

    def test_new_parent_and_policy_are_created(self):
        self.target = self.root / "new directory" / "policies.json"
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assert_stages_cleaned()


if __name__ == "__main__":
    unittest.main()
