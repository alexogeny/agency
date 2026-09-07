import runpy
import unittest
from pathlib import Path


SCRIPT_IMPORTS = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map")
)["script_imports"]


class CountedText(str):
    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.scanned_characters = 0
        return instance

    def count(self, sub, start=0, end=None):
        if end is None:
            end = len(self)
        self.scanned_characters += max(0, end - start)
        return super().count(sub, start, end)


class RepoMapImportTests(unittest.TestCase):
    def test_import_line_numbers_preserve_multiline_matches(self):
        script = (
            "\nimport a from\n 'first'; const b = require(\n"
            " 'sec\nond'); from 'third'\r\nfrom 'fourth'\n"
        )
        cases = [
            (language, script, [("first", 2), ("sec\nond", 3), ("third", 5), ("fourth", 6)])
            for language in ("javascript", "typescript")
        ]
        cases.extend([
            ("rust", "\n\n  use alpha::beta;\r\nmod gamma;\n\n  use delta;\n",
             [("alpha::beta", 1), ("gamma", 4), ("delta", 5)]),
            ("go", '\n\n  import "alpha"\r\nimport alias `beta\ngamma`\n\nimport "delta"\n',
             [("alpha", 1), ("beta\ngamma", 4), ("delta", 6)]),
            ("python", script, []),
            ("javascript", "", []),
            ("rust", "fn main() {}\n", []),
        ])
        for language, source, expected in cases:
            with self.subTest(language=language, source=source):
                self.assertEqual(
                    SCRIPT_IMPORTS(source, language),
                    [{"module": module, "line": line} for module, line in expected],
                )

    def test_line_counting_scans_at_most_one_text_length(self):
        templates = {
            "javascript": "import value from 'module{index}';\n",
            "typescript": "const value = require('module{index}');\n",
            "rust": "use module{index};\n",
            "go": 'import "module{index}"\n',
        }
        for language, template in templates.items():
            with self.subTest(language=language):
                source = CountedText("".join(template.format(index=index) for index in range(512)))
                self.assertEqual(
                    SCRIPT_IMPORTS(source, language),
                    [{"module": f"module{index}", "line": index + 1} for index in range(512)],
                )
                self.assertLessEqual(source.scanned_characters, len(source))


if __name__ == "__main__":
    unittest.main()
