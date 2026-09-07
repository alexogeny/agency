import re
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'Tools/report-build'))
PROJECT = SimpleNamespace(references={'REF': SimpleNamespace(citation='Example, 2025', author='Example', year='2025', sort_key=('example',))}, labels={'fig:one': ('Figure', 1)})


def original_restore(text, groups):
    for group, tokens in reversed(groups):
        text = re.sub(rf'\x00T{group}-([0-9]+)\x00', lambda match, values=tokens: values[int(match.group(1))], text)
    return text


class ReportEmptyTokenRestoreTests(unittest.TestCase):
    def test_plain_html_and_latex_skip_token_restoration_passes(self):
        for name in ('html_inline', 'latex_inline'):
            with self.subTest(renderer=name):
                with mock.patch.object(re, 'sub', wraps=re.sub) as substitute:
                    result = MODULE[name]('A plain paragraph with no formatting.', PROJECT)
                restores = [call for call in substitute.call_args_list if isinstance(call.args[0], str) and call.args[0].startswith(r'\x00T')]
                self.assertEqual(result, 'A plain paragraph with no formatting.')
                self.assertEqual(len(restores), 0)

    def test_mixed_formatting_and_raw_nul_tokens_match_original_restoration(self):
        texts = [
            '**bold *nested*** and `code & < >` [link](https://example.test/a?b=1&c=2)',
            'See [@REF, p. 3] and @REF; {cite: {ids: [REF], mode: narrative}}. {@fig:one}',
            '**[link](https://example.test)** *`literal @REF`* https://example.test/raw',
            '\0T0-0\0 plain \0T9-123\0',
            '\0T0-0\0 **bold** `code` [@REF] \0T12-0\0',
            '',
        ]
        for name in ('html_inline', 'latex_inline'):
            for text in texts:
                with self.subTest(renderer=name, text=text):
                    render = MODULE[name]
                    with mock.patch.dict(render.__globals__, {'restore_tokens': original_restore}):
                        expected = render(text, PROJECT)
                    self.assertEqual(render(text, PROJECT), expected)

    def test_nested_groups_restore_in_reverse_order_with_empty_groups(self):
        groups = [(0, ['inner']), (1, []), (2, ['<\0T0-0\0>']), (3, [])]
        self.assertEqual(MODULE['restore_tokens']('\0T2-0\0', groups), '<inner>')

    def test_invalid_index_in_populated_group_still_raises(self):
        with self.assertRaises(IndexError):
            MODULE['restore_tokens']('\0T2-8\0', [(2, ['value'])])


if __name__ == '__main__':
    unittest.main()
