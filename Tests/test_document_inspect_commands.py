from contextlib import redirect_stderr
import io
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


INSPECT = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools/document-inspect'))


class DocumentCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def stages(self):
        document = self.root / 'document with spaces.pdf'
        page = self.root / 'page.png'
        return (
            ('pdf_metadata', (document,), 'pdfinfo', 'pdfinfo could not read the document'),
            ('render_pages', (document, self.root, 2, 3, 144), 'pdftoppm',
             'pdftoppm could not render the document'),
            ('extract_text', (document, self.root / 'text.txt', 2, 3), 'pdftotext',
             'pdftotext could not extract the document'),
            ('make_contact_sheet', ([(3, page)], self.root / 'sheet.png'), 'montage',
             'montage could not build the contact sheet'),
            ('extract_ocr', ([(3, page)], self.root / 'ocr.txt', 'eng'), 'tesseract',
             'tesseract failed on page 3'),
        )

    def test_each_stage_keeps_stderr_and_fallback_diagnostics(self):
        for name, arguments, executable, fallback in self.stages():
            for stderr in ('  specific failure\n', ' \n'):
                with self.subTest(stage=name, stderr=stderr):
                    pages = self.root / 'pages'
                    if pages.exists():
                        pages.rmdir()
                    function = INSPECT[name]
                    error = io.StringIO()
                    failed = subprocess.CompletedProcess([], 7, 'unused output', stderr)
                    with patch.dict(function.__globals__, required_command=lambda name: '/fake bin/' + name), \
                         patch.object(subprocess, 'run', return_value=failed) as run, \
                         redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                        function(*arguments)
                    self.assertEqual(caught.exception.code, 1)
                    self.assertEqual(error.getvalue(), (stderr.strip() or fallback) + '\n')
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.args[0][0], '/fake bin/' + executable)
                    self.assertEqual(run.call_args.kwargs,
                                     {'check': False, 'text': True, 'capture_output': True})

    def test_missing_executables_fail_before_launch(self):
        for name, arguments, executable, _ in self.stages():
            with self.subTest(stage=name):
                error = io.StringIO()
                with patch('shutil.which', return_value=None), patch.object(subprocess, 'run') as run, \
                     redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    INSPECT[name](*arguments)
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(error.getvalue(), f'required command is unavailable: {executable}\n')
                run.assert_not_called()

    def test_ocr_resolves_once_and_preserves_order_and_page_separators(self):
        pages = [(2, self.root / 'two.png'), (5, self.root / 'five.png')]
        destination = self.root / 'ocr.txt'
        command = Mock(return_value='/fake bin/tesseract')
        responses = [subprocess.CompletedProcess([], 0, text, '')
                     for text in ('second page\n\n', 'fifth page \n')]
        function = INSPECT['extract_ocr']
        with patch.dict(function.__globals__, required_command=command), \
             patch.object(subprocess, 'run', side_effect=responses) as run:
            function(pages, destination, 'eng+fra')
        command.assert_called_once_with('tesseract')
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['/fake bin/tesseract', str(page), 'stdout', '-l', 'eng+fra']
                          for _, page in pages])
        self.assertEqual(destination.read_text(), 'second page\n\f\nfifth page\n')
