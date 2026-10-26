from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import urllib.parse

from agency_browser import BrowserError, Deferred, ServiceError
from agency_browser import _finite, origin


JOURNAL = '.agency-downloads.jsonl'
LOCK = '.agency-downloads.lock'
SCHEMA = 'agency/browser-downloads/1'
MAX_MANIFEST = 4 * 1024 * 1024
MAX_JOURNAL = 32 * 1024 * 1024
IDENTITY_FIELDS = ('id', 'path', 'filename', 'expected_size', 'resource')
STATUSES = {'downloading', 'downloaded', 'verified', 'failed', 'deferred', 'missing'}
HASH = re.compile(r'[0-9a-f]{64}\Z')


def _text(value):
    return isinstance(value, str) and bool(value) and not any(ord(c) < 32 for c in value)


def _path(value):
    return (_text(value) and len(value) <= 4096 and '\\' not in value
            and all(part not in ('', '.', '..') for part in value.split('/')))


def _basename(value):
    return _path(value) and '/' not in value and len(value.encode('utf-8')) <= 255


def validate_manifest(manifest):
    if (type(manifest) is not dict or set(manifest) != {'schema_version', 'allowed_origins', 'items'}
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or type(manifest['allowed_origins']) is not list or not 1 <= len(manifest['allowed_origins']) <= 32
            or type(manifest['items']) is not list or not 1 <= len(manifest['items']) <= 4096):
        raise BrowserError('Supply a version 1 manifest with allowed_origins and 1 to 4096 items.')
    allowed = set()
    for value in manifest['allowed_origins']:
        site = origin(value)
        parsed = urllib.parse.urlsplit(value)
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment or site in allowed:
            raise BrowserError('allowed_origins must contain distinct HTTP(S) origins without paths or queries.')
        allowed.add(site)
    items, ids, paths = [], set(), set()
    required = {'id', 'url', 'filename', 'expected_size', 'path'}
    for index, item in enumerate(manifest['items'], 1):
        if (type(item) is not dict or not required <= set(item) or set(item) - required - {'sha256'}
                or type(item['id']) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', item['id'])
                or item['id'] in ids or not _path(item['path']) or item['path'] in paths
                or item['path'].split('/')[0] in (JOURNAL, LOCK) or not _basename(item['filename'])
                or type(item['expected_size']) is not int or item['expected_size'] < 0
                or ('sha256' in item and (type(item['sha256']) is not str or not HASH.fullmatch(item['sha256'])))):
            raise BrowserError('Invalid or duplicate download manifest item ' + str(index) + '.')
        site = origin(item['url'])
        parsed = urllib.parse.urlsplit(item['url'])
        if site not in allowed or parsed.fragment:
            raise BrowserError('Download manifest item ' + str(index) + ' is outside its allowed origins.')
        # Bind resume records to the resource path while allowing signed query refreshes.
        items.append({**item, 'resource': site + parsed.path})
        ids.add(item['id']); paths.add(item['path'])
    for path in paths:
        if any('/'.join(path.split('/')[:i]) in paths for i in range(1, len(path.split('/')))):
            raise BrowserError('A manifest destination is also another destination\'s parent.')
    return items


