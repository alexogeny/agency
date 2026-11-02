import io
from decimal import Decimal
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Tools"))
from archive_verify import inventory, validate_archive


class ArchiveValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = self.base / "web-research"
        self.source.mkdir()
        (self.source / "page.txt").write_bytes(b"original text")
        (self.source / "page.txt").chmod(0o644)
        (self.source / "empty-directory").mkdir()
        (self.source / "link").symlink_to("page.txt")

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, omit=(), extra=False):
        buffer = io.BytesIO()
        with tarfile.open(
            fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT
        ) as archive:

            def select(member):
                info = (self.source.parent / member.name).lstat()
                member.pax_headers["mtime"] = str(Decimal(info.st_mtime_ns) / 10**9)
                return None if member.name in omit else member

            archive.add(self.source, arcname=self.source.name, filter=select)
            if extra:
                member = tarfile.TarInfo("web-research/unexpected.txt")
                archive.addfile(member, io.BytesIO())
        buffer.seek(0)
        return buffer

    def validate(self, buffer):
        with tarfile.open(fileobj=buffer, mode="r|") as archive:
            return validate_archive(
                archive, self.source, inventory(self.source), io.StringIO()
            )

    def test_complete_archive_with_empty_directory_symlink_and_hardlink(self):
        os.link(self.source / "page.txt", self.source / "hardlink.txt")
        result = self.validate(self.archive())
        self.assertEqual(result["regular_files"], 2)
        self.assertEqual(result["symlinks"], 1)
        self.assertEqual(result["directories"], 2)
        self.assertEqual(result["missing_paths"], 0)

    def test_missing_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            self.validate(self.archive(omit=("web-research/page.txt",)))

    def test_extra_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.validate(self.archive(extra=True))

    def test_same_size_content_change_is_rejected(self):
        buffer = self.archive()
        (self.source / "page.txt").write_bytes(b"changed! text")
        with self.assertRaisesRegex(ValueError, "content"):
            self.validate(buffer)

    def test_symlink_target_change_is_rejected(self):
        buffer = self.archive()
        (self.source / "link").unlink()
        (self.source / "link").symlink_to("elsewhere")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.validate(buffer)

    def test_permissions_change_is_rejected(self):
        buffer = self.archive()
        (self.source / "page.txt").chmod(0o600)
        with self.assertRaisesRegex(ValueError, "metadata"):
            self.validate(buffer)

    def test_empty_archive_is_rejected(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w"):
            pass
        buffer.seek(0)
        with self.assertRaisesRegex(ValueError, "missing"):
            self.validate(buffer)


class ArchiveBoundaryTests(unittest.TestCase):
    def test_unsafe_and_duplicate_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            source.mkdir()
            (source / "file").write_text("retained")
            for names in [["../escape"], ["source/file", "source/file"]]:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode="w") as archive:
                    for name in names:
                        entry = tarfile.TarInfo(name)
                        archive.addfile(entry, io.BytesIO())
                buffer.seek(0)
                with tarfile.open(fileobj=buffer, mode="r|") as archive:
                    with self.assertRaises(ValueError):
                        validate_archive(
                            archive, source, inventory(source), io.StringIO()
                        )
                self.assertEqual((source / "file").read_text(), "retained")

    def test_failed_verification_does_not_publish_a_manifest(self):
        from archive_verify import verify

        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            source.mkdir()
            (source / "file").write_text("retained")
            archive = Path(d) / "empty.tar"
            with tarfile.open(archive, "w"):
                pass
            report = Path(d) / "manifest.jsonl"
            with self.assertRaises(ValueError):
                verify(source, archive, report)
            self.assertFalse(report.exists())

    def test_inventory_propagates_directory_read_failures(self):
        from unittest import mock

        def denied(root, **kwargs):
            if kwargs.get("onerror"):
                kwargs["onerror"](PermissionError("unreadable directory"))
            return iter(())

        with tempfile.TemporaryDirectory() as d:
            with mock.patch("archive_verify.os.walk", side_effect=denied):
                with self.assertRaises(PermissionError):
                    inventory(Path(d))


if __name__ == "__main__":
    unittest.main()
