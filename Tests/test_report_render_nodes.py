from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools/report-build'))


class ReportNodeRenderingTests(unittest.TestCase):
    def setUp(self):
        renderer_type = MODULE['NativePdfRenderer']
        self.renderer = renderer_type.__new__(renderer_type)
        self.renderer.base_size = 10
        self.renderer.settings = {
            'title': {'size_pt': 22, 'alignment': 'right'},
            'heading_spacing_pt': {'before': 8, 'after': 4},
            'paragraph_spacing_pt': 6,
        }
        self.spans = [{'text': 'Content', 'style': 'bold', 'link': None}]
        self.renderer.inline_spans = Mock(return_value=self.spans)
        self.renderer.write_spans = Mock()

    def assert_heading(self, tag, classes, size, before, after, align):
        node = MODULE['HtmlNode'](tag, {'class': classes, 'id': 'destination'})
        self.renderer.render_node(node)
        self.renderer.inline_spans.assert_called_with(node, 'bold')
        arguments, options = self.renderer.write_spans.call_args
        self.assertEqual(arguments, (self.spans,))
        self.assertAlmostEqual(options['size'], size)
        self.assertEqual({key: value for key, value in options.items() if key != 'size'}, {
            'before': before, 'after': after, 'colour': (0, 0, 0),
            'destination': 'destination', 'align': align,
        })

    def test_normal_heading_levels_keep_sizes_spacing_and_destination(self):
        for level, size in ((1, 22), (2, 13.6), (3, 11.8), (4, 10.9), (5, 10), (6, 10)):
            with self.subTest(level=level):
                self.assert_heading(f'h{level}', '', size, 8, 4, 'left')

    def test_cover_heading_classes_keep_priority_alignment_and_spacing(self):
        for classes, size, before, after, align in (
            ('cover-title', 22, 0, 12, 'right'),
            ('cover-label', 10, 14, 4, 'center'),
            ('cover-label cover-author-label', 10, 60, 4, 'center'),
            ('cover-title cover-label cover-author-label', 22, 0, 12, 'right'),
        ):
            with self.subTest(classes=classes):
                self.assert_heading('h2', classes, size, before, after, align)

    def test_paragraph_cover_and_byline_alignment_is_independent_of_headings(self):
        for classes, justify, align, after in (
            ('', True, 'left', 6),
            ('subtitle', False, 'left', 6),
            ('byline', False, 'left', 6),
            ('cover-subtitle', False, 'center', 3.5),
            ('cover-assessment cover-detail cover-date byline', False, 'center', 3.5),
        ):
            with self.subTest(classes=classes):
                node = MODULE['HtmlNode']('p', {'class': classes})
                self.renderer.render_node(node)
                self.renderer.inline_spans.assert_called_with(node)
                self.renderer.write_spans.assert_called_with(self.spans, justify=justify, align=align, after=after)
