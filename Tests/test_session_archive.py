import base64
from collections import Counter
import json
from pathlib import Path
import tempfile
import time
import unittest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Tools"))
import session_archive as archive


class SanitizerTests(unittest.TestCase):
    def test_plain_text_and_structure_are_preserved(self):
        value = {
            "role": "user",
            "text": "Keep café, code `x = 2`, and\nnewlines.",
            "list": [1, None, True],
        }
        counts = Counter()
        self.assertEqual(archive.clean(value, counts), value)
        self.assertEqual(counts["payloads"], 0)

    def test_inline_and_nested_image_payloads_are_removed(self):
        uri = "data:image/png;base64," + base64.b64encode(b"image bytes" * 50).decode()
        value = {
            "text": "before " + uri + " after",
            "content": [{"type": "input_image", "image_url": uri}],
        }
        counts = Counter()
        result = archive.clean(value, counts)
        self.assertEqual(counts["payloads"], 2)
        self.assertNotIn("data:image", json.dumps(result))
        self.assertTrue(result["text"].startswith("before "))
        self.assertTrue(result["text"].endswith(" after"))
        self.assertEqual(result["content"][0]["type"], "input_image")

    def test_raw_and_stringified_image_objects_are_cleaned(self):
        raw = {
            "type": "image",
            "mimeType": "image/png",
            "data": "A" * 1000,
            "caption": "Keep this caption",
        }
        counts = Counter()
        result = archive.clean({"raw": raw, "encoded_output": json.dumps(raw)}, counts)
        self.assertEqual(counts["payloads"], 2)
        self.assertNotIn("A" * 1000, json.dumps(result))
        self.assertEqual(result["raw"]["caption"], "Keep this caption")


class ArchiveTests(unittest.TestCase):
    def test_directory_export_preserves_order_text_and_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            source.mkdir()
            path = source / "one.jsonl"
            rows = [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "café ``` preserved"}
                        ],
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {"result": "iVBORw0KGgo" + "A" * 1000},
                },
                {"type": "compacted", "payload": {"text": "checkpoint retained"}},
            ]
            original = "".join(json.dumps(x) + "\n" for x in rows)
            path.write_text(original)
            destination = root / "archive"
            archive.export_directory(source, destination)
            result = archive.verify_directory(source, destination)
            self.assertEqual(result["records"], 3)
            self.assertEqual(path.read_text(), original)
            saved = (destination / "jsonl/one.jsonl").read_text()
            self.assertNotIn("A" * 1000, saved)
            self.assertIn("checkpoint retained", saved)
            self.assertIn(
                "café ``` preserved", (destination / "markdown/one.md").read_text()
            )
            (destination / "jsonl/one.jsonl").write_text(
                saved.replace("checkpoint retained", "lost")
            )
            with self.assertRaises(RuntimeError):
                archive.verify_directory(source, destination)

    def test_cutoff_excludes_recent_files_and_rejects_empty_selection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            source.mkdir()
            (source / "new.jsonl").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "No sessions"):
                archive.export_directory(source, root / "out", before=time.time() - 100)
            self.assertFalse((root / "out").exists())

    def test_destination_inside_source_and_existing_destination_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            source.mkdir()
            (source / "one.jsonl").write_text("{}\n")
            with self.assertRaises(ValueError):
                archive.export_directory(source, source / "nested")
            with self.assertRaises(FileExistsError):
                archive.export_directory(source, Path(d))

    def test_source_mutation_blocks_verification(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            source.mkdir()
            path = source / "one.jsonl"
            path.write_text("{}\n")
            archive.export_directory(source, Path(d) / "out")
            path.write_text('{"changed":true}\n')
            with self.assertRaises(RuntimeError):
                archive.verify_directory(source, Path(d) / "out")

    def test_traversal_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            source.mkdir()
            path = source / "one.jsonl"
            path.write_text("{}\n")
            destination = Path(d) / "out"
            archive.export_directory(source, destination)
            manifest_path = destination / "backup_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"][0]["relative_path"] = "../outside.jsonl"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                archive.verify_directory(source, destination)


if __name__ == "__main__":
    unittest.main()
