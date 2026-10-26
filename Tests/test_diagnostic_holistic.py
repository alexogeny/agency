import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class LongProcessFormattingTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        binaries = root / 'bin'
        binaries.mkdir()
        scripts = {
            'ps': '#!/bin/sh\nif [ "$1" = -o ] && [ "$2" = ppid= ]; then printf "1\\n"; else cat "$PROCESS_ROWS"; fi\n',
            'fzf': '#!/bin/sh\ncat > "$CAPTURED_ROWS"\nexit 1\n',
        }
        for name, content in scripts.items():
            path = binaries / name
            path.write_text(content)
            path.chmod(0o755)
        ages = [2 * 86400 + 3 * 3600, 3 * 3600 + 23 * 60, 59 * 60, 15]
        rows = root / 'rows'
        rows.write_text(''.join(f'{999999900+i} 1 {age} 1.5 2.0 S fixture-{i}\n' for i, age in enumerate(ages)))
        capture = root / 'capture'
        probes = root / 'probes'
        hook = root / 'hook'
        hook.write_text('''set -T
formatter_parent=$BASHPID
trap 'if [[ $BASH_COMMAND == "format_age "* ]]; then printf "%s %s\\n" "$formatter_parent" "$BASHPID" >> "$FORMATTER_PROBES"; fi' DEBUG
''')
        result = subprocess.run(['/bin/bash', str(ROOT / 'Tools/long-processes'), '--age', '0s'],
            env={**os.environ, 'PATH':str(binaries)+os.pathsep+os.environ['PATH'],
                 'PROCESS_ROWS':str(rows),'CAPTURED_ROWS':str(capture),'FORMATTER_PROBES':str(probes),
                 'BASH_ENV':str(hook)},text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'')
        return capture.read_text().splitlines(), [line.split() for line in probes.read_text().splitlines()]

    def test_formats_nonempty_process_rows_without_changing_selection(self):
        rows, _ = self.fixture()
        self.assertEqual(len(rows),4)
        for index, age in enumerate(('2d 03h','3h 23m','59m','0m')):
            self.assertIn(age,rows[index])
            self.assertTrue(rows[index].startswith(str(999999900+index)))
            self.assertTrue(rows[index].endswith('fixture-'+str(index)))

    def test_row_age_formatting_does_not_start_subshells(self):
        rows, probes = self.fixture()
        self.assertTrue(rows)
        self.assertTrue(probes, 'formatter instrumentation did not execute')
        self.assertTrue(all(parent==actual for parent,actual in probes),probes)


class BenchmarkSamplerMemoryTests(unittest.TestCase):
    def test_sampling_retains_only_peaks_and_count(self):
        module = runpy.run_path(str(ROOT / 'Tools/resource-bench'))
        launch = module['launch_and_observe']
        count = 10000

        class Process:
            pid = 11
            returncode = 0
            polls = 0

            def communicate(self, timeout=None):
                self.polls += 1
                if self.polls <= count:
                    raise subprocess.TimeoutExpired(['fixture'], timeout)
                return b'proof', b''

        observed = 0
        def sample(pid):
            nonlocal observed
            observed += 1
            return {'rss':1000 + observed, 'pss':500 + observed,
                    'processes':2 if observed == 2 else 1}

        with patch.object(subprocess, 'Popen', new=lambda *a, **k: Process()), \
             patch.dict(launch.__globals__, process_tree_memory=sample):
            tracemalloc.start()
            try:
                status, stdout, stderr, memory = launch(['fixture'], ROOT, {}, 0, True, 5)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        self.assertEqual((status,stdout,stderr),(0,b'proof',b''))
        if isinstance(memory,list):
            memory = {**{key:max(row[key] for row in memory) for key in ('rss','pss','processes')},
                      'samples':len(memory)}
        self.assertEqual(memory,{'rss':11002,'pss':10502,'processes':2,'samples':10002})
        self.assertLess(peak,100000,f'sampler retained {peak} bytes of historical observations')


if __name__ == '__main__':
    unittest.main()
