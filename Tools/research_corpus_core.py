"""Portable sanitized research records and recoverable manifest publication."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote
import uuid

SCHEMA = 'agency/research-corpus/1'
RECORD_SCHEMA = 'agency/research-record/1'
SANITIZER_VERSION = 'agency/export-sanitizer/1'
MAX_BYTES = 16 * 1024 * 1024
_LOCKS = threading.local()
_RUNTIME_IDENTITY = None
SECRET = re.compile(r'(?:token|secret|password|passwd|authorization|cookie|signature|credential|api.?key|access.?key|session|^auth$|^sig$|^key$|^policy$)', re.I)
URL = re.compile(r'https?://[^\s<>\"\]\[)]+', re.I)


class CorpusError(Exception):
    def __init__(self, code, message, stage='', retriable=False, next_action='', **details):
        super().__init__(message)
        self.code, self.stage, self.retriable = code, stage, retriable
        self.next_action, self.details = next_action, details

    def as_dict(self):
        return sanitize({'code': self.code, 'message': str(self), 'stage': self.stage,
                         'retriable': self.retriable, 'next_action': self.next_action, **self.details})


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def safe_path(root, relative):
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise CorpusError('unsafe-path', 'Expected a relative path within the corpus', 'filesystem')
    for part in [root, *root.parents]:
        if part.is_symlink():
            raise CorpusError('unsafe-path', 'Symlink paths are forbidden', 'filesystem')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise CorpusError('unsafe-path', 'Symlink paths are forbidden', 'filesystem')
    return current


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_bytes(path, data):
    path = Path(path)
    safe_path(path.parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path, value):
    _atomic_bytes(path, canonical_bytes(value))


@contextmanager
def corpus_lock(root):
    root = Path(root).absolute()
    lock = safe_path(root, '.lock')
    held = getattr(_LOCKS, 'held', {})
    if str(root) in held:
        yield
        return
    with lock.open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        held[str(root)] = stream
        _LOCKS.held = held
        try:
            yield
        finally:
            del held[str(root)]



def _json(path):
    try:
        if path.stat().st_size > MAX_BYTES * 4:
            raise CorpusError('response-too-large', 'JSON exceeds bounded input size', 'read')
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CorpusError('invalid-checkpoint', 'Cannot read valid corpus JSON', 'read') from exc


def read_manifest(root):
    result = _json(safe_path(root, 'manifest.json'))
    if result.get('schema') != SCHEMA:
        raise CorpusError('unsupported-version', 'Unsupported corpus schema', 'manifest')
    for key, expected in [('corpus_id', str), ('protocol', dict), ('active_run', str), ('runs', list), ('sources', dict), ('records', list)]:
        if not isinstance(result.get(key), expected):
            raise CorpusError('invalid-checkpoint', 'Manifest has invalid required field: ' + key, 'manifest')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', result['corpus_id']):
        raise CorpusError('invalid-checkpoint', 'Invalid corpus identity', 'manifest')
    return result


def committed_records(root):
    return read_manifest(root)['records']


def load_record(root, entry):
    for path, digest in entry['hashes'].items():
        file = safe_path(root, path)
        if not file.is_file() or sha256(file.read_bytes()) != digest:
            raise CorpusError('artifact-integrity', 'Artifact missing or hash mismatch', 'verify', artifact=path)
    record = _json(safe_path(root, entry['paths']['json']))
    if record.get('schema') != RECORD_SCHEMA or record.get('record_id') != entry['record_id']:
        raise CorpusError('unsupported-version', 'Invalid record schema or identity', 'verify')
    return record


def _sanitize_url(match):
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        host = parts.netloc.rsplit('@', 1)[-1]
        query = [(key, '[REDACTED]' if SECRET.search(key) else sanitize(value)) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
        return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ''))
    except ValueError:
        return '[REDACTED-URL]'


def sanitize(value):
    """Versioned independent recursive boundary, applied before any evidence write."""
    if isinstance(value, dict):
        return {str(key): '[REDACTED]' if SECRET.search(str(key)) or str(key).lower() in ['canonical_path', 'profilepath', 'profile_path', 'profile_root', 'browserprofile', 'browser_path', 'cache_path', 'index_path', 'storagestate', 'localstorage', 'sessionstorage'] else sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        for _ in range(6):
            previous = value
            value = re.sub(r'\\+u([0-9a-fA-F]{4})', lambda match: chr(int(match.group(1), 16)) if not 0xD800 <= int(match.group(1), 16) <= 0xDFFF else match.group(0), value)
            value = html.unescape(re.sub(r'\\+/', '/', value))
            if re.search(r'https?%3a', value, re.I):
                value = unquote(value)
            if previous == value:
                break
        value = URL.sub(_sanitize_url, value)
        return re.sub(r'(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[REDACTED]', value)
    return value


def _changed_fields(original, clean):
    if isinstance(original, dict) and isinstance(clean, dict):
        return sum(_changed_fields(value, clean.get(str(key))) for key, value in original.items())
    if isinstance(original, list) and isinstance(clean, list):
        return sum(_changed_fields(a, b) for a, b in zip(original, clean))
    return int(original != clean)


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _version_identity(name):
    executable = shutil.which(name)
    if not executable:
        return {'status': 'unavailable', 'reason': 'executable not found; no browser launched'}
    try:
        process = subprocess.Popen([executable, '--version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        data = bytearray()
        deadline = time.monotonic() + 2
        while selector.get_map() and time.monotonic() < deadline and len(data) < 4096:
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), min(1024, 4096 - len(data)))
                if chunk:
                    data.extend(chunk)
                else:
                    selector.unregister(key.fileobj)
        if not selector.get_map():
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
        selector.close()
        process.stdout.close()
        return {'status': 'observed' if data else 'unavailable', 'version': sanitize(data.decode(errors='replace').strip()), 'exit_code': process.returncode, 'scope': 'version command only; browser not launched'}
    except (OSError, subprocess.SubprocessError):
        return {'status': 'unavailable', 'reason': 'version command failed; browser not launched'}


def _runtime_identity():
    global _RUNTIME_IDENTITY
    if _RUNTIME_IDENTITY is None:
        _RUNTIME_IDENTITY = {'python': sys.version, 'platform': sys.platform, 'minimum_offline_python': '3.10',
                             'bun': _version_identity('bun'), 'firefox': _version_identity('firefox')}
    return _RUNTIME_IDENTITY


def _snapshot(root):
    tools = Path(__file__).resolve().parent
    names = ['research_corpus_core.py', 'research_corpus_reproduce.py', 'research_corpus_services.py', 'research_corpus_process.py', 'research-corpus', 'web-research', 'web-research-mcp', 'web_research_evidence.ts', 'web_research_owned_profiles.py', 'housekeeping_providers.py', 'housekeeping_projects.py']
    files = {name: (tools / name).read_bytes() for name in names if (tools / name).is_file()}
    runtime = _runtime_identity()
    digest = sha256(canonical_bytes({'hashes': {name: sha256(data) for name, data in files.items()}, 'runtime': runtime}))
    relative = 'software/' + digest
    target = safe_path(root, relative)
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, data in files.items():
        file = safe_path(target, name)
        if file.exists() and file.read_bytes() != data:
            raise CorpusError('software-integrity', 'Software snapshot collision', 'snapshot')
        if not file.exists():
            _atomic_bytes(file, data)
        hashes[name] = sha256(data)
    identity = {'schema': 'agency/research-software/1', 'path': relative, 'hashes': hashes,
                'runtime': runtime, 'dependencies': 'Python standard library for offline processing',
                'source_identity': 'actual working files including uncommitted modifications'}
    if (target / 'software.json').exists():
        if _json(target / 'software.json') != identity:
            raise CorpusError('software-integrity', 'Software identity is immutable', 'snapshot')
    else:
        atomic_json(target / 'software.json', identity)
    return identity


def init_corpus(root, protocol):
    root = Path(root).absolute()
    if root.exists():
        raise CorpusError('output-exists', 'Corpus output already exists', 'init')
    value = _json(Path(protocol))
    if not isinstance(value, dict) or not value:
        raise CorpusError('invalid-protocol', 'Protocol must be a nonempty JSON object', 'init')
    budgets = value.get('budgets', value.get('budget', {}))
    if not isinstance(budgets, dict) or ('budget' in value and 'budgets' in value and value['budget'] != value['budgets']):
        raise CorpusError('invalid-protocol', 'Declare one consistent query/source budget object', 'init')
    value = {**value, 'budgets': budgets}
    for name, limit in budgets.items():
        if name in ['queries', 'sources'] and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise CorpusError('invalid-protocol', 'Query/source budgets must be positive integers', 'init')
    safe_path(root.parent, root.name)
    root.mkdir(mode=0o700)
    software = _snapshot(root)
    run_id = 'run-' + uuid.uuid4().hex
    manifest = {'schema': SCHEMA, 'corpus_id': 'corpus-' + uuid.uuid4().hex, 'created_at': _now(),
                'protocol': sanitize(value), 'active_run': run_id,
                'runs': [{'run_id': run_id, 'created_at': _now(), 'recipe': {'schema': 'agency/research-recipe/1', 'queries': [], 'selections': [], 'stopping_decisions': [{'kind': 'declared', 'rule': sanitize(value.get('stopping_rule')), 'budgets': value.get('budgets', {}), 'interpretation': 'Query/source ceilings enforced; narrative rule requires explicit researcher judgment'}], 'unsupported_controls': ['locale', 'date-window', 'provider-order', 'per-provider-budget']}, 'software': software}],
                'sources': {}, 'records': [], 'operations': {}, 'redaction_policy': SANITIZER_VERSION}
    atomic_json(root / 'manifest.json', manifest)
    return {'corpus_id': manifest['corpus_id'], 'run_id': run_id, 'status': 'initialized'}


def run_backend(arguments, request=None):
    previous = {}
    def cancelled(signum, frame):
        raise CorpusError('operation-cancelled', 'Owned backend operation was cancelled', 'backend',
                          process={'exit_code': None, 'cancelled': True, 'browser_released': None})
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, cancelled)
    try:
        return _run_backend(arguments, request)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _run_backend(arguments, request=None):
    command = os.environ.get('RESEARCH_CORPUS_WEB_COMMAND', str(Path(__file__).resolve().with_name('web-research')))
    if not Path(command).is_file():
        raise CorpusError('backend-unavailable', 'Backend executable is unavailable', 'backend')
    lifetime, owner = os.pipe()
    supervisor = str(Path(__file__).resolve().with_name('research_corpus_process.py'))
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', supervisor, str(lifetime), '--', command, *arguments],
                                   pass_fds=(lifetime,), stdin=subprocess.PIPE if request is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    except BaseException:
        os.close(owner)
        raise
    finally:
        os.close(lifetime)
    selector = selectors.DefaultSelector()
    outputs = {process.stdout: bytearray(), process.stderr: bytearray()}
    deadline, timed_out, exceeded = time.monotonic() + 120, False, False
    try:
        if request is not None:
            process.stdin.write(canonical_bytes(request))
            process.stdin.close()
        for stream in [process.stdout, process.stderr]:
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            if time.monotonic() > deadline:
                timed_out = True
                break
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                outputs[key.fileobj].extend(chunk)
                if sum(len(item) for item in outputs.values()) > MAX_BYTES:
                    exceeded = True
                    break
            if exceeded:
                break
        if timed_out or exceeded:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
    finally:
        os.close(owner)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        selector.close()
        if process.stdin is not None:
            process.stdin.close()
        process.stdout.close()
        process.stderr.close()
    state = {'exit_code': process.returncode, 'timed_out': timed_out, 'output_limit_exceeded': exceeded,
             'browser_released': None if process.returncode == 0 else False}
    try:
        payload = json.loads(outputs[process.stdout])
    except (ValueError, UnicodeError):
        raise CorpusError('backend-invalid-json', 'Backend returned no complete bounded evidence JSON', 'backend', retriable=False, process=state) from None
    return payload, state


def _crash(stage):
    if os.environ.get('RESEARCH_CORPUS_CRASH_AT') == stage:
        raise CorpusError('export-interrupted', 'Injected export interruption', stage, True, 'Run resume')


def _source_id(url):
    return 'source-' + sha256(url.encode())[:24]


def _run(manifest):
    return next(run for run in manifest['runs'] if run['run_id'] == manifest['active_run'])


def _make_record(manifest, kind, payload, process, source_id=None, url='', record_id=None, created_at=None):
    original_payload = payload
    payload = sanitize(payload)
    changed_fields = _changed_fields(original_payload, payload)
    if not isinstance(payload, dict):
        raise CorpusError('backend-invalid-json', 'Backend evidence must be an object', 'backend')
    text = payload.get('text') or payload.get('content') or ''
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, sort_keys=True)
    if kind == 'discovery':
        text = '\n'.join(str(item.get('title', '')) + '\n' + str(item.get('url', '')) + '\n' + str(item.get('snippet', '')) for item in payload.get('results', []) if isinstance(item, dict)) or json.dumps(payload, ensure_ascii=False, sort_keys=True)
    extraction = payload.get('extraction', {})
    if not isinstance(extraction, dict):
        extraction = {}
    truncated = payload.get('truncated', {})
    truncated_fields = [key for key, value in truncated.items() if value] if isinstance(truncated, dict) else []
    extraction = {'coverage': 'unknown', 'truncated_fields': truncated_fields,
                  'quality_observations': payload.get('quality', []),
                  'limitations': ['Coverage is limited to retained backend evidence'], **extraction}
    freshness = payload.get('freshness', {})
    if not isinstance(freshness, dict):
        freshness = {}
    retrieval_metadata = payload.get('retrieval', {})
    if not isinstance(retrieval_metadata, dict):
        retrieval_metadata = {}
    access = payload.get('access', {})
    access = access.get('state', 'unknown') if isinstance(access, dict) else access
    retrieval = {'mode': freshness.get('retrieval', 'unknown'), 'access': access,
                 'freshness': freshness, **retrieval_metadata}
    return {'schema': RECORD_SCHEMA, 'record_id': record_id or 'record-' + uuid.uuid4().hex,
            'kind': kind, 'run_id': manifest['active_run'], 'source_id': source_id, 'created_at': created_at or _now(),
            'title': payload.get('title', ''), 'url': sanitize(url or payload.get('url', '')), 'payload': payload,
            'text': text, 'markdown': payload.get('markdown') or text,
            'retrieval': retrieval, 'extraction': extraction,
            'delivery': {'citation_metadata_present': bool(url or payload.get('url')), 'evidence_text_present': bool(text), 'transport_truncated': bool(payload.get('transport_truncated', False)), 'extract_truncated': bool(extraction.get('truncated_fields'))},
            'bibliography': {'raw': payload.get('metadata', {}), 'raw_date': payload.get('published'), 'extracted_byline': payload.get('byline'), 'field_provenance': payload.get('provenance', {}), 'verified_authors': None, 'verified_year': None, 'verification_status': 'pending'},
            'process': process, 'transformations': [{'kind': 'recursive-export-sanitization', 'version': SANITIZER_VERSION, 'changed_fields': changed_fields}],
            'identities': {'sanitized_body_sha256': sha256(text.encode('utf-8')),
                           'byte_scope': 'UTF-8 retained body without header',
                           'source_evidence_sha256': freshness.get('content_sha256'),
                           'source_evidence_scope': 'Backend extracted markdown or text; opaque upstream identity, not raw HTTP bytes',
                           'upstream_evidence': payload.get('evidenceHash')}}


def _publish(root, pending):
    record = pending['record']
    base = 'records/' + record['record_id']
    stage = safe_path(root, 'pending/bundle')
    stage.mkdir(parents=True, exist_ok=True)
    paths = {'json': base + '/record.json', 'text': base + '/record.txt', 'markdown': base + '/record.md'}
    data = {'json': canonical_bytes(record), 'text': (record['text'] + '\n').encode(), 'markdown': (record['markdown'] + '\n').encode()}
    for kind in ['json', 'text', 'markdown']:
        _atomic_bytes(stage / Path(paths[kind]).name, data[kind])
        _crash(kind)
    destination = safe_path(root, base)
    destination.parent.mkdir(exist_ok=True)
    if destination.exists():
        for kind, path in paths.items():
            if safe_path(root, path).read_bytes() != data[kind]:
                raise CorpusError('artifact-integrity', 'Existing immutable bundle differs from checkpoint', 'publish')
        shutil.rmtree(stage)
    else:
        os.rename(stage, destination)
        _fsync_dir(destination.parent)
    _crash('rename')
    manifest = read_manifest(root)
    entry = {'record_id': record['record_id'], 'kind': record['kind'], 'run_id': record['run_id'], 'source_id': record['source_id'], 'paths': paths, 'hashes': {paths[kind]: sha256(content) for kind, content in data.items()}}
    if not any(item['record_id'] == record['record_id'] for item in manifest['records']):
        manifest['records'].append(entry)
        for sid, source in pending.get('sources', {}).items():
            if sid in manifest['sources'] and manifest['sources'][sid]['url'] != source['url']:
                raise CorpusError('source-identity-mismatch', 'Source identity already belongs to another URL', 'publish')
            old_aliases = manifest['sources'].get(sid, {}).get('aliases', [])
            manifest['sources'][sid] = {**source, 'aliases': sorted(set(old_aliases + source.get('aliases', [])))}
        if pending.get('operation_key'):
            manifest['operations'][pending['operation_key']] = {'record_id': record['record_id'], 'request_hash': pending['request_hash']}
        run = next(run for run in manifest['runs'] if run['run_id'] == record['run_id'])
        if pending.get('recipe'):
            run['recipe']['queries'].append(pending['recipe'])
        if record['source_id']:
            run['recipe']['selections'].append({'source_id': record['source_id'], 'url': record['url'], 'record_id': record['record_id']})
        _crash('before-manifest')
        atomic_json(safe_path(root, 'manifest.json'), manifest)
    _crash('manifest')
    journal = safe_path(root, 'journal/' + record['record_id'] + '.json')
    if not journal.exists():
        atomic_json(journal, {'schema': 'agency/research-checkpoint/1', 'entry': entry, 'operation_key': pending.get('operation_key'), 'committed_at': record['created_at']})
    request_path = safe_path(root, 'pending/request.json')
    if request_path.exists():
        request_path.unlink()
    safe_path(root, 'pending/result.json').unlink()
    _fsync_dir(safe_path(root, 'pending'))
    return {'record_id': record['record_id'], 'source_ids': sorted(pending.get('sources', {})), 'status': 'committed' if record['process'].get('exit_code') == 0 and not record['process'].get('evidence_error') else 'evidence-retained-process-failed', 'artifacts': paths, 'process': record['process']}


def _pending(root):
    return safe_path(root, 'pending/result.json')


def resume(root):
    with corpus_lock(root):
        manifest = read_manifest(root)
        if not _pending(root).exists() and safe_path(root, 'pending/request.json').exists():
            intent = _json(safe_path(root, 'pending/request.json'))
            if intent.get('schema') != 'agency/research-intent/1':
                raise CorpusError('invalid-checkpoint', 'Unsupported request intent schema', 'resume')
            record = _make_record(manifest, intent['kind'], {'outcome': 'interrupted-unknown', 'limitations': ['Backend outcome was not durably retained; no research coverage established']}, {'exit_code': None, 'browser_released': None, 'interrupted': True}, intent.get('source_id'), intent.get('url', ''), created_at=intent['created_at'])
            record['software'] = intent['software']
            pending = {'schema': 'agency/research-pending/1', 'record': record, 'sources': intent.get('sources', {}), 'operation_key': intent.get('operation_key'), 'request_hash': intent.get('request_hash'), 'recipe': intent.get('recipe')}
            atomic_json(_pending(root), pending)
        if not _pending(root).exists():
            for entry in manifest['records']:
                load_record(root, entry)
            return {'status': 'consistent', 'records': []}
        pending = _json(_pending(root))
        if pending.get('schema') != 'agency/research-pending/1':
            raise CorpusError('invalid-checkpoint', 'Unsupported pending checkpoint', 'resume')
        result = _publish(root, pending)
        return {'status': result['status'], 'records': [result['record_id']]}


def _ensure_running(manifest):
    if any(item.get('kind') == 'manual-stop' for item in _run(manifest)['recipe']['stopping_decisions']):
        raise CorpusError('run-stopped', 'Active run has an explicit stopping decision', 'stopping', next_action='Inspect retained results or create a linked rerun')


def stop(root, reason):
    if not reason.strip() or len(reason) > 4000:
        raise CorpusError('invalid-options', 'Stopping reason must contain 1..4000 characters', 'stopping')
    with corpus_lock(root):
        manifest = read_manifest(root)
        if _pending(root).exists() or safe_path(root, 'pending/request.json').exists():
            raise CorpusError('export-pending', 'Resume pending export before stopping the run', 'stopping')
        run = _run(manifest)
        previous = next((item for item in run['recipe']['stopping_decisions'] if item.get('kind') == 'manual-stop'), None)
        if previous is None:
            records = [entry['record_id'] for entry in manifest['records'] if entry['run_id'] == run['run_id']]
            previous = {'kind': 'manual-stop', 'reason': sanitize(reason), 'at': _now(), 'record_ids': records,
                        'declared_rule': manifest['protocol'].get('stopping_rule')}
            run['recipe']['stopping_decisions'].append(previous)
            atomic_json(safe_path(root, 'manifest.json'), manifest)
        return {'status': 'stopped', 'run_id': run['run_id'], 'decision': previous}


def _backend_identity():
    command = Path(os.environ.get('RESEARCH_CORPUS_WEB_COMMAND', str(Path(__file__).resolve().with_name('web-research'))))
    if not command.is_file():
        return {'status': 'unavailable'}
    hasher = hashlib.sha256()
    with command.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            hasher.update(chunk)
    return {'name': command.name, 'sha256': hasher.hexdigest(), 'scope': 'actual executable source bytes; runtime identity recorded in software snapshot'}


def _enforce_budget(root, manifest, category):
    limit = manifest['protocol'].get('budgets', {}).get(category)
    if limit is None:
        return
    kind = 'discovery' if category == 'queries' else 'source'
    count = sum(entry['run_id'] == manifest['active_run'] and entry['kind'] == kind for entry in manifest['records'])
    if count >= limit:
        decisions = _run(manifest)['recipe']['stopping_decisions']
        if not any(item.get('kind') == 'budget-exhausted' and item.get('category') == category for item in decisions):
            decisions.append({'kind': 'budget-exhausted', 'category': category, 'limit': limit, 'observed_attempts': count, 'at': _now()})
            atomic_json(safe_path(root, 'manifest.json'), manifest)
        raise CorpusError('budget-exhausted', 'Declared ' + category + ' attempt budget exhausted', 'budget', next_action='Review retained results and declared stopping rule')


def discover(root, query, profile, operation_id, strategy='federated', limit=8, domains=None, excluded_domains=None, engine='auto', **options):
    if options:
        raise CorpusError('unsupported-control', 'Requested provider controls are unsupported: ' + ', '.join(sorted(options)), 'recipe')
    if strategy not in ['first', 'federated'] or not 1 <= limit <= 50:
        raise CorpusError('invalid-options', 'Unsupported strategy or limit outside 1..50', 'recipe')
    if not query.strip() or len(query) > 1000 or query.startswith('-'):
        raise CorpusError('invalid-options', 'Search query must contain 1..1000 characters and not begin with a dash', 'recipe')
    if engine not in ['auto', 'duckduckgo', 'brave', 'bing'] or strategy == 'federated' and engine != 'auto':
        raise CorpusError('unsupported-control', 'Unsupported engine/strategy combination', 'recipe')
    domains, excluded_domains = list(domains or []), list(excluded_domains or [])
    for domain in [*domains, *excluded_domains]:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', domain) or '..' in domain:
            raise CorpusError('invalid-options', 'Domain filters require hostnames', 'recipe')
    request = sanitize({'query': query, 'strategy': strategy, 'limit': limit, 'profile_context': 'named-profile-state-not-retained', 'domains': domains, 'excluded_domains': excluded_domains, 'engine': engine})
    digest = sha256(canonical_bytes(request))
    with corpus_lock(root):
        manifest = read_manifest(root)
        key = manifest['active_run'] + ':' + operation_id
        if key in manifest['operations']:
            operation = manifest['operations'][key]
            if operation['request_hash'] != digest:
                raise CorpusError('operation-conflict', 'Operation ID belongs to a different request', 'discover')
            entry = next(item for item in manifest['records'] if item['record_id'] == operation['record_id'])
            retained = load_record(root, entry)
            state = retained['process']
            return {'record_id': entry['record_id'], 'status': 'already-committed' if state.get('exit_code') == 0 and not state.get('evidence_error') else 'evidence-retained-process-failed', 'artifacts': entry['paths'], 'process': state}
        if _pending(root).exists() or safe_path(root, 'pending/request.json').exists():
            raise CorpusError('export-pending', 'Commit retained discovery before another search', 'discover', True, 'Run resume')
        _ensure_running(manifest)
        _enforce_budget(root, manifest, 'queries')
        software = _snapshot(root)
        started_at = _now()
        intent = {'schema': 'agency/research-intent/1', 'kind': 'discovery', 'created_at': started_at,
                  'operation_key': key, 'request_hash': digest, 'software': software,
                  'recipe': {**request, 'operation_id': operation_id, 'exact_query': sanitize(query), 'effective_query': None, 'attempts': [], 'omissions': ['Process interrupted before result checkpoint'], 'absolute_date_window': manifest['protocol'].get('date_window')}}
        atomic_json(safe_path(root, 'pending/request.json'), intent)
        _crash('intent')
        arguments = ['search', query, '--strategy', strategy, '--limit', str(limit), '--json', '--profile', profile, '--engine', engine]
        for domain in domains:
            arguments.extend(['--domain', domain])
        for domain in excluded_domains:
            arguments.extend(['--exclude-domain', domain])
        try:
            payload, process = run_backend(arguments)
        except CorpusError as exc:
            payload, process = {'outcome': exc.code, 'error': exc.as_dict()}, exc.details.get('process', {'exit_code': None, 'browser_released': None})
        record = _make_record(manifest, 'discovery', payload, process, created_at=started_at)
        record['software'] = software
        if payload.get('outcome') in ['backend-invalid-json', 'backend-unavailable']:
            record['process']['evidence_error'] = payload['outcome']
        sources = {}
        for hit in payload.get('results', []):
            if isinstance(hit, dict) and isinstance(hit.get('url'), str):
                url = sanitize(hit['url'])
                sources[_source_id(url)] = {'url': url, 'aliases': [url]}
        recipe = {**request, 'operation_id': operation_id, 'exact_query': sanitize(query), 'effective_query': sanitize(payload.get('query', query)), 'started_at': record['created_at'], 'attempts': payload.get('attempts', []), 'omissions': payload.get('omissions', []), 'absolute_date_window': manifest['protocol'].get('date_window'), 'date_window_enforcement': 'unsupported-backend-control-declared-scope-only', 'locale': 'backend-default-uncontrolled', 'provider_order': payload.get('providers', 'backend-default'), 'access_context': 'named-profile state not retained; authentication/access not assumed', 'argv': sanitize(arguments), 'budgets': {'subprocess_timeout_seconds': 120, 'combined_output_bytes': MAX_BYTES, 'result_limit': limit, 'provider_deadlines': 'backend-default-uncontrolled'}, 'backend_identity': _backend_identity()}
        pending = {'schema': 'agency/research-pending/1', 'record': record, 'sources': sources, 'operation_key': key, 'request_hash': digest, 'recipe': sanitize(recipe)}
        atomic_json(_pending(root), pending)
        _crash('checkpoint')
        return _publish(root, pending)


def open_source(root, source_id, url=None, profile=None, from_index=False, force_live=False):
    if from_index and force_live:
        raise CorpusError('invalid-options', 'Index-only export cannot request a live refresh', 'open')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', source_id):
        raise CorpusError('invalid-source-id', 'Source ID must be a short opaque identifier', 'open')
    with corpus_lock(root):
        manifest = read_manifest(root)
        if _pending(root).exists() or safe_path(root, 'pending/request.json').exists():
            raise CorpusError('export-pending', 'Resume pending export first', 'open', True, 'Run resume')
        existing = manifest['sources'].get(source_id)
        url = url or (existing or {}).get('url')
        if not url:
            raise CorpusError('unknown-source', 'Source URL is unknown', 'open')
        if urlsplit(url).scheme not in ['http', 'https'] or not urlsplit(url).netloc:
            raise CorpusError('invalid-url', 'Source URL must use HTTP or HTTPS', 'open')
        clean_url = sanitize(url)
        if existing and existing['url'] != clean_url:
            raise CorpusError('source-identity-mismatch', 'Source ID already belongs to another URL', 'open')
        arguments = ['scrape', url, '--format', 'json']
        if from_index:
            arguments.append('--from-index')
        else:
            if not profile:
                raise CorpusError('profile-required', 'Live source opening requires an explicit task profile', 'open')
            arguments.extend(['--index' if force_live else '--preflight', '--profile', profile])
        if not from_index:
            _ensure_running(manifest)
        _enforce_budget(root, manifest, 'sources')
        software = _snapshot(root)
        started_at = _now()
        atomic_json(safe_path(root, 'pending/request.json'), {'schema': 'agency/research-intent/1', 'kind': 'source', 'source_id': source_id, 'url': clean_url, 'created_at': started_at, 'software': software, 'sources': {source_id: {'url': clean_url, 'aliases': [clean_url]}}})
        _crash('intent')
        try:
            payload, process = run_backend(arguments)
        except CorpusError as exc:
            payload, process = {'outcome': exc.code, 'error': exc.as_dict()}, exc.details.get('process', {'exit_code': None, 'browser_released': None})
        record = _make_record(manifest, 'source', payload, process, source_id, clean_url, created_at=started_at)
        record['software'] = software
        if payload.get('outcome') in ['backend-invalid-json', 'backend-unavailable']:
            record['process']['evidence_error'] = payload['outcome']
        pending = {'schema': 'agency/research-pending/1', 'record': record, 'sources': {source_id: {'url': clean_url, 'aliases': sorted(set([clean_url, sanitize(str(payload.get('url', clean_url))), sanitize(str(payload.get('canonicalUrl', clean_url)))]))}}}
        atomic_json(_pending(root), pending)
        return _publish(root, pending)


def retain(root, file, kind, operation_id, format='text'):
    if kind not in ['protocol', 'screening', 'synthesis'] or format not in ['text', 'markdown']:
        raise CorpusError('invalid-options', 'Unsupported retained document kind or format', 'retain')
    file = Path(file).absolute()
    safe_path(file.parent, file.name)
    if not file.is_file() or file.stat().st_size > MAX_BYTES:
        raise CorpusError('invalid-input', 'Retained input must be a bounded regular UTF-8 file', 'retain')
    try:
        content = file.read_text(encoding='utf-8', errors='strict')
    except UnicodeError as exc:
        raise CorpusError('invalid-utf8', 'Retained document must contain valid UTF-8', 'retain') from exc
    if not content.strip() or '\x00' in content:
        raise CorpusError('empty-selection', 'Retained document must contain nonempty text', 'retain')
    payload = {'title': file.name, 'text': content, 'markdown': content, 'retained_format': format,
               'retrieval': {'mode': 'local-retained-document', 'access': 'local'},
               'extraction': {'coverage': 'unknown', 'limitations': ['Locally retained ' + kind + '; not opened source evidence']}}
    digest = sha256(canonical_bytes(sanitize({'kind': kind, 'content': content, 'format': format})))
    with corpus_lock(root):
        manifest = read_manifest(root)
        key = manifest['active_run'] + ':' + operation_id
        if key in manifest['operations']:
            operation = manifest['operations'][key]
            if operation['request_hash'] != digest:
                raise CorpusError('operation-conflict', 'Operation ID belongs to a different retained document', 'retain')
            entry = next(entry for entry in manifest['records'] if entry['record_id'] == operation['record_id'])
            retained = load_record(root, entry)
            state = retained['process']
            return {'record_id': entry['record_id'], 'status': 'already-committed' if state.get('exit_code') == 0 and not state.get('evidence_error') else 'evidence-retained-process-failed', 'artifacts': entry['paths'], 'process': state}
        if _pending(root).exists() or safe_path(root, 'pending/request.json').exists():
            raise CorpusError('export-pending', 'Resume pending result before retaining a document', 'retain')
        record = _make_record(manifest, kind, payload, {'exit_code': 0, 'browser_released': None, 'operation': 'offline-retain'})
        record['software'] = _snapshot(root)
        pending = {'schema': 'agency/research-pending/1', 'record': record, 'operation_key': key, 'request_hash': digest}
        atomic_json(_pending(root), pending)
        return _publish(root, pending)


def _profile_state(root):
    corpus_id = read_manifest(root)['corpus_id']
    private = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'agency/research-corpus'
    safe_path(private.parent, private.name)
    private.mkdir(parents=True, mode=0o700, exist_ok=True)
    return safe_path(private, corpus_id + '.json')


def profiles(root, action, owner_execution='', purpose='', authorization=None, receipt=None, mode='persistent'):
    with corpus_lock(root):
        path = _profile_state(root)
        if action == 'cleanup' and receipt:
            receipt_path = Path(receipt).absolute()
            safe_path(receipt_path.parent, receipt_path.name)
            corpus_root = Path(root).absolute()
            if corpus_root == receipt_path or corpus_root in receipt_path.parents:
                raise CorpusError('unsafe-path', 'Private cleanup receipt must remain outside corpus', 'profile')
            if receipt_path.exists():
                raise CorpusError('output-exists', 'Receipt output already exists', 'profile')
        if action != 'handles' and not owner_execution:
            raise CorpusError('owner-required', 'Profile mutation requires owner execution', 'profile')
        if action == 'handles':
            if not path.exists():
                raise CorpusError('profile-identity-mismatch', 'No private owned profile handle', 'profile')
            handle = _json(path)
            if not owner_execution or handle.get('owner_execution') != owner_execution:
                raise CorpusError('profile-owner-mismatch', 'Owner execution does not match private profile handle', 'profile')
            if not authorization or authorization != handle.get('authorization'):
                raise CorpusError('cleanup-not-authorized', 'Authorization does not match private profile scope', 'profile')
            return {'requests': [{'handle': handle, 'owner_execution': handle['owner_execution'], 'authorization': handle['authorization']}]}
        if action == 'create':
            if path.exists():
                raise CorpusError('profile-conflict', 'Corpus already has an owned profile handle', 'profile')
            request = {'schema': 'agency/owned-profile-request/1', 'owner_execution': owner_execution, 'purpose': purpose, 'mode': mode, 'authorization': authorization}
        else:
            if not path.exists():
                raise CorpusError('profile-identity-mismatch', 'No private owned profile handle', 'profile')
            request = {'handle': _json(path), 'owner_execution': owner_execution, 'authorization': authorization}
        result, state = run_backend(['profile-' + action], request)
        if action == 'cleanup' and receipt:
            target = Path(receipt)
            if target.exists():
                raise CorpusError('output-exists', 'Receipt output already exists', 'profile')
            atomic_json(target, sanitize(result))
        if state['exit_code']:
            error = result.get('error', result)
            raise CorpusError(error.get('code', 'profile-failed'), error.get('message', 'Profile operation failed'), 'profile', error.get('retriable', False), error.get('next_action', ''))
        if action == 'create':
            atomic_json(path, result)
            os.chmod(path, 0o600)
        elif action == 'cleanup' and result.get('outcome') == 'removed':
            if result.get('postcheck') != {'profile_absent': True, 'metadata_absent': True}:
                raise CorpusError('cleanup-partial', 'Profile removal lacks a complete absence check', 'profile')
            path.unlink()
            _fsync_dir(path.parent)
        return sanitize({key: value for key, value in result.items() if key not in ['canonical_path', 'handle', 'authorization']})


def rerun(root, from_run, profile):
    with corpus_lock(root):
        manifest = read_manifest(root)
        if _pending(root).exists() or safe_path(root, 'pending/request.json').exists():
            raise CorpusError('export-pending', 'Resume pending export before rerun', 'rerun')
        old = next((run for run in manifest['runs'] if run['run_id'] == from_run), None)
        if old is None:
            raise CorpusError('unknown-run', 'Unknown original run', 'rerun')
        new = {'run_id': 'run-' + uuid.uuid4().hex, 'parent_run': from_run, 'created_at': _now(), 'software': _snapshot(root), 'recipe': {**old['recipe'], 'queries': [], 'selections': [], 'stopping_decisions': [item for item in old['recipe']['stopping_decisions'] if item.get('kind') == 'declared'] + [{'kind': 'rerun-started', 'parent_run': from_run, 'at': _now()}]}}
        manifest['runs'].append(new)
        manifest['active_run'] = new['run_id']
        atomic_json(safe_path(root, 'manifest.json'), manifest)
        records = []
        for query in old['recipe']['queries']:
            records.append(discover(root, query['exact_query'], profile, query['operation_id'], query['strategy'], query['limit'], query.get('domains'), query.get('excluded_domains'), query.get('engine', 'auto')))
        for selection in old['recipe']['selections']:
            records.append(open_source(root, selection['source_id'], selection['url'], profile, force_live=True))
        return {'run_id': new['run_id'], 'parent_run': from_run, 'records': records, 'status': 'rerun-complete'}


class CorpusParser(argparse.ArgumentParser):
    def error(self, message):
        raise CorpusError('unsupported-control' if 'unrecognized arguments' in message else 'invalid-options', message, 'arguments')


def make_parser():
    parser = CorpusParser(prog='research-corpus')
    subs = parser.add_subparsers(dest='command', required=True)
    init = subs.add_parser('init'); init.add_argument('corpus'); init.add_argument('--protocol', required=True)
    search = subs.add_parser('discover'); search.add_argument('corpus'); search.add_argument('--query', required=True); search.add_argument('--profile', required=True); search.add_argument('--operation-id', required=True); search.add_argument('--strategy', choices=['first', 'federated'], default='federated'); search.add_argument('--limit', type=int, default=8); search.add_argument('--domain', action='append', default=[]); search.add_argument('--exclude-domain', action='append', default=[]); search.add_argument('--engine', choices=['auto', 'duckduckgo', 'brave', 'bing'], default='auto')
    for command in ['open', 'export']:
        source = subs.add_parser(command); source.add_argument('corpus'); source.add_argument('--source-id', required=True); source.add_argument('--url'); source.add_argument('--profile'); source.add_argument('--from-index', action='store_true'); source.add_argument('--format', choices=['all'], default='all')
    retained = subs.add_parser('retain'); retained.add_argument('corpus'); retained.add_argument('file'); retained.add_argument('--kind', choices=['protocol', 'screening', 'synthesis'], required=True); retained.add_argument('--operation-id', required=True); retained.add_argument('--format', choices=['text', 'markdown'], default='text')
    stopped = subs.add_parser('stop'); stopped.add_argument('corpus'); stopped.add_argument('--reason', required=True)
    resume_parser = subs.add_parser('resume'); resume_parser.add_argument('corpus')
    replay = subs.add_parser('reproduce'); replay.add_argument('corpus'); replay.add_argument('--output', required=True); replay.add_argument('--offline', required=True, action='store_true')
    live = subs.add_parser('rerun'); live.add_argument('corpus'); live.add_argument('--from', dest='from_run', required=True); live.add_argument('--profile', required=True)
    profile = subs.add_parser('profiles'); profile.add_argument('action', choices=['create', 'close', 'cleanup', 'handles']); profile.add_argument('corpus'); profile.add_argument('--owner-execution', default=''); profile.add_argument('--purpose', default=''); profile.add_argument('--mode', choices=['persistent', 'ephemeral'], default='persistent'); profile.add_argument('--authorization'); profile.add_argument('--receipt')
    try:
        import research_corpus_services
        research_corpus_services.add_parsers(subs)
    except ImportError:
        pass
    return parser


def mcp_plan(command):
    if not isinstance(command, list) or not 1 <= len(command) <= 128 or any(
            not isinstance(arg, str) or len(arg) > 8192 or '\x00' in arg for arg in command):
        raise CorpusError('invalid-options', 'MCP command must be a bounded argument array', 'arguments')
    args = make_parser().parse_args(command)
    requests = []
    if args.command == 'profiles':
        if args.action == 'handles':
            raise CorpusError('private-operation', 'Profile handles are internal IPC only', 'arguments')
        if args.action in ('close', 'cleanup'):
            authorization = {'reference': args.authorization, 'owner_execution': args.owner_execution,
                             'disposable': True} if args.authorization else None
            requests = profiles(args.corpus, 'handles', args.owner_execution,
                                authorization=authorization)['requests']
            if args.action == 'cleanup':
                requests = [request for request in requests
                            if os.path.lexists(request['handle']['canonical_path'])]
    return {'schema': 'agency/corpus-mcp-plan/1', 'profile_requests': requests}


def main(argv=None):
    try:
        if os.environ.get('RESEARCH_CORPUS_PARENT_PIPE') == '1':
            def watch_parent():
                while os.read(sys.stdin.fileno(), 1):
                    pass
                os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=watch_parent, daemon=True, name='corpus-parent').start()
        argv = sys.argv[1:] if argv is None else argv
        if argv == ['--mcp-plan']:
            data = sys.stdin.buffer.read(65537)
            if len(data) > 65536:
                raise CorpusError('invalid-options', 'MCP plan exceeds 65536 bytes', 'arguments')
            result = mcp_plan(json.loads(data)['command'])
            print(json.dumps({'ok': True, **result}, ensure_ascii=False, sort_keys=True))
            return 0
        args = make_parser().parse_args(argv)
        if args.command == 'init': result = init_corpus(args.corpus, args.protocol)
        elif args.command == 'discover': result = discover(args.corpus, args.query, args.profile, args.operation_id, args.strategy, args.limit, args.domain, args.exclude_domain, args.engine)
        elif args.command in ['open', 'export']:
            if args.command == 'export' and not args.from_index:
                raise CorpusError('index-only-required', 'Export requires --from-index', 'export')
            result = open_source(args.corpus, args.source_id, args.url, args.profile, args.from_index)
        elif args.command == 'resume': result = resume(args.corpus)
        elif args.command == 'stop': result = stop(args.corpus, args.reason)
        elif args.command == 'retain': result = retain(args.corpus, args.file, args.kind, args.operation_id, args.format)
        elif args.command == 'reproduce':
            import research_corpus_reproduce
            result = research_corpus_reproduce.reproduce(args.corpus, args.output)
        elif args.command == 'rerun': result = rerun(args.corpus, args.from_run, args.profile)
        elif args.command == 'profiles':
            authorization = {'reference': args.authorization, 'owner_execution': args.owner_execution, 'disposable': True} if args.authorization else None
            result = profiles(args.corpus, args.action, args.owner_execution, args.purpose, authorization, args.receipt, args.mode)
        else:
            import research_corpus_services
            result = research_corpus_services.dispatch(args)
        print(json.dumps({'ok': True, **result}, ensure_ascii=False, sort_keys=True))
        return 0 if result.get('ok', True) and result.get('status') != 'evidence-retained-process-failed' else 1
    except CorpusError as exc:
        print(json.dumps({'ok': False, 'error': exc.as_dict()}, ensure_ascii=False, sort_keys=True))
        return 1
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': {'code': 'invalid-input', 'message': sanitize(str(exc)), 'stage': 'dispatch', 'retriable': False, 'next_action': 'Check inputs and corpus audit'}}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
