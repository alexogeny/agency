"""Linux project-cleanup checks and descriptor-anchored removal primitives."""
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_ITEMS = 128
PROC_LIMIT = 4 * 1024 * 1024


def _display(value):
    return ascii(str(value))[1:-1]


def mount_paths():
    try:
        with open('/proc/self/mountinfo', encoding='utf-8', errors='surrogateescape') as handle:
            return {re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), line.split()[4])
                    for line in handle if len(line.split()) > 4}
    except OSError as error:
        raise RuntimeError('Cannot inspect mount boundaries') from error


def _open_path(path):
    fd = os.open('/', FLAGS)
    try:
        for component in path.parts[1:]:
            following = os.open(component, FLAGS, dir_fd=fd)
            os.close(fd)
            fd = following
        return fd
    except BaseException:
        os.close(fd)
        raise


def _path(item):
    if not isinstance(item, dict) or item.get('scan_complete') is not True:
        raise RuntimeError('Project selection is invalid or its scan is incomplete')
    value = item.get('path')
    if not isinstance(value, str) or not value.startswith('/') or '\0' in value:
        raise RuntimeError('Project selection requires an absolute path')
    path = Path(value)
    if str(path) != value or '..' in path.parts or path == Path('/'):
        raise RuntimeError('Project selection requires a normalized non-root path')
    category = item.get('category')
    if category == 'python_environments':
        if path.name not in {'.venv', 'venv', 'env', '.env'}:
            raise RuntimeError('Python environment name is not supported for removal')
    elif category == 'node_dependencies':
        if path.name != 'node_modules':
            raise RuntimeError('Node dependencies must be named node_modules')
    else:
        raise RuntimeError('Project category is not supported for removal')
    identity = item.get('identity')
    if (not isinstance(identity, dict) or set(identity) != {'device', 'inode'}
            or any(type(value) is not int for value in identity.values())):
        raise RuntimeError('Project selection has no valid scanned identity')
    return path


def _identity_matches(info, item):
    return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
        item['identity']['device'], item['identity']['inode'])


def _checked(item, mounts):
    path = _path(item)
    prefix = str(path) + '/'
    if any(mount == str(path) or mount.startswith(prefix) for mount in mounts):
        raise RuntimeError(f'Project contains a mount boundary: {_display(path)}')
    parent_fd = root_fd = None
    try:
        parent_fd = _open_path(path.parent)
        root_fd = os.open(path.name, FLAGS, dir_fd=parent_fd)
        if not _identity_matches(os.fstat(root_fd), item):
            raise RuntimeError(f'Project identity changed: {_display(path)}')
        if item['category'] == 'python_environments':
            try:
                marker = os.stat('pyvenv.cfg', dir_fd=root_fd, follow_symlinks=False)
            except OSError as error:
                raise RuntimeError('Python environment has no readable regular pyvenv.cfg') from error
            if not stat.S_ISREG(marker.st_mode):
                raise RuntimeError('Python environment requires a regular pyvenv.cfg')
        return path, parent_fd, root_fd
    except BaseException as error:
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        if isinstance(error, OSError):
            raise RuntimeError(f'Project path changed, is inaccessible or contains a symlink: {_display(path)}') from error
        raise


def _reject_nested_git(root_fd):
    stack = []
    initial = os.dup(root_fd)
    device = os.fstat(initial).st_dev
    try:
        try:
            stack.append((initial, os.scandir(initial)))
        except BaseException:
            os.close(initial)
            raise
        while stack:
            fd, iterator = stack[-1]
            try:
                entry = next(iterator)
            except StopIteration:
                iterator.close()
                os.close(fd)
                stack.pop()
                continue
            if entry.name == '.git':
                raise RuntimeError('Selected directory contains a Git repository marker; preserve its source and history')
            if not entry.is_dir(follow_symlinks=False):
                continue
            if len(stack) >= 128:
                raise RuntimeError('Git marker inspection depth limit reached; refusing removal')
            child = os.open(entry.name, FLAGS, dir_fd=fd)
            try:
                if os.fstat(child).st_dev != device:
                    raise RuntimeError('Mount boundary encountered during Git marker inspection')
                iterator = os.scandir(child)
            except BaseException:
                os.close(child)
                raise
            stack.append((child, iterator))
    except OSError as error:
        raise RuntimeError('Cannot completely inspect selected directory for nested Git repositories') from error
    finally:
        for fd, iterator in reversed(stack):
            iterator.close()
            os.close(fd)


