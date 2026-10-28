"""Supervise one backend group until completion or its owning pipe closes."""
import os
import signal
import subprocess
import sys
import threading
import time


def main():
    lifetime = int(sys.argv[1])
    if sys.argv[2] != '--':
        raise ValueError('Expected an executable argument vector')
    os.set_inheritable(lifetime, False)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    def watch_owner():
        try:
            while os.read(lifetime, 1):
                pass
        finally:
            os.close(lifetime)
            stopped.set()
    threading.Thread(target=watch_owner, daemon=True, name='backend-owner').start()
    process = subprocess.Popen(sys.argv[3:], close_fds=True, start_new_session=True)
    finished = None
    while not stopped.wait(.05):
        finished = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if finished is not None:
            break
    # Leave the group leader unreaped until all signals are sent, preventing PID reuse.
    if finished is None:
        os.killpg(process.pid, signal.SIGTERM)
        time.sleep(1)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    result = process.wait()
    return result if result >= 0 else 128 - result


if __name__ == '__main__':
    sys.exit(main())
