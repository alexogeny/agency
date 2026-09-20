"""Count decision receipts without retaining tool inputs or decision content."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import uuid


MARKER = '_agency_decisions'
MAX_INPUT = 1024 * 1024
MAX_STATE = 256 * 1024
MAX_REPORTS = 2048


def with_report(value):
    if MARKER in value:
        return value
    decisions = errors = reused = 0
    if not value.get('dry_run'):
        if 'items' in value:
            for row in value['items']:
                if 'result' in row:
                    row['result'].pop(MARKER, None)
                if row.get('reused'):
                    reused += int('result' in row)
                else:
                    decisions += int('result' in row)
                    errors += int('error' in row)
        else:
            decisions = int('decision' in value)
            errors = int('error' in value)
    value[MARKER] = {'version': 1, 'id': uuid.uuid4().hex, 'created_ns': time.time_ns(),
                     'decisions': decisions, 'errors': errors, 'reused': reused}
    return value


def receipts(value):
    found = {}
    complete = True
    pending = [(value, 0)]
    visits = 0
    parsed_bytes = 0
    while pending:
        item, depth = pending.pop()
        visits += 1
        if depth > 12 or visits > 4096:
            complete = False
            break
        if isinstance(item, dict):
            if MARKER in item:
                report = item[MARKER]
                if (type(report) is dict and type(report.get('version')) is int and report['version'] == 1
                        and type(report.get('id')) is str
                        and re.fullmatch(r'[0-9a-f]{32}', report['id'])
                        and type(report.get('created_ns')) is int
                        and all(type(report.get(key)) is int and 0 <= report[key] <= 32
                                for key in ('decisions', 'errors', 'reused'))):
                    found[report['id']] = report
                else:
                    complete = False
                # A batch receipt already accounts for its nested worker results.
                continue
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str) and MARKER in item:
            parsed_bytes += len(item)
            if parsed_bytes > 4 * MAX_INPUT:
                complete = False
                break
            try:
                decoded = json.loads(item)
            except (ValueError, RecursionError):
                decoded = None
            if decoded is not None:
                pending.append((decoded, depth + 1))
            else:
                for line in item.splitlines():
                    if MARKER not in line or not line.lstrip().startswith(('{', '[')):
                        continue
                    try:
                        decoded = json.loads(line)
                    except (ValueError, RecursionError):
                        complete = False
                        continue
                    pending.append((decoded, depth + 1))
    return found, complete


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _state_directory():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    path = (Path(runtime) / 'agency-decision-usage' if runtime
            else Path(tempfile.gettempdir()) / f'agency-decision-usage-{os.getuid()}')
    path.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(descriptor)
        raise ValueError('Unsafe usage directory')
    return descriptor


def _summary(state):
    if not state or not state.get('started'):
        return 'Jev: usage unavailable (turn start not observed)'
    count = state['decisions']
    parts = [f'Jev: {count} decision' + ('' if count == 1 else 's')]
    if state['errors']:
        count = state['errors']
        parts.append(f'{count} error' + ('' if count == 1 else 's'))
    if state['reused']:
        parts.append(f"{state['reused']} reused")
    if not state['complete']:
        parts.append('count incomplete')
    return ' · '.join(parts)


@contextmanager
def _locked_state(identity):
    directory = _state_directory()
    try:
        descriptor = os.open(_digest(identity) + '.json',
                             os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, 'r+', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Unsafe usage file')
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield stream


def _gap(client, record=False):
    # An unreadable event cannot be assigned safely to one session. Mark every
    # currently active turn for this client incomplete rather than invent zero.
    with _locked_state(client + ':gap') as stream:
        if record:
            value = time.time_ns()
            stream.seek(0)
            stream.write(str(value))
            stream.truncate()
            return value
        return int(stream.read(64) or '0')


def hook(client, payload):
    event = payload.get('hook_event_name')
    session = payload.get('session_id')
    if type(session) is not str or not session or len(session) > 512:
        raise ValueError('Missing session identity')
    if event not in ('UserPromptSubmit', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'Interrupt'):
        return {}
    # Claude subagents share a session id; never attribute them to the main turn.
    if payload.get('agent_id'):
        return {}
    turn = payload.get('turn_id')
    if turn is not None and (type(turn) is not str or not turn or len(turn) > 512):
        raise ValueError('Invalid turn identity')
    turn_hash = _digest(turn) if turn else None
    reports = {}
    complete = True
    if event in ('PostToolUse', 'PostToolUseFailure'):
        reports, complete = receipts(payload.get('tool_response', {}))
        tool = payload.get('tool_name', '')
        arguments = payload.get('tool_input', {})
        command = arguments.get('command', arguments.get('cmd', '')) if isinstance(arguments, dict) else ''
        expected = (isinstance(tool, str) and 'agency' in tool and 'decide' in tool and 'classify' in tool
                    or isinstance(command, str) and 'agency-decide' in command
                    and re.search(r'\b(classify|classify-batch|evaluate)\b', command))
        if not reports and expected:
            complete = False
        if not reports and complete:
            return {}
    with _locked_state(client + ':session:' + session) as stream:
        raw = stream.read(MAX_STATE + 1)
        if len(raw) > MAX_STATE:
            raise ValueError('Oversized usage state')
        try:
            state = json.loads(raw) if raw else {}
        except ValueError:
            if event != 'UserPromptSubmit':
                raise
            state = {}
        if type(state) is not dict:
            if event != 'UserPromptSubmit':
                raise ValueError('Invalid usage state')
            state = {}
        if event == 'UserPromptSubmit':
            if not turn_hash or state.get('turn') != turn_hash:
                state = {'turn': turn_hash, 'started': time.time_ns(), 'complete': True,
                         'decisions': 0, 'errors': 0, 'reused': 0, 'seen': []}
        elif turn_hash and state.get('turn') != turn_hash:
            return {'systemMessage': 'Jev: usage unavailable (turn start not observed)'} if event in ('Stop', 'Interrupt') else {}
        elif event in ('Stop', 'Interrupt'):
            if state and _gap(client) > state['started']:
                state['complete'] = False
            return {'systemMessage': _summary(state)}
        elif state:
            state['complete'] = state['complete'] and complete
            seen = set(state['seen'])
            for identifier, report in reports.items():
                if identifier in seen or report['created_ns'] < state['started']:
                    continue
                if report['created_ns'] > time.time_ns() or len(seen) >= MAX_REPORTS:
                    state['complete'] = False
                    continue
                seen.add(identifier)
                for key in ('decisions', 'errors', 'reused'):
                    state[key] += report[key]
            state['seen'] = sorted(seen)
        stream.seek(0)
        json.dump(state, stream, separators=(',', ':'))
        stream.truncate()
    return {'systemMessage': _summary(state)} if client == 'pi' else {}


def main():
    parser = argparse.ArgumentParser(description='Private per-turn Jev counts from CLI/MCP receipts.')
    parser.add_argument('--client', choices=('codex', 'claude', 'pi'), required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('Oversized hook input')
        payload = json.loads(raw)
        if type(payload) is not dict:
            raise ValueError('Invalid hook input')
        result = hook(args.client, payload)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        try:
            _gap(args.client, record=True)
        except (OSError, ValueError):
            pass  # A broken or unsafe state directory must not block the client.
        result = {'systemMessage': 'Jev: usage unavailable (counter could not read this event)'}
    print(json.dumps(result))
    return 0
