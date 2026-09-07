from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "report-build"))
GLOBALS = MODULE["command_build"].__globals__


class ReportHtmlReuseTests(unittest.TestCase):
    def test_each_format_renders_html_only_when_needed_once(self):
        cases = [
            ("all", {"report.txt", "report.html", "report.tex", "report.pdf"}, 1),
            ("html", {"report.html"}, 1),
            ("pdf", {"report.tex", "report.pdf"}, 1),
            ("text", {"report.txt"}, 0),
            ("tex", {"report.tex"}, 0),
        ]
        for format_name, expected_files, expected_calls in cases:
            with self.subTest(format=format_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project = SimpleNamespace(root=root)
                html = Mock(return_value="<html>report</html>")
                renderer = Mock()
                renderer.pdf.return_value = b"PDF bytes"
                arguments = SimpleNamespace(path=root / "index.md", output="build", format=format_name, json=True)
                with patch.dict(
                    GLOBALS,
                    load_project=Mock(return_value=project), ensure_valid=Mock(),
                    render_html=html, render_text=Mock(return_value="Text content"),
                    render_latex=Mock(return_value="TeX content"),
                    NativePdfRenderer=Mock(return_value=renderer),
                ):
                    MODULE["command_build"](arguments)
                self.assertEqual(html.call_count, expected_calls)
                actual_files = {path.name: path.read_bytes() for path in (root / "build").iterdir()}
                contents = {
                    "report.txt": b"Text content", "report.html": b"<html>report</html>",
                    "report.tex": b"TeX content", "report.pdf": b"PDF bytes",
                }
                self.assertEqual(actual_files, {name: contents[name] for name in expected_files})
                if "report.pdf" in expected_files:
                    renderer.render.assert_called_once_with("<html>report</html>")

    def test_direct_pdf_call_still_renders_html(self):
        project = object()
        html = Mock(return_value="generated HTML")
        renderer = Mock()
        renderer.pdf.return_value = b"PDF bytes"
        with patch.dict(GLOBALS, render_html=html, NativePdfRenderer=Mock(return_value=renderer)):
            self.assertEqual(MODULE["render_pdf"](project), b"PDF bytes")
        html.assert_called_once_with(project)
        renderer.render.assert_called_once_with("generated HTML")

    def test_supplied_html_including_empty_string_is_used_directly(self):
        for content in ("supplied HTML", ""):
            with self.subTest(content=content):
                html = Mock()
                renderer = Mock()
                renderer.pdf.return_value = b"PDF bytes"
                with patch.dict(GLOBALS, render_html=html, NativePdfRenderer=Mock(return_value=renderer)):
                    self.assertEqual(MODULE["render_pdf"](object(), content), b"PDF bytes")
                html.assert_not_called()
                renderer.render.assert_called_once_with(content)


if __name__ == "__main__":
    unittest.main()
