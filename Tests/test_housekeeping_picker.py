import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'Tools/housekeeping_picker.py'
HARNESS = '''
import importlib.util, json, select, sys, termios
spec=importlib.util.spec_from_file_location('picker', sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
items=json.loads(sys.argv[2]); before=termios.tcgetattr(0)
options=json.loads(sys.argv[4])
updates=options.pop('updates', None)
refresh_error=options.pop('refresh_error', False)
if updates is not None or refresh_error:
    def refresh():
        print('CALLBACK_STARTED', flush=True)
        if refresh_error: raise RuntimeError('fixture refresh failure')
        return updates.pop(0)
    options['refresh']=refresh
if len(sys.argv)>3 and sys.argv[3]=='draw-error':
    original=m._frame; calls=[0]
    def failing(*args, **kwargs):
        calls[0]+=1
        if calls[0]>1: raise RuntimeError('fixture rendering failure')
        return original(*args, **kwargs)
    m._frame=failing
try:
    selected=m.pick_projects(items, colour=False, **options)
    print('RESULT='+json.dumps([item['label'] for item in selected]), flush=True)
except (KeyboardInterrupt, EOFError):
    print('CANCELLED', flush=True)
except RuntimeError:
    print('RENDER_ERROR', flush=True)
finally:
    print('QUEUED='+str(bool(select.select([0], [], [], 0)[0])), flush=True)
    print('RESTORED='+str(before == termios.tcgetattr(0)), flush=True)
'''


