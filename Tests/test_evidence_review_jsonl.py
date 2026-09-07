from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest


LOAD_RECORDS = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "evidence-review")
)["load_records"]


class EvidenceReviewJsonlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def test_unicode_separators_inside_strings_are_preserved(self):
        for suffix in ("jsonl", "ndjson"):
            for separator in ("\u2028", "\u2029", "\u0085"):
                with self.subTest(suffix=suffix, separator=separator):
                    records = [{"title": f"First{separator}second"}, {"title": "Next"}]
                    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
                    self.assertEqual(LOAD_RECORDS(self.write(f"input.{suffix}", text), None), records)

    def test_blank_lines_and_physical_newlines_are_preserved(self):
        for ending in ("\n", "\r\n", "\r"):
            with self.subTest(ending=ending):
                text = ending.join(["", "  ", '{"title":"First"}', "\t", '{"title":"Second"}', ""])
                self.assertEqual(
                    LOAD_RECORDS(self.write("input.JSONL", text), None),
                    [{"title": "First"}, {"title": "Second"}],
                )
        for text in ("", " \n\t\r\n"):
            self.assertEqual(LOAD_RECORDS(self.write("empty.jsonl", text), None), [])

    def test_non_object_error_reports_physical_line_number(self):
        title = json.dumps({"title": "First\u2028second"}, ensure_ascii=False)
        path = self.write("input.jsonl", f"\n{title}\n\n[]\n")
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            LOAD_RECORDS(path, None)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn(f"{path}:4 is not a JSON object", error.getvalue())

    def test_malformed_json_still_raises_decode_error(self):
        for malformed in ('{broken', '{"title":', '{"title":"unfinished"'):
            with self.subTest(malformed=malformed):
                path = self.write("input.jsonl", '{"title":"First"}\n' + malformed + '\n')
                with self.assertRaises(json.JSONDecodeError) as expected:
                    json.loads(malformed)
                with self.assertRaises(json.JSONDecodeError) as actual:
                    LOAD_RECORDS(path, None)
                self.assertEqual(str(actual.exception), str(expected.exception))

    def test_unicode_separators_are_not_record_delimiters(self):
        for separator in ("\u2028", "\u2029", "\u0085"):
            with self.subTest(separator=separator):
                path = self.write("input.jsonl", '{"id":1}' + separator + '{"id":2}')
                with self.assertRaises(json.JSONDecodeError):
                    LOAD_RECORDS(path, None)

    def test_json_and_csv_loading_are_unchanged(self):
        path = self.write("input.json", '{"data":{"records":[{"title":"JSON"},3]}}')
        self.assertEqual(LOAD_RECORDS(path, "data.records"), [{"title": "JSON"}])
        path = self.write("input.csv", '\ufefftitle,year\r\n"CSV title",2025\r\n')
        self.assertEqual(LOAD_RECORDS(path, None), [{"title": "CSV title", "year": "2025"}])


if __name__ == "__main__":
    unittest.main()
