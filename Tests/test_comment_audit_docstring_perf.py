import ast
from pathlib import Path
import runpy
import textwrap
import unittest
from unittest.mock import patch


DOCSTRINGS = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "comment-audit")
)["python_docstrings"]


class CommentAuditDocstringTests(unittest.TestCase):
    def test_expression_literals_do_not_expand_into_docstring_search(self):
        source = '"""Previously module"""\nvalues = [' + ','.join(map(str, range(5000))) + ']\n'
        original = ast.iter_child_nodes
        with patch.object(ast, "iter_child_nodes", wraps=original) as expanded:
            findings = DOCSTRINGS(Path("fixture.py"), source)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 1)
        self.assertLessEqual(expanded.call_count, 4)

    def test_breadth_first_order_includes_control_flow_containers(self):
        source = textwrap.dedent('''\
            """Previously module"""
            @decorate(lambda value: value + 1)
            class Outer(Base[int]):
                """Previously class"""
                def method(self, value: list[int] = [1, 2]) -> str:
                    """Previously method"""
                    if condition:
                        def conditional():
                            """Previously conditional"""
                async def async_method(self):
                    """Previously async_method"""
            def function(value: tuple[int, str]):
                """Previously function"""
                def nested():
                    """Previously nested"""
            try:
                raise Error()
            except Error:
                def handler():
                    """Previously handler"""
            else:
                def try_else():
                    """Previously try_else"""
            finally:
                def try_finally():
                    """Previously try_finally"""
            match value:
                case {"key": captured} if captured:
                    def matched():
                        """Previously matched"""
            if condition:
                def top_cond():
                    """Previously top_cond"""
            for item in values:
                def loop():
                    """Previously loop"""
            with manager() as context_value:
                def context():
                    """Previously context"""
        ''')
        names = [
            "module", "class", "function", "method", "async_method", "nested",
            "try_else", "try_finally", "top_cond", "loop", "context", "handler",
            "matched", "conditional",
        ]
        expected = []
        for name in names:
            text = f"Previously {name}"
            line = source[:source.index(f'"""{text}"""')].count("\n") + 1
            expected.append({"path": "fixture.py", "line": line,
                             "category": "history-narration", "text": text})
        self.assertEqual(DOCSTRINGS(Path("fixture.py"), source), expected)

    def test_invalid_source_and_non_docstrings_are_ignored(self):
        for source in (
            "def invalid(\n",
            'value = "Previously assigned"\n',
            'def function():\n    pass\n    "Previously late string"\n',
            'def function():\n    "Ordinary documentation"\n',
            '',
        ):
            with self.subTest(source=source):
                self.assertEqual(DOCSTRINGS(Path("fixture.py"), source), [])


if __name__ == "__main__":
    unittest.main()
