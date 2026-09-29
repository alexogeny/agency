import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReportFontInstallerTests(unittest.TestCase):
    def run_fixture(self, corrupt=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        archive = root / "fonts.tar.xz"
        with tarfile.open(archive, "w:xz") as bundle:
            for name in ["cmunrm.ttf", "cmunbx.ttf", "cmunti.ttf", "cmunbi.ttf", "OFL.txt", "OFL-FAQ.txt", "README"]:
                content = f"fixture {name}".encode()
                member = tarfile.TarInfo(f"cm-unicode-0.7.0/{name}")
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        source = (ROOT / "scripts/install-report-fonts.sh").read_text()
        source = source.replace("2609c14450f42d0bcd40203900afcb1d693521a9b24a18c65e14b6b0585ff150", digest)
        installer = root / "install-fonts.sh"
        installer.write_text(source)
        if corrupt:
            archive.write_bytes(b"corrupt download")
        binaries = root / "bin"
        binaries.mkdir()
        (binaries / "curl").write_text('#!/bin/sh\nwhile [ "$1" != "--output" ]; do shift; done\ncp "$FONT_FIXTURE" "$2"\n')
        (binaries / "fc-cache").write_text('#!/bin/sh\nexit 0\n')
        (binaries / "sha256sum").write_text('#!/bin/sh\nprintf "incompatible sha256sum check mode\\n" >&2\nexit 1\n')
        for binary in binaries.iterdir():
            binary.chmod(0o755)
        home = root / "home"
        home.mkdir()
        result = subprocess.run(
            ["/bin/bash", str(installer)],
            env={**os.environ, "HOME": str(home), "FONT_FIXTURE": str(archive), "PATH": str(binaries) + os.pathsep + os.environ["PATH"]},
            capture_output=True, text=True,
        )
        return result, home

    def test_uses_shasum_when_installed_sha256sum_is_incompatible(self):
        result, home = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((home / ".local/share/fonts/cm-unicode/cmunrm.ttf").read_text(), "fixture cmunrm.ttf")
        self.assertEqual(list((home / "Scratch").iterdir()), [])

    def test_checksum_mismatch_stops_before_installing_fonts(self):
        result, home = self.run_fixture(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((home / ".local/share/fonts").exists())
        self.assertEqual(list((home / "Scratch").iterdir()), [])
