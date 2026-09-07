from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "report-build"))


class CountedText(str):
    space_counts = 0

    def count(self, value, *args):
        if value == " ":
            self.space_counts += 1
        return super().count(value, *args)


class ReportLineMetricsTests(unittest.TestCase):
    def renderer(self, texts, link=None):
        renderer = MODULE["NativePdfRenderer"].__new__(MODULE["NativePdfRenderer"])
        renderer.base_size = 10
        renderer.settings = {"paragraph_spacing_pt": 4, "line_height": 1.2}
        renderer.content_width = Mock(return_value=100)
        renderer.content_left = Mock(return_value=20)
        renderer.wrapped_lines = Mock(return_value=[
            [{"text": text, "style": "regular", "link": link}] for text in texts
        ])
        renderer.ensure_space = Mock()
        renderer.measure = Mock(side_effect=lambda text, style, size: len(text) * 2)
        renderer.pages = [{"commands": [], "links": []}]
        renderer.page = 0
        renderer.y = 100
        renderer.destinations = {}
        return renderer

    def test_left_line_skips_discarded_final_advance(self):
        text = CountedText("a b")
        renderer = self.renderer([text])
        renderer.write_spans([])
        renderer.measure.assert_not_called()
        self.assertEqual(text.space_counts, 0)
        self.assertEqual(renderer.pages[0]["commands"], [("regular", 10, 20, 100, "a b", (0, 0, 0))])
        self.assertEqual(renderer.y, 84)

    def test_center_and_right_measure_width_without_counting_spaces(self):
        for align, x in (("center", 67), ("right", 114)):
            with self.subTest(align=align):
                text = CountedText("a b")
                renderer = self.renderer([text])
                renderer.write_spans([], align=align, justify=True)
                self.assertEqual(renderer.measure.call_count, 1)
                self.assertEqual(text.space_counts, 0)
                self.assertEqual(renderer.pages[0]["commands"][0][2], x)

    def test_justification_preserves_commands_links_and_last_line(self):
        first, last = CountedText("a b"), CountedText("c d")
        renderer = self.renderer([first, last], link="#target")
        renderer.write_spans([], justify=True, destination="target")
        self.assertEqual(renderer.pages[0]["commands"], [
            ("regular", 10, 20, 100, "a", (0, 0, 0)),
            ("regular", 10, 22, 100, " ", (0, 0, 0)),
            ("regular", 10, 118, 100, "b", (0, 0, 0)),
            ("regular", 10, 20, 88, "c d", (0, 0, 0)),
        ])
        self.assertEqual(renderer.pages[0]["links"], [
            (20, 97.8, 22, 110, "#target"),
            (118, 97.8, 120, 110, "#target"),
            (20, 85.8, 26, 98, "#target"),
        ])
        self.assertEqual(renderer.destinations, {"target": (0, 110)})
        self.assertEqual((first.space_counts, last.space_counts), (1, 0))
        self.assertEqual(renderer.y, 72)
        self.assertEqual(renderer.measure.call_count, 6)

    def test_justified_line_without_spaces_needs_no_total_width(self):
        renderer = self.renderer(["abc", "def"])
        renderer.write_spans([], justify=True)
        self.assertEqual(renderer.measure.call_count, 0)
        self.assertEqual([command[2] for command in renderer.pages[0]["commands"]], [20, 20])


    def test_repeated_span_object_still_advances_before_next_span(self):
        renderer = self.renderer([])
        span = {"text": "same", "style": "regular"}
        renderer.wrapped_lines.return_value = [[span, span]]
        renderer.write_spans([])
        renderer.measure.assert_called_once_with("same", "regular", 10)
        self.assertEqual([command[2] for command in renderer.pages[0]["commands"]], [20, 28])

    def test_last_linked_span_keeps_rectangle_measurement(self):
        renderer = self.renderer([])
        renderer.wrapped_lines.return_value = [[
            {"text": "aa", "style": "regular"},
            {"text": "bbb", "style": "bold", "link": "#target"},
        ]]
        renderer.write_spans([])
        self.assertEqual([call.args for call in renderer.measure.call_args_list], [
            ("aa", "regular", 10), ("bbb", "bold", 10),
        ])
        self.assertEqual([command[2] for command in renderer.pages[0]["commands"]], [20, 24])
        self.assertEqual(renderer.pages[0]["links"], [(24, 97.8, 30, 110, "#target")])


if __name__ == "__main__":
    unittest.main()
