import runpy
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
Renderer = runpy.run_path(str(ROOT / 'Tools/report-build'))['NativePdfRenderer']


class ReportPlainTextWidthTests(unittest.TestCase):
    def fixture(self):
        value = Renderer.__new__(Renderer)
        value.pages = [{'commands': [], 'links': []}]
        value.page = 0
        value.y = 100
        value.measure = mock.Mock(return_value=42)
        return value

    def test_plain_text_does_not_measure_unused_width(self):
        value = self.fixture()
        value.add_command('plain text', 'regular', 10, 20, (0, 0, 0))
        value.measure.assert_not_called()
        self.assertEqual(value.pages[0], {'commands': [('regular', 10, 20, 100, 'plain text', (0, 0, 0))], 'links': []})

    def test_whitespace_link_does_not_measure_or_emit_annotation(self):
        value = self.fixture()
        value.add_command(' \t\n', 'bold', 12, 30, (1, 0, 0), 'https://fixture.test/')
        value.measure.assert_not_called()
        self.assertEqual(value.pages[0], {'commands': [('bold', 12, 30, 100, ' \t\n', (1, 0, 0))], 'links': []})

    def test_nonblank_link_preserves_measurement_and_rectangle(self):
        value = self.fixture()
        value.add_command(' link ', 'italic', 10, 20, (0, 0, 1), '#target')
        value.measure.assert_called_once_with(' link ', 'italic', 10)
        self.assertEqual(value.pages[0], {'commands': [('italic', 10, 20, 100, ' link ', (0, 0, 1))], 'links': [(20, 97.8, 62, 110, '#target')]})

    def test_empty_text_remains_ignored(self):
        value = self.fixture()
        value.add_command('', 'regular', 10, 20, (0, 0, 0), 'https://fixture.test/')
        value.measure.assert_not_called()
        self.assertEqual(value.pages[0], {'commands': [], 'links': []})


if __name__ == '__main__':
    unittest.main()
