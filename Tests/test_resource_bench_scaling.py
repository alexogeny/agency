import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


PROCESS_TREE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools/resource-bench'))['process_tree']


class ResourceBenchScalingTests(unittest.TestCase):
    def test_membership_work_is_bounded_per_process(self):
        for size in (64, 128, 256, 128):
            comparisons = []

            class Pid(int):
                __hash__ = int.__hash__

                def __eq__(self, other):
                    comparisons.append(1)
                    return int.__eq__(self, other)

            class ProcPath:
                def __init__(self, value):
                    self.pid = int(str(value).split('/')[2])

                def iterdir(self):
                    return iter((self,))

                def __truediv__(self, name):
                    return self

                def read_text(self):
                    return str(self.pid + 1) if self.pid < size else ''

            with self.subTest(size=size), patch.dict(PROCESS_TREE.__globals__, Path=ProcPath, int=Pid):
                result = PROCESS_TREE(Pid(1))
            self.assertEqual(list(map(int, result)), list(range(1, size + 1)))
            self.assertLessEqual(len(comparisons), size * 2)
