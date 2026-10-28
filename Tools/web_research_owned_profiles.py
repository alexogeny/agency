"""Exact, authorized task-profile lifecycle; JSON stdin/stdout, no browser launch."""
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time

import housekeeping_providers as housekeeping


class ProfileError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise ProfileError(code, message)


def plain_path(path):
    path = Path(path)
    for part in [path, *path.parents]:
        if part.is_symlink():
            fail('profile-identity-mismatch', 'Profile paths must not contain symlinks')
    return path


def authorization(request, execution):
    auth = request.get('authorization')
    if (not isinstance(auth, dict) or auth.get('disposable') is not True
            or auth.get('owner_execution') != execution
            or not isinstance(auth.get('reference'), str) or not 1 <= len(auth['reference']) <= 256):
        fail('cleanup-not-authorized', 'Explicit disposable authorization for this execution is required')
    return auth


def active_processes(profile):
    # Check exact Firefox argv even when an external launch omitted Agency's lock.
    proc = Path('/proc')
    if not proc.is_dir():
        fail('profile-inspection-unavailable', 'Exact task cleanup currently requires Linux process inspection; preserve the profile')
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = (entry / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except PermissionError:
            fail('profile-active', 'Cannot inspect an owned process; preserve the profile')
        if not args or b'firefox' not in os.path.basename(args[0]).lower():
            continue
        encoded = os.fsencode(profile)
        if encoded in args or b'--profile=' + encoded in args:
            fail('profile-active', 'Firefox still references the selected profile')


def create(request, data_root):
    execution = request.get('owner_execution')
    if (request.get('schema') != 'agency/owned-profile-request/1' or not isinstance(execution, str)
            or not 1 <= len(execution) <= 256 or request.get('mode') not in ('persistent', 'ephemeral')
            or not isinstance(request.get('purpose'), str) or not 1 <= len(request['purpose']) <= 256):
        fail('invalid-profile-request', 'Create requires schema, execution, bounded purpose and mode')
    auth = authorization(request, execution)
    if request['mode'] == 'ephemeral':
        fail('unsupported-profile-mode', 'Owned ephemeral profiles are unsupported; use persistent mode with explicit close and cleanup')
    parent = plain_path(data_root / 'profiles')
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = 'task-' + secrets.token_hex(16)
    root = parent / profile
    root.mkdir(mode=0o700)
    info = root.stat()
    now = time.time()
    handle = dict(schema='agency/owned-profile/1', profile=profile, nonce=secrets.token_hex(32),
                  metadata_id=secrets.token_hex(16), owner_execution=execution, canonical_path=str(root),
                  created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
                  mode=request['mode'], purpose=request['purpose'], authorization=auth,
                  filesystem_identity={'device': info.st_dev, 'inode': info.st_ino})
    metadata = dict(schema_version=1, owner='web-research', purpose=request['purpose'], pinned=True,
                    created_at=now, last_used_at=now, completed_at=None, owned_profile=handle)
    try:
        with open(str(root) + '.agency.json', 'x', encoding='utf-8') as output:
            os.chmod(output.name, 0o600)
            json.dump(metadata, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        root.rmdir()
        raise
    return handle


def cleanup_marker(handle):
    return {'schema': 'agency/owned-profile-cleanup/1', 'nonce': handle['nonce'],
            'metadata_id': handle['metadata_id'], 'filesystem_identity': handle['filesystem_identity']}


def mark_cleanup(root, handle):
    metadata = housekeeping.profile_metadata(root)
    metadata['cleanup_started'] = cleanup_marker(handle)
    target = Path(str(root) + '.agency.json')
    descriptor, name = tempfile.mkstemp(prefix='.profile-cleanup-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(metadata, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(name).unlink(missing_ok=True)


def selected(request, data_root, allow_missing=False):
    handle = request.get('handle')
    if not isinstance(handle, dict) or handle.get('schema') != 'agency/owned-profile/1':
        fail('profile-identity-mismatch', 'A complete owned-profile handle is required')
    execution = request.get('owner_execution')
    if execution != handle.get('owner_execution'):
        fail('profile-identity-mismatch', 'Execution identity does not match profile')
    auth = authorization(request, execution)
    if auth != handle.get('authorization'):
        fail('cleanup-not-authorized', 'Authorization does not match the recorded scope')
    name = handle.get('profile')
    if not isinstance(name, str) or not housekeeping.PROFILE_NAME.fullmatch(name) or not name.startswith('task-'):
        fail('profile-identity-mismatch', 'Unrecognized task profile name')
    root = plain_path(data_root / 'profiles' / name)
    exists = os.path.lexists(root)
    if str(root) != handle.get('canonical_path') or (exists and not root.is_dir()) or (not exists and not allow_missing):
        fail('profile-identity-mismatch', 'Exact canonical profile path is absent or mismatched')
    if exists:
        info = root.stat()
        if handle.get('filesystem_identity') != {'device': info.st_dev, 'inode': info.st_ino}:
            fail('profile-identity-mismatch', 'Profile directory identity has changed')
    plain_path(Path(str(root) + '.agency.json'))
    try:
        metadata = housekeeping.profile_metadata(root)
    except (OSError, RuntimeError, ValueError):
        fail('profile-identity-mismatch', 'Task lifecycle metadata is unavailable')
    if metadata.get('owned_profile') != handle:
        fail('profile-identity-mismatch', 'Profile nonce or lifecycle identity does not match')
    if exists and metadata.get('cleanup_started'):
        # A deleted inode can be reused immediately; equality cannot prove continuity.
        fail('profile-identity-mismatch', 'Cleanup already started; an existing directory requires manual review')
    if not exists and metadata.get('cleanup_started') != cleanup_marker(handle):
        fail('profile-identity-mismatch', 'Missing profile has no matching cleanup checkpoint')
    return root, handle


def operate(command, request, data_root):
    if command == 'profile-create':
        return create(request, data_root)
    recovering = command == 'profile-cleanup'
    root, handle = selected(request, data_root, allow_missing=recovering)
    if command == 'profile-validate':
        return {'validated': True}
    try:
        if root.is_dir():
            housekeeping._profile_check(root)
        with housekeeping._profile_guard(root, allow_missing=recovering, identity=handle['filesystem_identity']):
            # Revalidate under the same lock used by browser and housekeeping clients.
            current, _ = selected(request, data_root, allow_missing=recovering)
            if current != root:
                fail('profile-identity-mismatch', 'Selected profile changed')
            active_processes(root)
            if command == 'profile-close':
                return {'schema': 'agency/owned-profile-close/1', 'profile': handle['profile'],
                        'nonce': handle['nonce'], 'browser_released': True, 'closed': True,
                        'process_policy': 'tracked client lease closed before native/process release verification'}
            if root.is_dir():
                mark_cleanup(root, handle)
            receipt = dict(schema='agency/profile-cleanup-receipt/1', profile=handle['profile'],
                           nonce=handle['nonce'], owner_execution=handle['owner_execution'],
                           authorization=handle['authorization'], outcome='partial',
                           preconditions={'identity_matches': True, 'processes_clear': True, 'locks_held': True},
                           targets=[], postcheck={})
            targets = (root, Path(str(root) + '.agency.json'))
            for target in targets:
                try:
                    if target == root:
                        if not os.path.lexists(root):
                            receipt['targets'].append({'path': str(target), 'result': 'already-absent'})
                            continue
                        housekeeping._remove({'path': str(target), 'identity': handle['filesystem_identity']})
                    else:
                        if os.path.lexists(root):
                            fail('profile-identity-mismatch', 'Profile appeared during metadata-only cleanup')
                        target.unlink()
                    receipt['targets'].append({'path': str(target), 'result': 'removed'})
                except (OSError, RuntimeError) as exc:
                    receipt['targets'].append({'path': str(target), 'result': 'failed', 'detail': str(exc)})
                    break
            receipt['postcheck'] = {'profile_absent': not os.path.lexists(root),
                                    'metadata_absent': not os.path.lexists(targets[1])}
            if all(receipt['postcheck'].values()):
                receipt['outcome'] = 'removed'
            else:
                receipt['error'] = {'code': 'cleanup-partial', 'stage': 'cleanup', 'retriable': False,
                                    'next_action': 'Inspect the receipt targets; preserve remaining metadata for recovery'}
            return receipt
    except ProfileError:
        raise
    except (OSError, RuntimeError):
        fail('profile-active', 'Profile is locked, active, or cannot be safely inspected')


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            fail('invalid-profile-request', 'Profile request exceeds 65536 bytes')
        request = json.loads(raw)
        if not isinstance(request, dict):
            fail('invalid-profile-request', 'Profile request must be a JSON object')
        data_root = plain_path(Path(os.environ.get('WEB_RESEARCH_DATA_DIR', Path.home() / '.local/share/web-research')).absolute())
        result = operate(sys.argv[1], request, data_root)
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get('outcome') == 'partial' else 0
    except (ProfileError, OSError, ValueError) as error:
        print(json.dumps({'error': {'code': getattr(error, 'code', 'invalid-profile-request'),
            'message': str(error) if isinstance(error, ProfileError) else 'Profile operation failed safely',
            'stage': 'profile-lifecycle', 'retriable': False,
            'next_action': 'Inspect the selected owned handle and release its browser before retrying'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
