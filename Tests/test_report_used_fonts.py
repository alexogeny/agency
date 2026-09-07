from pathlib import Path
import runpy
import unittest


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "report-build"))


class Font:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls
        self.used = {1: "historical glyph"}

    def encode(self, text):
        return text.encode().hex()

    def pdf_objects(self, document):
        self.calls.append(self.name)
        return document.add(b"<< /Type /Font >>")


class ReportUsedFontsTests(unittest.TestCase):
    def renderer(self, commands, numbered=False):
        renderer = MODULE["NativePdfRenderer"].__new__(MODULE["NativePdfRenderer"])
        calls = []
        renderer.fonts = {
            style: Font(style, calls)
            for style in ("regular", "bold", "italic", "bolditalic")
        }
        renderer.images = {}
        renderer.destinations = {}
        renderer.pages = [{
            "commands": [(style, 12, 10, 10, text, (0, 0, 0)) for style, text in commands],
            "numbered": numbered, "images": [], "lines": [], "links": [],
        }]
        renderer.page_number_command = lambda number: (
            "regular", 10, 10, 10, str(number), (0, 0, 0)
        )
        return renderer, calls

    def test_only_current_styles_are_embedded_in_font_order(self):
        renderer, calls = self.renderer([("italic", "a"), ("bold", "b")])
        data = renderer.pdf()
        self.assertEqual(calls, ["bold", "italic"])
        self.assertNotIn(b"/F1 ", data)
        self.assertNotIn(b"/F4 ", data)
        self.assertIn(b"/F2 ", data)
        self.assertIn(b"/F3 ", data)

    def test_page_number_requires_regular_font(self):
        renderer, calls = self.renderer([], numbered=True)
        renderer.pdf()
        self.assertEqual(calls, ["regular"])

    def test_empty_unnumbered_page_requires_no_fonts(self):
        renderer, calls = self.renderer([])
        renderer.pdf()
        self.assertEqual(calls, [])

    def test_empty_text_command_still_requires_its_font(self):
        renderer, calls = self.renderer([("italic", "")])
        renderer.pdf()
        self.assertEqual(calls, ["italic"])

    def test_shared_font_object_preserves_each_style_resource(self):
        renderer, calls = self.renderer([("bold", "x"), ("regular", "y")])
        renderer.fonts["bold"] = renderer.fonts["regular"]
        data = renderer.pdf()
        self.assertEqual(calls, ["regular", "regular"])
        self.assertIn(b"/F1 ", data)
        self.assertIn(b"/F2 ", data)

    def test_repeated_call_uses_current_commands_despite_glyph_history(self):
        renderer, calls = self.renderer([("bold", "x")])
        first = renderer.pdf()
        self.assertEqual(renderer.pdf(), first)
        calls.clear()
        renderer.pages[0]["commands"] = [("italic", 12, 10, 10, "y", (0, 0, 0))]
        renderer.pdf()
        self.assertEqual(calls, ["italic"])


if __name__ == "__main__":
    unittest.main()