class PickerTests(unittest.TestCase):
    def candidates(self, count=3):
        return [{'path': f'/fixture/project{i}/.venv', 'label': f'project-{i}',
                 'category': 'python_environments', 'selectable': i != 1,
                 'allocated_bytes': 1024 * (i + 1), 'reason': 'Review only: unverified environment'}
                for i in range(count)]

    def run_picker(self, keys, count=3, resize=False, candidates=None, size=(10, 55), fail_draw=False, cancel_signal=None, **options):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', *size, 0, 0))
        process = subprocess.Popen([sys.executable, '-B', '-c', HARNESS, str(TOOL),
                                    json.dumps(self.candidates(count) if candidates is None else candidates),
                                    'draw-error' if fail_draw else 'normal', json.dumps(options)],
                                   stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        output = bytearray()
        def drain_until(marker, seconds=3):
            deadline = time.monotonic() + seconds
            while marker not in output and time.monotonic() < deadline:
                readable, _, _ = select.select([master], [], [], max(0, deadline-time.monotonic()))
                if not readable:
                    break
                try:
                    block = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not block:
                    break
                output.extend(block)
        try:
            drain_until(b'Space')
            self.assertIn(b'Space', output, output.decode(errors='replace'))
            if resize:
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 8, 38, 0, 0))
                os.kill(process.pid, signal.SIGWINCH)
            if cancel_signal:
                os.kill(process.pid, cancel_signal)
            else:
                os.write(master, keys)
            drain_until(b'RESTORED=True')
            process.wait(timeout=3)
            self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
            self.assertIn(b'RESTORED=True', output)
            self.assertIn(b'\x1b[?1049l', output)
            self.assertIn(b'\x1b[?25h', output)
            return output.decode(errors='replace')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_all_unselected_enter_selects_nothing(self):
        output = self.run_picker(b'\r')
        self.assertIn('RESULT=[]', output)
        self.assertIn('[ ]', output)

    def test_seeded_selection_excludes_disabled_and_missing_paths(self):
        output = self.run_picker(b'\r', initial_selected=[
            '/fixture/project0/.venv', '/fixture/project1/.venv', '/missing'])
        self.assertIn('RESULT=["project-0"]', output)
        self.assertIn('[x] project-0', output)

    def test_seeded_selection_is_capped(self):
        items = self.candidates(130)
        for item in items:
            item['selectable'] = True
        output = self.run_picker(b'\r', candidates=items, initial_selected=[item['path'] for item in items])
        result = output.split('RESULT=', 1)[1].splitlines()[0]
        self.assertEqual(len(json.loads(result)), 128)

    def test_refresh_drops_blocked_check_and_keeps_other_checked_path(self):
        items = self.candidates()
        items[0].update(selectable=False, reason='Now busy')
        items[2]['label'] = 'renamed-project'
        output = self.run_picker(b'r\r', updates=[items[::-1]],
                                 initial_selected=['/fixture/project0/.venv', '/fixture/project2/.venv'])
        self.assertIn('RESULT=["renamed-project"]', output)
        self.assertIn('Now busy', output)
        self.assertIn('> [-] project-0', output)

    def test_refresh_reenables_row_without_checking_it(self):
        items = self.candidates()
        items[1].update(selectable=True, label='available-now')
        output = self.run_picker(b'\x1b[BR\r', updates=[items], size=(10, 100))
        self.assertIn('> [ ] available-now', output)
        self.assertIn('RESULT=[]', output)
        self.assertIn('R refresh', output)
        self.assertLess(output.index('Checking availability...'), output.index('CALLBACK_STARTED'))

    def test_refresh_does_not_restore_a_check_dropped_when_busy(self):
        busy = self.candidates()
        busy[0].update(selectable=False, reason='Now busy')
        output = self.run_picker(b'rr\r', updates=[busy, self.candidates()],
                                 initial_selected=['/fixture/project0/.venv', '/fixture/project2/.venv'])
        self.assertIn('RESULT=["project-2"]', output)
        self.assertEqual(output.count('CALLBACK_STARTED'), 2)

    def test_all_disabled_rows_remain_browsable(self):
        items = self.candidates()
        for item in items:
            item['selectable'] = False
        items[2]['reason'] = 'Final blocked row'
        output = self.run_picker(b'\x1b[B\x1b[B \r', candidates=items)
        self.assertIn('> [-] project-2', output)
        self.assertIn('Final blocked row', output)
        self.assertIn('RESULT=[]', output)

    def test_notice_on_first_frame_and_optional_refresh_control(self):
        notice = 'Some folders became unavailable; other choices kept.'
        output = self.run_picker(b'\r', notice=notice, size=(10, 100))
        self.assertIn(notice, output)
        self.assertNotIn('R refresh', output)

    def test_empty_candidates_can_refresh_and_refresh_exception_restores_terminal(self):
        output = self.run_picker(b'r \r', candidates=[], updates=[self.candidates()])
        self.assertIn('No project directories to select.', output)
        self.assertIn('RESULT=["project-0"]', output)
        self.assertIn('RENDER_ERROR', self.run_picker(b'r', refresh_error=True))

    def test_space_toggles_selectable_rows_and_skips_disabled(self):
        output = self.run_picker(b' \x1b[B \x1b[B \r')
        self.assertIn('RESULT=["project-0", "project-2"]', output)
        self.assertIn('[-]', output)
        self.assertIn('Review only', output)

    def test_scroll_and_resize_reach_last_candidate(self):
        output = self.run_picker(b'\x1b[B' * 24 + b' \r', count=25, resize=True)
        self.assertIn('RESULT=["project-24"]', output)

    def test_cancel_keys_restore_terminal(self):
        for key in (b'q', b'\x1b', b'\x03', b'\x04'):
            with self.subTest(key=key):
                self.assertIn('CANCELLED', self.run_picker(key))

    def test_queued_keystrokes_cannot_answer_next_confirmation(self):
        output = self.run_picker(b'\ryes\n')
        self.assertIn('RESULT=[]', output)
        self.assertIn('QUEUED=False', output)

    def test_zero_terminal_dimensions_use_a_readable_fallback(self):
        self.assertIn('RESULT=[]', self.run_picker(b'\r', size=(0, 0)))

    def test_signal_cancellation_and_render_failure_restore_terminal(self):
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum):
                self.assertIn('CANCELLED', self.run_picker(b'', cancel_signal=signum))
        self.assertIn('RENDER_ERROR', self.run_picker(b' ', fail_draw=True))

    def test_selection_cap_is_visible_and_cannot_be_exceeded(self):
        items = self.candidates(129)
        for item in items:
            item['selectable'] = True
        output = self.run_picker((b' \x1b[B' * 128) + b' \r', candidates=items)
        result = next(line for line in output.splitlines() if 'RESULT=' in line).split('RESULT=', 1)[1]
        self.assertEqual(len(json.loads(result)), 128)
        self.assertIn('Selection limit: 128', output)

    def test_control_paths_do_not_reach_terminal_unescaped(self):
        items = self.candidates()
        items[0]['label'] = '\x1b]52;c;secret\x07\n' + '界' * 60 + '\u202e'
        output = self.run_picker(b'\r', candidates=items)
        self.assertNotIn('\x1b]52', output)
        self.assertNotIn('\x07', output)
        self.assertNotIn('\u202e', output)


if __name__ == '__main__':
    unittest.main()