def load_manifest(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise BrowserError('Download manifest exceeds 4 MiB.')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise BrowserError('Download manifest has duplicate JSON keys.')
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise BrowserError('Invalid download manifest JSON.') from None
    validate_manifest(result)
    return result


def plan_batch(manifest, destination):
    items = validate_manifest(manifest)
    return {'status': 'planned', 'complete': False, 'files': len(items),
            'expected_bytes': sum(item['expected_size'] for item in items),
            'destination': str(Path(destination).resolve())}


def _target(root, relative):
    path = root
    for part in relative.split('/'):
        path = path / part
        if path.is_symlink():
            raise BrowserError('A download destination or parent is a symlink.')
        if path.exists() and path != root / relative and not path.is_dir():
            raise BrowserError('A download destination parent is not a directory.')
    if path.exists() and not path.is_file():
        raise BrowserError('A download destination is not a regular file.')
    return path


def _private_descriptor(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_APPEND, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise BrowserError('Download state must be a private regular file owned by this user.')
    return fd


def _record(stream, value):
    raw = (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if os.fstat(stream.fileno()).st_size + len(raw) > MAX_JOURNAL:
        raise BrowserError('Download journal exceeds 32 MiB; retain it and start a new collection journal.')
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())


def _read_journal(stream):
    if os.fstat(stream.fileno()).st_size > MAX_JOURNAL:
        raise BrowserError('Download journal exceeds 32 MiB.')
    raw = stream.read(MAX_JOURNAL + 1)
    if not raw:
        _record(stream, {'schema': SCHEMA})
        return {}
    if not raw.endswith(b'\n'):
        raise BrowserError('Download journal has an incomplete final record; inspect it before resuming.')
    try:
        records = [json.loads(line) for line in raw.splitlines()]
    except (ValueError, UnicodeError, RecursionError):
        raise BrowserError('Invalid download journal; refusing to discard its receipts.') from None
    if records[0] != {'schema': SCHEMA}:
        raise BrowserError('Unsupported download journal schema.')
    latest = {}
    for row in records[1:]:
        if (type(row) is not dict or any(field not in row for field in IDENTITY_FIELDS)
                or not _text(row['id']) or not _path(row['path']) or not _basename(row['filename'])
                or type(row['expected_size']) is not int or row['expected_size'] < 0
                or not _text(row['resource']) or type(row.get('status')) is not str or row['status'] not in STATUSES
                or (row['status'] in ('downloaded', 'verified')
                    and (type(row.get('sha256')) is not str or not HASH.fullmatch(row['sha256'])
                         or type(row.get('bytes')) is not int or row['bytes'] != row['expected_size']))):
            raise BrowserError('Invalid download journal receipt.')
        previous = latest.get(row['id'])
        if previous and any(previous[field] != row[field] for field in IDENTITY_FIELDS):
            raise BrowserError('Download journal contains conflicting resource identities.')
        if row['status'] not in ('downloaded', 'verified'):
            row.pop('sha256', None)
            if previous and previous.get('sha256'):
                row['sha256'] = previous['sha256']
        latest[row['id']] = row
    return latest


@contextmanager
def _journal(root):
    with os.fdopen(_private_descriptor(root / LOCK), 'r+b') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Deferred('Another download batch for this collection is in progress.') from None
        with os.fdopen(_private_descriptor(root / JOURNAL), 'r+b') as stream:
            yield stream, _read_journal(stream)


def _verify(path, item, previous):
    if path.stat().st_size != item['expected_size']:
        return None, 'size_mismatch'
    known = item.get('sha256')
    receipt_hash = previous.get('sha256') if previous else None
    if not known and not receipt_hash:
        return None, 'existing_unverified'
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if (known and actual != known) or (receipt_hash and actual != receipt_hash):
        return None, 'checksum_mismatch'
    return actual, None


def download_batch(manifest, destination, transfer=None, verify_only=False, progress=None, retry_interrupted=False):
    items = validate_manifest(manifest)
    root = Path(destination).resolve()
    if verify_only and not root.is_dir():
        raise BrowserError('Offline verification requires an existing collection directory.')
    for item in items:
        _target(root, item['path'])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    summary = {'status': 'complete', 'complete': True, 'files': len(items),
               'expected_bytes': sum(item['expected_size'] for item in items), 'verified_bytes': 0,
               'downloaded': 0, 'verified': 0, 'pending': len(items), 'journal': str(root / JOURNAL)}
    with _journal(root) as (stream, latest):
        for item in items:
            previous = latest.get(item['id'])
            if previous and any(previous[field] != item[field] for field in IDENTITY_FIELDS):
                raise BrowserError('Manifest changes a recorded resource identity; use a new ID and destination for a new version.')
        for item in items:
            path = _target(root, item['path'])
            previous = latest.get(item['id'])
            base = {field: item[field] for field in IDENTITY_FIELDS}
            error = None
            if path.exists():
                actual, error = _verify(path, item, previous)
                receipt = {**base, 'status': 'verified', 'bytes': item['expected_size'], 'sha256': actual}
            elif verify_only:
                error = 'missing'
            elif previous and previous['status'] in ('downloading', 'failed', 'deferred') and not retry_interrupted:
                # A browser transfer may still finish after its caller stopped.
                error = 'inspect_transfer'
            else:
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                _target(root, item['path'])
                _record(stream, {**base, 'status': 'downloading'})
                try:
                    if transfer is None:
                        raise BrowserError('No authenticated download transport was supplied.')
                    outcome = transfer(item, path)
                    result = outcome.get('result') if type(outcome) is dict else None
                    if (type(result) is not dict or result.get('path') != str(path)
                            or type(result.get('bytes')) is not int or result['bytes'] != item['expected_size']
                            or type(result.get('sha256')) is not str or not HASH.fullmatch(result['sha256'])
                            or path.is_symlink() or not path.is_file() or path.stat().st_size != item['expected_size']
                            or not _finite(outcome.get('wait_seconds'), 0, 3600)):
                        error = 'invalid_receipt'
                    elif ((item.get('sha256') and item['sha256'] != result['sha256'])
                          or (previous and previous.get('sha256') and previous['sha256'] != result['sha256'])):
                        error = 'checksum_mismatch'
                    else:
                        path.chmod(0o600)
                        receipt = {**base, 'status': 'downloaded', 'bytes': result['bytes'],
                                   'sha256': result['sha256'], 'wait_seconds': outcome['wait_seconds']}
                except Deferred:
                    error = 'deferred'
                except ServiceError as failure:
                    error = 'http_' + str(failure.status) if type(failure.status) is int else 'service_error'
                except BrowserError:
                    error = 'browser_error'
                except OSError:
                    error = 'filesystem_error'
            if error:
                status = 'deferred' if error in ('deferred', 'inspect_transfer') else 'missing' if error == 'missing' else 'failed'
                # An offline check cannot prove that an interrupted browser transfer stopped.
                recorded_status = (previous['status'] if error == 'missing' and previous
                                   and previous['status'] in ('downloading', 'failed', 'deferred') else status)
                _record(stream, {**base, 'status': recorded_status, 'error_code': error})
                summary.update({'status': status, 'complete': False, 'error': {'id': item['id'], 'code': error}})
                return summary
            _record(stream, receipt)
            latest[item['id']] = receipt
            summary[receipt['status']] += 1
            summary['verified_bytes'] += item['expected_size']
            summary['pending'] -= 1
            if progress:
                progress({'id': item['id'], 'status': receipt['status'], 'bytes': item['expected_size']})
    return summary
