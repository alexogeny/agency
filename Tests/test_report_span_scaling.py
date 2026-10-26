import re
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools/report-build'))
Renderer = MODULE['NativePdfRenderer']


class ReportSpanScalingTests(unittest.TestCase):
    def setUp(self):
        self.renderer = Renderer.__new__(Renderer)

    def test_compacting_a_run_does_not_copy_growing_prefixes(self):
        original_sub = re.sub
        for size in (64, 128, 256, 128):
            copied = []

            class Text(str):
                def __add__(self, other):
                    copied.append(len(self) + len(other))
                    return Text(str.__add__(self, other))

            def sub(*args, **kwargs):
                return Text(original_sub(*args, **kwargs))

            spans = [dict(text='word ', style='regular', link=None) for _ in range(size)]
            with self.subTest(size=size), patch.object(re, 'sub', sub):
                result = self.renderer.compact_spans(spans)
            self.assertEqual(result, [dict(text='word ' * size, style='regular', link=None)])
            self.assertLessEqual(sum(copied), size * 5)
            self.assertEqual(spans[0]['text'], 'word ')

    def test_nested_inline_text_is_normalized_a_bounded_number_of_times(self):
        node = MODULE['HtmlNode']('span', {})
        node.children.append('word ' * 100)
        for _ in range(100):
            parent = MODULE['HtmlNode']('span', {})
            parent.children.append(node)
            node = parent
        original_sub = re.sub
        processed = []

        def sub(pattern, replacement, text, *args, **kwargs):
            processed.append(len(text))
            return original_sub(pattern, replacement, text, *args, **kwargs)

        with patch.object(re, 'sub', sub):
            result = self.renderer.inline_spans(node)
        self.assertEqual(result, [dict(text='word ' * 100, style='regular', link=None)])
        self.assertLessEqual(sum(processed), 1500)

    def test_branching_inline_text_is_normalized_a_bounded_number_of_times(self):
        def tree(depth):
            node = MODULE['HtmlNode']('span' if depth % 2 else 'em', {})
            if depth:
                node.children.extend((tree(depth - 1), tree(depth - 1)))
            else:
                node.children.append('word ' * 10)
            return node

        node = tree(7)
        original_sub = re.sub
        processed = []

        def sub(pattern, replacement, text, *args, **kwargs):
            processed.append(len(text))
            return original_sub(pattern, replacement, text, *args, **kwargs)

        with patch.object(re, 'sub', sub):
            result = self.renderer.inline_spans(node)
        self.assertEqual(result, [dict(text='word ' * 1280, style='italic', link=None)])
        self.assertLessEqual(sum(processed), 6400 * 3)

    def test_whitespace_style_and_link_boundaries_preserve_recursive_semantics(self):
        parser = MODULE['ReportHtmlParser']()
        parser.feed('<p>a <span> b <span> c </span> d </span> e <b>x<i> y <b> z </b></i></b><a href="one"> q <a href="two"> r </a> s </a><br> t</p>')
        node = parser.root.children[0]

        def reference(node, style='regular', link=None):
            spans = []
            for child in node.children:
                if isinstance(child, str):
                    spans.append(dict(text=child, style=style, link=link))
                    continue
                child_style = style
                if child.tag in {'strong', 'b'}:
                    child_style = 'bolditalic' if style == 'italic' else 'bold'
                elif child.tag in {'em', 'i'}:
                    child_style = 'bolditalic' if style == 'bold' else 'italic'
                child_link = child.attrs.get('href', link) if child.tag == 'a' else link
                if child.tag == 'br':
                    spans.append(dict(text=' ', style=style, link=link))
                else:
                    spans.extend(reference(child, child_style, child_link))
            compact = []
            for span in spans:
                text = re.sub(r'\s+', ' ', span['text'])
                if not text:
                    continue
                if compact and all(compact[-1].get(key) == span.get(key) for key in ('style', 'link')):
                    compact[-1]['text'] += text
                else:
                    compact.append(dict(span, text=text))
            return compact

        self.assertEqual(self.renderer.inline_spans(node), reference(node))
