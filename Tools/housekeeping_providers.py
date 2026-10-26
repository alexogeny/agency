"""Application-owned cleanup rules, read-only eligibility and guarded removal."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import time

import housekeeping_projects as projects

PROFILE_DAYS = 30
PROFILE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
RELEASE_NAME = re.compile(r'(\d+)\.(\d+)\.(\d+)-([A-Za-z0-9_-]+)\Z')
RULES = {
    'web-cache': ('Clear inactive web-research browser cache',
                  'Remove this cache directory only. Cookies, history, logins, website storage, extensions and captures remain.'),
    'web-profile': ('Remove a completed web-research profile',
                    'Remove the entire explicitly selected profile, including logins and site data. Captures and the research index remain.'),
    'codex-release': ('Remove an obsolete Codex app-server release',
                      'Keep the current release, one older rollback, newer staged releases and releases observed in active use. Sessions and databases remain.'),
    'thumbnails': ('Clear generated desktop thumbnails',
                   'PNG previews regenerate. Close applications using these previews before selecting this action.'),
    'pacman': ('Prune older pacman package archives',
               'Keep two versions per package by default. Installed software remains; older cached rollback packages are removed. Requires administrator authentication.'),
}


def web_root(home):
    return Path(os.path.abspath(os.path.expanduser(os.environ.get('WEB_RESEARCH_DATA_DIR', str(home / '.local/share/web-research')))))


def proposal(path, home):
    path, home = Path(path), Path(home)
    action = None
    profile = None
    try:
        parts = path.relative_to(web_root(home) / 'profiles').parts
    except ValueError:
        parts = ()
    if parts and PROFILE_NAME.fullmatch(parts[0]) and parts[0] != '..':
        profile = web_root(home) / 'profiles' / parts[0]
        if len(parts) == 1:
            action = 'web-profile'
        elif len(parts) == 2 and parts[1] in {'cache2', 'startupCache'}:
            action = 'web-cache'
    releases = home / '.codex/packages/app-server-daemon/releases'
    if path.parent == releases:
        action = 'codex-release'
    elif path == home / '.cache/thumbnails':
        action = 'thumbnails'
    elif path == Path('/var/cache/pacman/pkg'):
        action = 'pacman'
    if action is None:
        return None
    title, tradeoff = RULES[action]
    return dict(path=str(path), home=str(home), provider=True, action=action,
                kind='review' if action in {'web-profile', 'codex-release'} else 'cache',
                title=title, tradeoff=tradeoff, command=None, scan_complete=True,
                allocated_bytes=0, apparent_bytes=0, files=0,
                profile=str(profile) if profile else None)


def _json(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 65536:
            raise RuntimeError('Lifecycle metadata is not a small regular file owned by this user')
        return json.loads(handle.read(65537))


def profile_metadata(profile):
    try:
        value = _json(str(profile) + '.agency.json')
    except (OSError, ValueError, RuntimeError) as error:
        raise RuntimeError('Lifecycle metadata missing or invalid; preserve this legacy profile') from error
    if (not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('owner') != 'web-research'
            or type(value.get('pinned')) is not bool or not isinstance(value.get('purpose'), str)
            or not value['purpose'].strip()):
        raise RuntimeError('Lifecycle metadata does not establish web-research ownership and purpose')
    return value


def _whole_profile_reason(profile):
    metadata = profile_metadata(profile)
    if metadata['pinned']:
        raise RuntimeError('Profile is pinned; preserve it')
    cutoff = time.time() - PROFILE_DAYS * 86400
    for field in ('last_used_at', 'completed_at'):
        value = metadata.get(field)
        if type(value) not in {int, float} or not 0 < value <= cutoff:
            raise RuntimeError(f'Whole-profile removal requires recorded completion and no use for {PROFILE_DAYS} days')
    return metadata


def _lock_owner(lock):
    descriptor = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('Profile lock is not a regular file owned by this user')
        data = handle.read(65)
    if not re.fullmatch(rb'[1-9][0-9]{0,15}', data):
        raise RuntimeError('Profile lock has an invalid owner; preserve it')
    owner = int(data)
    try:
        os.kill(owner, 0)
    except ProcessLookupError:
        return info
    except (OSError, OverflowError) as error:
        raise RuntimeError('Cannot establish profile lock ownership; preserve it') from error
    raise RuntimeError(f'Profile is in active use by PID {owner}')


def _profile_check(profile):
    try:
        _lock_owner(str(profile) + '.lock')
    except FileNotFoundError:
        pass
    for name in ('parent.lock', 'lock'):
        if os.path.lexists(profile / name):
            raise RuntimeError('Firefox profile has a native lock; close Firefox and inspect it')
    try:
        descriptor = os.open(profile / '.parentlock', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError('Firefox lock is not a regular file')
        # Firefox uses POSIX record locks; a shared probe also works with a read-only descriptor.
        fcntl.lockf(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError as error:
        raise RuntimeError('Firefox profile is locked or its native lock cannot be inspected') from error
    finally:
        os.close(descriptor)


def _codex_retention(parent):
    try:
        current = (parent / 'current').resolve(strict=True)
    except OSError as error:
        raise RuntimeError('Current Codex release is unavailable; preserve all releases') from error
    releases = parent / 'releases'
    matched = RELEASE_NAME.fullmatch(current.name)
    if not (parent / 'current').is_symlink() or current.parent != releases or not matched:
        raise RuntimeError('Current Codex release does not identify a recognized release in this tree')
    current_version = tuple(map(int, matched.groups()[:3]))
    platform = matched[4]
    older = []
    for entry in releases.iterdir():
        match = RELEASE_NAME.fullmatch(entry.name)
        if match and match[4] == platform and entry.is_dir() and not entry.is_symlink():
            version = tuple(map(int, match.groups()[:3]))
            if version < current_version:
                older.append((version, entry.name))
    rollback = max(older)[1] if older else None
    return current, rollback, current_version, platform


def _thumbnail_check(root):
    flags = projects.FLAGS
    initial = projects._open_path(root)
    stack = []
    count = 0
    try:
        stack.append((initial, os.scandir(initial), ()))
        while stack:
            descriptor, iterator, parts = stack[-1]
            try:
                entry = next(iterator)
            except StopIteration:
                iterator.close()
                os.close(descriptor)
                stack.pop()
                continue
            count += 1
            if count > 200000:
                raise RuntimeError('Thumbnail inspection limit reached; review manually')
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                if ((not parts and entry.name not in {'normal', 'large', 'x-large', 'xx-large', 'fail'})
                        or (parts and (parts != ('fail',)))):
                    raise RuntimeError('Thumbnail tree contains an unfamiliar directory; preserve it')
                child = os.open(entry.name, flags, dir_fd=descriptor)
                stack.append((child, os.scandir(child), (*parts, entry.name)))
            elif not (stat.S_ISREG(info.st_mode) and parts and entry.name.endswith('.png')):
                raise RuntimeError('Thumbnail tree contains unfamiliar files; preserve them')
    finally:
        for descriptor, iterator, _ in reversed(stack):
            iterator.close()
            os.close(descriptor)


def _checked(item, mounts, retention=None):
    raw = item.get('path')
    if not isinstance(raw, str) or not raw.startswith('/') or '..' in Path(raw).parts or str(Path(raw)) != raw:
        raise RuntimeError('Application cleanup requires a normalized absolute path')
    complete = item.get('scan_complete') or (item.get('action') == 'pacman' and item.get('native_plan_complete') is True)
    if not complete or not isinstance(item.get('identity'), dict):
        raise RuntimeError('Application scan incomplete or identity missing')
    path = Path(raw)
    expected = proposal(path, Path(item['home']))
    if not expected or expected['action'] != item.get('action'):
        raise RuntimeError('Path does not match its application cleanup rule')
    if any(mount == raw or mount.startswith(raw + '/') for mount in mounts):
        raise RuntimeError('Application cleanup contains a mount boundary')
    descriptor = projects._open_path(path)
    try:
        info = os.fstat(descriptor)
        if {'device': info.st_dev, 'inode': info.st_ino} != item['identity']:
            raise RuntimeError('Application directory identity changed; rerun the scan')
        if item['action'] != 'pacman' and info.st_uid != os.getuid():
            raise RuntimeError('Application directory is not owned by this user')
    finally:
        os.close(descriptor)
    action = item['action']
    if action in {'web-cache', 'web-profile'}:
        profile = Path(expected['profile'])
        profile_descriptor = projects._open_path(profile)
        os.close(profile_descriptor)
        _profile_check(profile)
        if action == 'web-profile':
            _whole_profile_reason(profile)
    elif action == 'codex-release':
        parent = path.parent.parent
        if retention is None:
            state = _codex_retention(parent)
        else:
            if parent not in retention:
                try:
                    retention[parent] = _codex_retention(parent)
                except (OSError, RuntimeError, ValueError) as error:
                    retention[parent] = error
            state = retention[parent]
            if isinstance(state, Exception):
                raise state
        current, rollback, version, platform = state
        match = RELEASE_NAME.fullmatch(path.name)
        if not match or match[4] != platform:
            raise RuntimeError('Unrecognized release version or platform; preserve it')
        try:
            metadata = _json(path / 'codex-package.json')
        except (OSError, ValueError, RuntimeError) as error:
            raise RuntimeError('Codex installation metadata missing or invalid; preserve this directory') from error
        if (not isinstance(metadata, dict) or metadata.get('layoutVersion') != 1 or metadata.get('variant') != 'codex'
                or metadata.get('version') != '.'.join(match.groups()[:3]) or metadata.get('target') != platform
                or metadata.get('entrypoint') != 'bin/codex'):
            raise RuntimeError('Codex installation metadata does not match this release')
        if path == current:
            raise RuntimeError('Keep the current Codex release')
        if path.name == rollback:
            raise RuntimeError('Keep one older Codex rollback release')
        if tuple(map(int, match.groups()[:3])) >= version:
            raise RuntimeError('Keep a newer staged Codex release')
    elif action == 'thumbnails':
        _thumbnail_check(path)
    return path


def pacman_preview(item, keep=2):
    if type(keep) is not int or keep < 1:
        raise RuntimeError('Keep at least one pacman package version')
    executable = shutil.which('paccache')
    if not executable:
        raise RuntimeError('paccache is unavailable')
    environment = {**os.environ, 'LC_ALL': 'C'}
    result = subprocess.run([executable, '-d', '-vv', '-z', '--nocolor', '-k', str(keep), '-c', item['path']],
                            env=environment, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Read-only paccache planning failed')
    value = result.stdout
    if len(value) > 4 * 1024 * 1024:
        raise RuntimeError('paccache candidate output exceeds the planning limit')
    header = b'==> Candidate packages:\n'
    if value.startswith(header):
        chunks = value[len(header):].split(b'\0')
        if not chunks[-1].startswith(b'\n==> finished dry run:'):
            raise RuntimeError('Unrecognized paccache candidate output')
        names = chunks[:-1]
    elif b'no candidate packages found' in value or not value.strip():
        names = []
    else:
        raise RuntimeError('Unrecognized paccache candidate output')
    entries = []
    for name in names:
        path = Path(os.fsdecode(name))
        if path.parent != Path(item['path']) or not re.fullmatch(r'.+\.pkg\.tar(?:\.[A-Za-z0-9]+)?(?:\.sig)?', path.name):
            raise RuntimeError('paccache returned a file outside the recognized package cache')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_dev != item['identity']['device']:
            raise RuntimeError('paccache candidate is not an ordinary file on this filesystem')
        entries.append(dict(path=str(path), inode=info.st_ino, size=info.st_size, mtime_ns=info.st_mtime_ns,
                            allocated_bytes=info.st_blocks * 512))
    return dict(keep_versions=keep, candidate_files=entries, executable=str(Path(executable).resolve()), native_plan_complete=True,
                candidate_apparent_bytes=sum(entry['size'] for entry in entries),
                candidate_allocated_bytes=sum(entry['allocated_bytes'] for entry in entries))


def report_actions(items, *, selection=True):
    blocked, roots = {}, {}
    mounts = projects.mount_paths()
    retention = {}
    for item in items:
        try:
            path = _checked(item, mounts, retention)
            root = str(Path(item['profile'])) if item.get('profile') else str(path)
            roots.setdefault(root, []).append(item['path'])
        except (OSError, RuntimeError, ValueError) as error:
            blocked[item['path']] = str(error)
    if selection:
        paths = {item['path'] for item in items}
        for path in paths:
            for parent in projects._matching_roots(str(Path(path).parent), paths):
                blocked[path] = blocked[parent] = 'Cleanup selections overlap; choose the profile or its caches'
    inspection = projects.inspect_processes(roots, ignore_own_arguments=True)
    for root, reason in inspection['blocked'].items():
        for path in roots[root]:
            blocked[path] = reason
    return dict(blocked=blocked, uninspected_processes=inspection['uninspected_processes'])


def plan(proposals, *, pacman_keep=2):
    candidates = []
    for original in proposals:
        if not original.get('provider'):
            continue
        item = dict(original, category='application_data', selectable=True,
                    reason='Choose explicitly; availability and retention are checked again before removal.',
                    selected=False, refreshable=bool(original.get('scan_complete') and original.get('identity')),
                    age_note='Modification times describe file activity; access times do not establish last use.')
        if item['action'] == 'web-profile':
            item.update(item.get('subtree_totals', {}))
            try:
                item['lifecycle'] = profile_metadata(Path(item['path']))
            except RuntimeError:
                pass
        if item['action'] == 'pacman':
            try:
                item.update(pacman_preview(item, pacman_keep))
                item['cache_totals'] = {key: original[key] for key in ('allocated_bytes', 'apparent_bytes', 'files')}
                item.update(allocated_bytes=item['candidate_allocated_bytes'], apparent_bytes=item['candidate_apparent_bytes'],
                            files=len(item['candidate_files']))
                item['sudo_gui'] = shutil.which('sudo-gui')
                if not item['sudo_gui']:
                    raise RuntimeError('sudo-gui is unavailable; administrator cleanup requires manual review')
                if not item['candidate_files']:
                    raise RuntimeError('No older package archives match the retention rule')
                if not item['scan_complete']:
                    item['reason'] = 'Native package candidates verified separately; inaccessible temporary download directories remain untouched.'
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                item.update(selectable=False, reason=str(error))
            item['refreshable'] = item['selectable']
        candidates.append(item)
    report = report_actions(candidates, selection=False) if candidates else dict(blocked={}, uninspected_processes=0)
    for item in candidates:
        if item['path'] in report['blocked']:
            item.update(selectable=False, reason=report['blocked'][item['path']])
        item['uninspected_processes'] = report['uninspected_processes']
    return sorted(candidates, key=lambda item: (item['selectable'], item['allocated_bytes']), reverse=True)


@contextmanager
def _profile_guard(profile):
    lock = str(profile) + '.lock'
    try:
        stale = _lock_owner(lock)
    except FileNotFoundError:
        stale = None
    if stale is not None:
        current = os.lstat(lock)
        if (current.st_dev, current.st_ino, current.st_mtime_ns) != (stale.st_dev, stale.st_ino, stale.st_mtime_ns):
            raise RuntimeError('Profile lock changed during acquisition')
        _lock_owner(lock)
        os.unlink(lock)
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    owned = os.fstat(descriptor)
    native = root = None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        root = projects._open_path(profile)
        native = os.open('.parentlock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root)
        if not stat.S_ISREG(os.fstat(native).st_mode):
            raise RuntimeError('Firefox native lock is not a regular file')
        fcntl.lockf(native, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        if native is not None:
            os.close(native)
        if root is not None:
            os.close(root)
        os.close(descriptor)
        current = os.lstat(lock)
        if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
            os.unlink(lock)


@contextmanager
def _install_guard(parent):
    descriptor = os.open(parent / 'install.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError('Codex installation lock is not a regular file')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _remove(item):
    if not getattr(shutil.rmtree, 'avoids_symlink_attacks', False):
        raise RuntimeError('Descriptor-safe recursive removal is unavailable')
    path = Path(item['path'])
    parent = projects._open_path(path.parent)
    root = holding = None
    holding_name = '.housekeeping-' + secrets.token_hex(12)
    created = False
    try:
        root = os.open(path.name, projects.FLAGS, dir_fd=parent)
        if {'device': os.fstat(root).st_dev, 'inode': os.fstat(root).st_ino} != item['identity']:
            raise RuntimeError('Application directory identity changed before removal')
        projects._git_check(path, root)
        os.mkdir(holding_name, 0o700, dir_fd=parent)
        created = True
        holding = os.open(holding_name, projects.FLAGS, dir_fd=parent)
        os.rename(path.name, 'selected', src_dir_fd=parent, dst_dir_fd=holding)
        moved = os.stat('selected', dir_fd=holding, follow_symlinks=False)
        if {'device': moved.st_dev, 'inode': moved.st_ino} != item['identity']:
            raise RuntimeError('Moved application directory does not match the approved identity')
        moved_path = str(path.parent / holding_name / 'selected')
        if any(mount == moved_path or mount.startswith(moved_path + '/') for mount in projects.mount_paths()):
            raise RuntimeError('Moved application directory contains a mount boundary')
        shutil.rmtree('selected', dir_fd=holding)
        os.close(holding)
        holding = None
        os.rmdir(holding_name, dir_fd=parent)
    except BaseException as error:
        if created:
            raise RuntimeError(f'Removal stopped; preserve holding directory {path.parent / holding_name}') from error
        raise
    finally:
        if holding is not None:
            os.close(holding)
        if root is not None:
            os.close(root)
        os.close(parent)


def execute(item):
    report = report_actions([item])
    if report['blocked']:
        raise RuntimeError(report['blocked'][item['path']])
    path = Path(item['path'])
    action = item['action']
    if action == 'pacman':
        current = pacman_preview(item, item['keep_versions'])
        if current['candidate_files'] != item['candidate_files']:
            raise RuntimeError('Pacman cache candidates changed; rerun the dry run')
        return subprocess.run([item['sudo_gui'], '--message', f'Prune pacman archives, keeping {item["keep_versions"]} versions per package.',
                               '--', 'sudo', current['executable'], '-r', '--nocolor', '-k', str(item['keep_versions']), '-c', item['path']],
                              text=True, capture_output=True, env={**os.environ, 'LC_ALL': 'C'})
    if action in {'web-cache', 'web-profile'}:
        with _profile_guard(Path(item['profile'])):
            if action == 'web-profile':
                _whole_profile_reason(path)
            _remove(item)
            if action == 'web-profile':
                os.unlink(str(path) + '.agency.json')
    elif action == 'codex-release':
        with _install_guard(path.parent.parent):
            _checked(item, projects.mount_paths())
            current = projects.inspect_processes([path], ignore_own_arguments=True)
            if current['blocked']:
                raise RuntimeError(current['blocked'][str(path)])
            _remove(item)
    elif action == 'thumbnails':
        _thumbnail_check(path)
        _remove(item)
    else:
        raise RuntimeError('Unsupported application cleanup action')
    return subprocess.CompletedProcess([], 0, f'Removed {path}\n', '')