def _git_check(path, root_fd):
    _reject_nested_git(root_fd)
    executable = shutil.which('git')
    if executable is None:
        raise RuntimeError('Git is required to check for tracked project files')
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    environment['LC_ALL'] = 'C'
    command = [os.path.abspath(executable), '-c', 'core.fsmonitor=false', '-C', f'/proc/self/fd/{root_fd}']
    try:
        inside = subprocess.run([*command, 'rev-parse', '--is-inside-work-tree'],
                                env=environment, capture_output=True, timeout=10, check=False, pass_fds=(root_fd,))
        if inside.returncode:
            if inside.returncode == 128 and inside.stderr.startswith(b'fatal: not a git repository'):
                return
            raise RuntimeError('Git could not establish repository ownership; refusing removal')
        if inside.stdout.strip() != b'true':
            raise RuntimeError('Selected directory is not an ordinary Git worktree')
        with tempfile.TemporaryFile() as output:
            queried = subprocess.run([*command, 'ls-files', '-z', '--', '.'], env=environment,
                                     stdout=output, stderr=subprocess.PIPE, timeout=10, check=False, pass_fds=(root_fd,))
            if queried.returncode:
                raise RuntimeError('Git tracked-file query failed; refusing removal')
            output.seek(0)
            if output.read(1):
                raise RuntimeError(f'Selected directory contains Git tracked files: {_display(path)}')
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Git tracked-file inspection unavailable; refusing removal') from error


def _matching_roots(value, roots):
    if not value.startswith('/'):
        return
    if value.endswith(' (deleted)'):
        value = value[:-10]
    value = os.path.normpath(value)
    while value and value != '/':
        if value in roots:
            yield value
        value = value.rpartition('/')[0]


def _read_process_file(path):
    with open(path, 'rb') as handle:
        value = handle.read(PROC_LIMIT + 1)
    if len(value) > PROC_LIMIT:
        raise OSError('Process inspection size limit exceeded')
    return value


def inspect_processes(roots, *, ignore_own_arguments=False):
    roots = {str(root) for root in roots}
    if not roots:
        return {'blocked': {}, 'uninspected_processes': 0}
    unknown = 0
    evidence = {}
    names = {}
    def record(value, pid, kind):
        for root in _matching_roots(value, roots):
            processes = evidence.setdefault(root, {})
            if pid in processes or len(processes) < 3:
                processes.setdefault(pid, set()).add(kind)
    own_pid = str(os.getpid())
    names[own_pid] = _display(Path(sys.executable).name[:40]) or 'python'
    try:
        record(os.getcwd(), own_pid, 'cwd')
    except OSError as error:
        raise RuntimeError('Cannot inspect the current working directory') from error
    record(os.path.abspath(sys.prefix), own_pid, 'current Python environment')
    if ignore_own_arguments and sys.argv and not sys.argv[0].startswith('-'):
        record(os.path.abspath(sys.argv[0]), own_pid, 'command path')
    try:
        processes = os.scandir('/proc')
    except OSError as error:
        raise RuntimeError('Cannot inspect running processes') from error
    with processes:
        for entry in processes:
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat(follow_symlinks=False).st_uid != os.getuid():
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                unknown += 1
                continue
            process = Path(entry.path)
            incomplete = False
            process_cwd = None
            executable_name = None
            for name in ('cwd', 'exe'):
                try:
                    linked = os.readlink(process / name)
                    if name == 'cwd':
                        process_cwd = linked
                    else:
                        executable_name = Path(linked).name
                    record(linked, entry.name, 'cwd' if name == 'cwd' else 'command path')
                except FileNotFoundError:
                    pass
                except OSError:
                    incomplete = True
            try:
                name = os.fsdecode(_read_process_file(process / 'comm')).strip()
            except OSError:
                name = executable_name or 'process'
            names[entry.name] = _display(name[:40]) or 'process'
            try:
                with os.scandir(process / 'fd') as descriptors:
                    for count, descriptor in enumerate(descriptors):
                        if count >= 8192:
                            incomplete = True
                            break
                        try:
                            record(os.readlink(descriptor.path), entry.name, 'open file')
                        except FileNotFoundError:
                            pass
                        except OSError:
                            incomplete = True
            except FileNotFoundError:
                pass
            except OSError:
                incomplete = True
            for name in ('maps', 'cmdline', 'environ'):
                if name == 'cmdline' and entry.name == own_pid and ignore_own_arguments:
                    # The scanner's target argument is not a runtime dependency.
                    continue
                try:
                    content = _read_process_file(process / name)
                    if name == 'maps':
                        for line in content.splitlines():
                            fields = line.split(None, 5)
                            if len(fields) == 6:
                                mapped = re.sub(rb'\\([0-7]{3})', lambda match: bytes([int(match[1], 8)]), fields[5])
                                record(os.fsdecode(mapped), entry.name, 'mapped file')
                    elif name == 'environ':
                        for value in content.split(b'\0'):
                            if value.startswith(b'VIRTUAL_ENV='):
                                record(os.fsdecode(value[12:]), entry.name, 'VIRTUAL_ENV')
                    else:
                        for value in content.split(b'\0'):
                            text = os.fsdecode(value)
                            if text.startswith('--') and '=' in text:
                                text = text.split('=', 1)[1]
                            if process_cwd and '/' in text and not text.startswith(('/', '-')):
                                text = os.path.normpath(os.path.join(process_cwd, text))
                            record(text, entry.name, 'command path')
                except FileNotFoundError:
                    pass
                except OSError:
                    incomplete = True
            if incomplete and process.exists():
                unknown += 1
    blocked = {}
    for root, processes in evidence.items():
        details = [f"{names.get(pid, 'process')} (PID {pid}; {', '.join(sorted(kinds))})"
                   for pid, kinds in processes.items()]
        blocked[root] = 'In active use: ' + '; '.join(details)
    return {'blocked': blocked, 'uninspected_processes': unknown}


