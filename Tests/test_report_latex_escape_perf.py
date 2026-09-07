from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools' / 'report-build'))
ESCAPES = {
    '\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$',
    '&': r'\&', '%': r'\%', '#': r'\#', '_': r'\_',
    '^': r'\textasciicircum{}', '~': r'\textasciitilde{}',
}


class ReportLatexEscapeTests(unittest.TestCase):
    def test_escape_avoids_python_character_iteration(self):
        class CountedString(str):
            iterations = 0
            def __iter__(self):
                for character in super().__iter__():
                    self.iterations += 1
                    yield character
        text = CountedString('A plain paragraph with no escapes.' * 100)
        self.assertEqual(MODULE['latex_escape'](text), str(text))
        self.assertEqual(text.iterations, 0)

    def test_all_escapes_and_other_characters_are_preserved(self):
        values = ['', '\\{}$&%#_^~', 'plain ASCII', 'Καφές café 😀 日本語', '\x00\ud800\udfff', '\n\r\t']
        values += [chr(code) for code in range(256)]
        for value in values:
            with self.subTest(value=repr(value)):
                expected = ''.join(ESCAPES.get(character, character) for character in value)
                self.assertEqual(MODULE['latex_escape'](value), expected)

    def test_code_emphasis_links_and_token_like_text(self):
        project = SimpleNamespace(references={}, labels={})
        for source, expected in [
            ('plain', 'plain'),
            ('`a_b%`', r'\texttt{a\_b\%}'),
            ('**bold** and *italic*', r'\textbf{bold} and \emph{italic}'),
            ('[label_&](https://example.test/a_b)', r'\href{\detokenize{https://example.test/a_b}}{label\_\&}'),
            ('\x00TOKEN0\x00', '\x00TOKEN0\x00'),
            ('α😀 and *emphasis*', 'α😀 and ' + r'\emph{emphasis}'),
        ]:
            with self.subTest(source=source):
                self.assertEqual(MODULE['latex_inline'](source, project), expected)