def report_projects(items):
    if not isinstance(items, list) or len(items) > 4096:
        raise RuntimeError('Inspect at most 4096 project directories at a time')
    if not items:
        return {'blocked': {}, 'uninspected_processes': 0}
    mounts = mount_paths()
    roots = set()
    blocked = {}
    seen = set()
    for item in items:
        raw = item.get('path') if isinstance(item, dict) else None
        if not isinstance(raw, str) or not raw.startswith('/'):
            raise RuntimeError('Each project report entry requires an absolute path')
        if raw in seen:
            blocked[raw] = 'Project selections overlap or repeat a directory'
            roots.discard(raw)
            continue
        seen.add(raw)
        try:
            path, parent_fd, root_fd = _checked(item, mounts)
            try:
                _git_check(path, root_fd)
            finally:
                os.close(root_fd)
                os.close(parent_fd)
        except RuntimeError as error:
            blocked[raw] = str(error)
            continue
        roots.add(str(path))
    for root in roots:
        for parent in _matching_roots(str(Path(root).parent), roots):
            blocked[root] = blocked[parent] = 'Project selections overlap or repeat a directory'
    inspected = inspect_processes(roots - blocked.keys())
    blocked.update(inspected['blocked'])
    return {'blocked': blocked, 'uninspected_processes': inspected['uninspected_processes']}


def validate_projects(items):
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise RuntimeError(f'Select at most {MAX_ITEMS} project directories at a time')
    result = report_projects(items)
    if result['blocked']:
        details = [f'{_display(path)}: {reason}' for path, reason in list(result['blocked'].items())[:5]]
        remaining = len(result['blocked']) - len(details)
        if remaining:
            details.append(f'{remaining} more blocked project directories')
        raise RuntimeError('; '.join(details))
    return {'uninspected_processes': result['uninspected_processes']}


def remove_project(item):
    if not getattr(shutil.rmtree, 'avoids_symlink_attacks', False):
        raise RuntimeError('This Python lacks descriptor-safe recursive removal')
    path, parent_fd, root_fd = _checked(item, mount_paths())
    holding_fd = None
    holding_name = '.housekeeping-' + secrets.token_hex(12)
    holding_path = path.parent / holding_name
    created = False
    try:
        _git_check(path, root_fd)
        os.mkdir(holding_name, 0o700, dir_fd=parent_fd)
        created = True
        holding_fd = os.open(holding_name, FLAGS, dir_fd=parent_fd)
        os.rename(path.name, 'selected', src_dir_fd=parent_fd, dst_dir_fd=holding_fd)
        moved = os.stat('selected', dir_fd=holding_fd, follow_symlinks=False)
        if not _identity_matches(moved, item):
            raise RuntimeError('Moved project identity does not match the approved selection')
        moved_path = str(holding_path / 'selected')
        if any(mount == moved_path or mount.startswith(moved_path + '/') for mount in mount_paths()):
            raise RuntimeError('Moved project contains a mount boundary')
        shutil.rmtree('selected', dir_fd=holding_fd)
        os.close(holding_fd)
        holding_fd = None
        os.rmdir(holding_name, dir_fd=parent_fd)
    except BaseException as error:
        if created:
            raise RuntimeError(f'Removal stopped; preserve and inspect holding directory {_display(holding_path)}') from error
        if isinstance(error, RuntimeError):
            raise
        raise RuntimeError(f'Project removal could not start: {_display(path)}') from error
    finally:
        if holding_fd is not None:
            os.close(holding_fd)
        os.close(root_fd)
        os.close(parent_fd)
