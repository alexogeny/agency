"""Offline derived views of committed, sanitized research corpus evidence."""
from __future__ import annotations

import csv
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager


def core():
    import research_corpus_core
    return research_corpus_core


def error(code, message, stage='index', next_action='Inspect the named corpus artifact and retry.'):
    return core().CorpusError(code, core().sanitize(message), stage=stage, next_action=next_action)


def parse_year(value):
    """Interpret declared date formats, leaving ambiguous numeric dates unknown."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r'\d{4}', value):
        year = int(value)
        return year if 1500 <= year <= dt.datetime.now(dt.timezone.utc).year + 1 else None
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%SZ', '%d %b %Y', '%d %B %Y', '%B %d, %Y', '%b %d, %Y'):
        try:
            year = dt.datetime.strptime(value, fmt).year
            return year if 1500 <= year <= dt.datetime.now(dt.timezone.utc).year + 1 else None
        except ValueError:
            pass
    return None


def external_path(root, value, runtime=False):
    path = Path(value).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise error('unsafe-path', f'Symlink output path refused: {path}')
    root = Path(root).resolve()
    checkout = Path(__file__).resolve().parents[1]
    if (checkout / '.git').exists() and (path == checkout or checkout in path.parents):
        raise error('unsafe-path', 'Generated databases and ledgers must be outside the checkout.')
    if path == root or root in path.parents:
        raise error('unsafe-path', 'Generated databases and ledgers must be outside the corpus.')
    if runtime and any((parent / '.git').exists() for parent in path.parents):
        raise error('unsafe-path', 'Generated index databases and sidecars must be outside repositories.')
    return path


@contextmanager
def index_lock(db, exclusive):
    lock = db.with_suffix(db.suffix + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_symlink():
        raise error('unsafe-path', 'Index lock path must not be a symlink.')
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'r+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def documents(root):
    api = core()
    manifest = api.read_manifest(root)
    entries = api.committed_records(root)
    if not entries:
        raise error('empty-selection', 'Corpus has no committed records.')
    docs = []
    for entry in entries:
        record = api.load_record(root, entry)
        if api.sanitize(record) != record:
            raise error('unsanitized-input', f'Record violates the export sanitization policy: {entry["record_id"]}')
        relative = entry['paths']['text']
        try:
            body = api.safe_path(root, relative).read_text(encoding='utf-8', errors='strict')
        except UnicodeError as exc:
            raise error('invalid-utf8', f'Invalid UTF-8: {relative}') from exc
        if api.sanitize(body) != body:
            raise error('unsanitized-input', f'Text artifact violates sanitization policy: {relative}')
        extraction = record.get('extraction') or {}
        retrieval = record.get('retrieval') or {}
        docs.append({'record_id': entry['record_id'], 'source_id': entry.get('source_id'), 'run_id': entry['run_id'], 'path': relative, 'kind': entry['kind'], 'title': record.get('title') or '', 'url': record.get('url') or '', 'body': body, 'sha256': api.sha256(body.encode('utf-8')), 'coverage': extraction.get('coverage', 'unknown'), 'access': retrieval.get('access', 'unknown'), 'observations': extraction.get('quality_observations', []), 'limitations': extraction.get('limitations', []), 'line_start': 1, 'line_end': max(1, len(body.splitlines()))})
    docs.sort(key=lambda row: (row['path'], row['record_id']))
    return manifest, docs


def build_index(root, db, manifest_path=None):
    api = core()
    root = Path(root)
    db = external_path(root, db, runtime=True)
    sidecar = external_path(root, manifest_path or db.with_suffix(db.suffix + '.manifest.json'), runtime=True)
    if sidecar in (db, db.with_suffix(db.suffix + '.lock')):
        raise error('unsafe-path', 'Database, sidecar and lifecycle lock must be distinct.')
    # Load and validate every input before touching the last usable generation.
    with api.corpus_lock(root):
        manifest, docs = documents(root)
    descriptors = [{k: v for k, v in d.items() if k != 'body'} for d in docs]
    generation = api.sha256(api.canonical_bytes({'corpus_id': manifest['corpus_id'], 'documents': descriptors}))
    meta = {'schema': 'agency/research-index/1', 'corpus_id': manifest['corpus_id'], 'generation': generation, 'document_count': len(docs), 'documents': descriptors, 'included': [d['path'] for d in docs], 'excluded': [], 'sidecar': str(sidecar)}
    db.parent.mkdir(parents=True, exist_ok=True)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + db.name + '.', dir=db.parent)
    os.close(descriptor)
    temp = Path(temporary)
    try:
        with closing(sqlite3.connect(temp)) as connection, connection:
            connection.execute('CREATE TABLE metadata (generation TEXT, corpus_id TEXT, sidecar TEXT)')
            connection.execute('INSERT INTO metadata VALUES (?, ?, ?)', (generation, manifest['corpus_id'], str(sidecar)))
            connection.execute('CREATE TABLE documents (record_id TEXT PRIMARY KEY, metadata TEXT NOT NULL)')
            connection.execute('CREATE VIRTUAL TABLE evidence USING fts5(record_id UNINDEXED, title, body)')
            connection.executemany('INSERT INTO documents VALUES (?, ?)', [(d['record_id'], json.dumps({k: v for k, v in d.items() if k != 'body'}, sort_keys=True)) for d in docs])
            connection.executemany('INSERT INTO evidence VALUES (?, ?, ?)', [(d['record_id'], d['title'], d['body']) for d in docs])
        with temp.open('rb') as stream:
            os.fsync(stream.fileno())
        with index_lock(db, True):
            # Rollback handles ordinary publication errors. A process crash between
            # renames is detected by the generation check rather than hidden.
            backup = db.with_name('.' + db.name + '.' + uuid.uuid4().hex + '.previous')
            had_db = db.exists()
            old_sidecar = sidecar.read_bytes() if sidecar.exists() else None
            if had_db:
                os.link(db, backup)
            try:
                os.replace(temp, db)
                api.atomic_json(sidecar, meta)
                directory = os.open(db.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except BaseException:
                if had_db:
                    os.replace(backup, db)
                else:
                    db.unlink(missing_ok=True)
                if old_sidecar is None:
                    sidecar.unlink(missing_ok=True)
                else:
                    fd, restore_name = tempfile.mkstemp(prefix='.' + sidecar.name, dir=sidecar.parent)
                    with os.fdopen(fd, 'wb') as restore:
                        restore.write(old_sidecar)
                        restore.flush()
                        os.fsync(restore.fileno())
                    os.replace(restore_name, sidecar)
                raise
            finally:
                backup.unlink(missing_ok=True)
    except sqlite3.Error as exc:
        raise error('index-unavailable', f'Unable to build FTS5 index: {exc}', next_action='Use Python with SQLite FTS5 support and check output permissions.') from exc
    finally:
        temp.unlink(missing_ok=True)
    return {'ok': True, 'generation': generation, 'document_count': len(docs), 'db': str(db), 'manifest': str(sidecar)}


def query_index(root, db, expression, prefix=None, kind='source', limit=20):
    api = core()
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise error('invalid-limit', 'Query limit must be between 1 and 1000.')
    if kind not in ('source', 'discovery', 'screening', 'synthesis', 'protocol', 'all'):
        raise error('invalid-kind', f'Unknown document kind: {kind}')
    if prefix is not None:
        api.safe_path(root, prefix)
    db = external_path(root, db, runtime=True)
    if not db.is_file():
        raise error('index-unavailable', f'Index does not exist: {db}', next_action='Run research-corpus index build with an external --db path.')
    try:
        with index_lock(db, False), closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as connection:
            identity = connection.execute('SELECT generation, corpus_id, sidecar FROM metadata').fetchone()
            if not identity:
                raise error('index-unavailable', 'Index metadata is empty; rebuild the index.')
            generation, corpus_id, sidecar = identity
            sidecar_path = external_path(root, sidecar, runtime=True)
            try:
                meta = json.loads(sidecar_path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise error('index-generation-mismatch', 'Index generation sidecar is missing or malformed; rebuild the index.') from exc
            expected_generation = api.sha256(api.canonical_bytes({'corpus_id': meta.get('corpus_id'), 'documents': meta.get('documents')}))
            if meta.get('generation') != generation or meta.get('corpus_id') != corpus_id or expected_generation != generation:
                raise error('index-generation-mismatch', 'Index generation does not match its sidecar; rebuild the index.')
            if api.read_manifest(root)['corpus_id'] != corpus_id:
                raise error('index-corpus-mismatch', 'Index belongs to a different corpus.')
            clauses = ['evidence MATCH ?']
            values = [expression]
            if kind != 'all':
                clauses.append("json_extract(documents.metadata, '$.kind') = ?")
                values.append(kind)
            if prefix is not None:
                clauses.append("substr(json_extract(documents.metadata, '$.path'), 1, ?) = ?")
                values.extend([len(prefix), prefix])
            values.append(limit)
            rows = connection.execute('SELECT documents.metadata, snippet(evidence, 2, \'[\', \']\', \' … \', 32), bm25(evidence), highlight(evidence, 2, char(1), char(2)) FROM evidence JOIN documents USING(record_id) WHERE ' + ' AND '.join(clauses) + ' ORDER BY bm25(evidence), evidence.record_id LIMIT ?', values).fetchall()
    except sqlite3.Error as exc:
        code = 'invalid-query' if 'fts5' in str(exc).lower() or 'syntax' in str(exc).lower() or 'unterminated' in str(exc).lower() else 'index-unavailable'
        raise error(code, f'Index query failed: {exc}', next_action='Check the FTS5 expression or rebuild an incompatible index.') from exc
    hits = []
    for row, snippet, rank, highlighted in rows:
        hit = dict(json.loads(row), snippet=snippet, rank=rank)
        first = highlighted.find(chr(1))
        if first >= 0:
            hit['line_start'] = highlighted[:first].count('\n') + 1
            last = highlighted.rfind(chr(2))
            hit['line_end'] = highlighted[:last].count('\n') + 1
        hits.append(hit)
    return {'ok': True, 'generation': generation, 'kind': kind, 'hits': hits, 'limit': limit}


def audit_corpus(root):
    with core().corpus_lock(root):
        return _audit_corpus(root)


def _audit_corpus(root):
    api = core()
    manifest = api.read_manifest(root)
    issues = []
    entries = manifest.get('records', [])
    if not entries:
        issues.append({'check': 'empty-selection', 'message': 'No committed records'})
    runs = {r.get('run_id'): r for r in manifest.get('runs', [])}
    for run_id, run in runs.items():
        for field in ('recipe', 'software'):
            if not run.get(field):
                issues.append({'check': 'run-provenance', 'run_id': run_id, 'field': field})
        software = run.get('software') or {}
        if not software.get('hashes') or not software.get('runtime'):
            issues.append({'check': 'software-provenance', 'run_id': run_id})
        if run.get('recipe', {}).get('schema') != 'agency/research-recipe/1':
            issues.append({'check': 'recipe-schema', 'run_id': run_id})
        for relative, digest in software.get('hashes', {}).items():
            try:
                path = api.safe_path(root, str(Path(software.get('path', '')) / relative))
                if api.sha256(path.read_bytes()) != digest:
                    raise ValueError('Software hash differs')
            except (OSError, ValueError, api.CorpusError) as exc:
                issues.append({'check': 'software-hash', 'path': relative, 'message': str(exc)})
    if manifest.get('redaction_policy') != api.SANITIZER_VERSION:
        issues.append({'check': 'redaction-policy', 'message': 'Missing redaction policy version'})
    if any(api.safe_path(root, path).exists() for path in ('pending/result.json', 'pending/request.json')):
        issues.append({'check': 'incomplete-checkpoint', 'message': 'Pending export requires resume'})
    counts = dict(discovery=0, opened=0, substantive=0, screened=0, pending=0, unavailable=0, duplicates=0, process_unknown=0, coverage_unknown=0)
    seen = set()
    coverage_values = {'full-public-extract', 'abstract-only', 'metadata-only', 'thin', 'link-directory', 'blocked', 'not-found', 'partial-navigation', 'unknown'}
    checked_processors = set()
    for entry in entries:
        rid = entry.get('record_id')
        if rid in seen:
            issues.append({'check': 'duplicate-record-id', 'record_id': rid})
        seen.add(rid)
        if set(entry.get('hashes', {})) != set(entry.get('paths', {}).values()):
            issues.append({'check': 'artifact-hash-selection', 'record_id': rid})
        for key in ('json', 'text', 'markdown'):
            relative = entry.get('paths', {}).get(key)
            try:
                if not relative:
                    raise ValueError(f'Missing {key} sibling')
                data = api.safe_path(root, relative).read_bytes()
                data.decode('utf-8', errors='strict')
                if api.sha256(data) != entry.get('hashes', {}).get(relative):
                    raise ValueError('Artifact hash differs')
            except (OSError, ValueError, api.CorpusError) as exc:
                issues.append({'check': 'artifact', 'record_id': rid, 'path': relative, 'message': str(exc)})
        try:
            record = api.load_record(root, entry)
        except (OSError, ValueError, api.CorpusError) as exc:
            issues.append({'check': 'record', 'record_id': rid, 'message': str(exc)})
            continue
        processor = record.get('software')
        if not isinstance(processor, dict) or not processor.get('hashes') or not processor.get('runtime'):
            issues.append({'check': 'software-provenance', 'record_id': rid})
        else:
            identity = api.sha256(api.canonical_bytes(processor))
            if identity not in checked_processors:
                checked_processors.add(identity)
                for name, digest in processor['hashes'].items():
                    relative = str(Path(processor.get('path', '')) / name)
                    try:
                        if api.sha256(api.safe_path(root, relative).read_bytes()) != digest:
                            raise ValueError('Observation processor hash differs')
                    except (OSError, ValueError, api.CorpusError) as exc:
                        issues.append({'check': 'software-hash', 'record_id': rid,
                                       'path': relative, 'message': str(exc)})
        try:
            checkpoint = json.loads(api.safe_path(root, 'journal/' + str(rid) + '.json').read_text(encoding='utf-8'))
            if checkpoint.get('entry') != entry:
                raise ValueError('Checkpoint differs from committed entry')
        except (OSError, ValueError, api.CorpusError) as exc:
            issues.append({'check': 'checkpoint', 'record_id': rid, 'message': str(exc)})
        if not record.get('transformations') or not any(item.get('version') == manifest.get('redaction_policy') for item in record.get('transformations', [])):
            issues.append({'check': 'redaction-policy', 'record_id': rid})
        body_digest = record.get('identities', {}).get('sanitized_body_sha256')
        if body_digest != api.sha256(record.get('text', '').encode('utf-8')):
            issues.append({'check': 'body-identity', 'record_id': rid})
        if api.sanitize(record) != record:
            issues.append({'check': 'sanitization', 'record_id': rid})
        if entry.get('run_id') not in runs:
            issues.append({'check': 'run-reference', 'record_id': rid})
        if entry.get('kind') == 'source' and entry.get('source_id') not in manifest.get('sources', {}):
            issues.append({'check': 'source-reference', 'record_id': rid})
        for field in ('record_id', 'kind', 'run_id', 'source_id'):
            if record.get(field) != entry.get(field):
                issues.append({'check': 'record-identity', 'record_id': rid, 'field': field})
        try:
            timestamp = dt.datetime.fromisoformat(record.get('created_at', '').replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Missing timezone')
        except (ValueError, TypeError):
            issues.append({'check': 'retrieval-date', 'record_id': rid})
        coverage = record.get('extraction', {}).get('coverage', 'unknown')
        if coverage not in coverage_values:
            issues.append({'check': 'coverage', 'record_id': rid, 'value': coverage})
        access = record.get('retrieval', {}).get('access')
        if not access:
            issues.append({'check': 'access', 'record_id': rid})
        process = record.get('process') or {}
        if not process:
            issues.append({'check': 'process', 'record_id': rid})
        elif process.get('exit_code') not in (0, None) or process.get('timed_out') or process.get('browser_released') is False:
            issues.append({'check': 'process-incomplete', 'record_id': rid, 'process': process})
        counts['process_unknown'] += process.get('browser_released') is None
        counts['coverage_unknown'] += coverage == 'unknown'
        for field, kind in [('text', 'text'), ('markdown', 'markdown')]:
            try:
                retained = api.safe_path(root, entry['paths'][kind]).read_bytes()
                if retained != (record.get(field, '') + '\n').encode('utf-8'):
                    issues.append({'check': 'sibling-consistency', 'record_id': rid, 'path': entry['paths'][kind]})
            except OSError:
                pass
        if entry.get('kind') == 'discovery':
            counts['discovery'] += 1
        elif entry.get('kind') == 'source':
            counts['opened'] += 1
            counts['substantive'] += coverage in ('full-public-extract', 'abstract-only')
            counts['unavailable'] += coverage in ('blocked', 'not-found') or access in ('blocked', 'not-found', 'login-required')
            screening = record.get('screening', {})
            counts['screened'] += screening.get('relevance') in ('include', 'exclude')
            counts['pending'] += screening.get('full_text_decision', 'pending') == 'pending'
            counts['duplicates'] += bool(screening.get('duplicate_of'))
    counts['unique_opened_sources'] = len({entry.get('source_id') for entry in entries if entry.get('kind') == 'source'})
    return {'ok': not issues, 'corpus_id': manifest['corpus_id'], 'record_count': len(entries), 'counts': counts, 'issues': issues}


def compare_runs(root, old, new):
    api = core()
    manifest = api.read_manifest(root)
    runs = {r['run_id']: r for r in manifest['runs']}
    if old not in runs or new not in runs:
        raise error('unknown-run', 'Both comparison runs must exist.', 'compare')
    def selected(run):
        result = {}
        for entry in api.committed_records(root):
            if entry['run_id'] != run:
                continue
            record = api.load_record(root, entry)
            key = (entry['kind'], entry.get('source_id') or record.get('payload', {}).get('query') or record.get('title', ''))
            result.setdefault(key, []).append(record)
        return result
    before, after = selected(old), selected(new)
    changes = []
    for key in sorted(before.keys() | after.keys(), key=str):
        left, right = before.get(key, []), after.get(key, [])
        if not left or not right:
            changes.append({'identity': list(key), 'change': 'added' if right else 'removed', 'record_ids': [r['record_id'] for r in right or left]})
            continue
        a, b = left[-1], right[-1]
        fields = {}
        for name, av, bv in [('body', a.get('text'), b.get('text')), ('access', a.get('retrieval'), b.get('retrieval')), ('coverage', a.get('extraction'), b.get('extraction')), ('rankings', a.get('payload', {}).get('results'), b.get('payload', {}).get('results'))]:
            if av != bv:
                fields[name] = {'old': api.sha256(api.canonical_bytes(av)) if name in ('body', 'rankings') else av, 'new': api.sha256(api.canonical_bytes(bv)) if name in ('body', 'rankings') else bv}
                if name == 'rankings':
                    old_ranks = {item.get('url'): rank for rank, item in enumerate(av or [], 1) if isinstance(item, dict) and item.get('url')}
                    new_ranks = {item.get('url'): rank for rank, item in enumerate(bv or [], 1) if isinstance(item, dict) and item.get('url')}
                    fields[name]['movements'] = [{'url': url, 'old_rank': old_ranks.get(url), 'new_rank': new_ranks.get(url)} for url in sorted(old_ranks.keys() | new_ranks.keys()) if old_ranks.get(url) != new_ranks.get(url)]
        if fields:
            changes.append({'identity': list(key), 'change': 'changed', 'fields': fields, 'old_record_id': a['record_id'], 'new_record_id': b['record_id']})
    return {'ok': True, 'old': old, 'new': new, 'changes': changes, 'software_changed': runs[old].get('software') != runs[new].get('software'), 'recipe_changed': runs[old].get('recipe') != runs[new].get('recipe')}


SCREENING_FIELDS = ['source_id', 'record_id', 'title', 'year', 'authors', 'doi', 'url', 'discovery_source', 'discovery_record_id', 'duplicate_of', 'duplicate_candidates', 'title_abstract_decision', 'title_abstract_reason', 'full_text_decision', 'full_text_reason', 'notes', 'raw_date', 'parsed_year', 'extracted_byline', 'field_provenance', 'verification_status', 'coverage', 'access']


def _verified_field(bibliography, field):
    provenance = bibliography.get('field_provenance', {}).get(field)
    return (bibliography.get(field + '_verification_status') == 'verified'
            and isinstance(provenance, dict)
            and provenance.get('origin') in {'metadata', 'visible-main', 'authoritative-record', 'authoritative-bibliographic-record'}
            and provenance.get('inspected') is True
            and provenance.get('alignment_verified') is True)


def reconcile_screening(root, ledger, output):
    api = core()
    output = external_path(root, output)
    ledger = Path(ledger)
    if output.exists() or output == ledger.absolute():
        raise error('screening-output-exists', 'Screening reconciliation requires a new output path.', 'screening')
    with ledger.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        old_fields = reader.fieldnames or []
        old = list(reader)
    keyed = {}
    for row in old:
        sid = row.get('source_id')
        if not sid or sid in keyed:
            raise error('invalid-screening-ledger', 'Existing ledger requires unique stable source_id values.', 'screening')
        keyed[sid] = row
    rows = dict(keyed)
    for entry in api.committed_records(root):
        if entry['kind'] != 'source':
            continue
        record = api.load_record(root, entry)
        sid = entry['source_id']
        bib = record.get('bibliography') or {}
        provenance = bib.get('field_provenance') or {}
        # Verification is field-specific: a title's status cannot verify authors.
        authors_verified = _verified_field(bib, 'authors') and bib.get('verified_authors')
        year_verified = _verified_field(bib, 'year') and bib.get('verified_year')
        row = {'source_id': sid, 'record_id': record['record_id'], 'title': record.get('title') or '', 'url': record.get('url') or '', 'doi': bib.get('doi') or '', 'year': bib.get('verified_year') if year_verified else '', 'authors': '; '.join(bib['verified_authors']) if authors_verified and isinstance(bib['verified_authors'], list) else bib.get('verified_authors', '') if authors_verified else '', 'raw_date': bib.get('raw_date') or '', 'parsed_year': parse_year(bib.get('raw_date')) or '', 'extracted_byline': bib.get('extracted_byline') or '', 'field_provenance': json.dumps(provenance, sort_keys=True), 'verification_status': 'verified' if authors_verified and year_verified else 'pending', 'title_abstract_decision': 'pending', 'full_text_decision': 'pending', 'coverage': record.get('extraction', {}).get('coverage', 'unknown'), 'access': record.get('retrieval', {}).get('access', 'unknown')}
        # Manual decisions and arbitrary reviewer columns always survive.
        row.update(keyed.get(sid, {}))
        rows[sid] = row
    if not rows:
        raise error('empty-selection', 'No screening records selected.', 'screening')
    candidates = {}
    for sid, row in rows.items():
        for kind, value in [('doi', str(row.get('doi', '')).lower().removeprefix('https://doi.org/')), ('title', re.sub(r'\W+', ' ', str(row.get('title', '')).casefold()).strip()), ('url', row.get('url', ''))]:
            if value:
                candidates.setdefault((kind, value), []).append(sid)
    duplicates = {sid: set() for sid in rows}
    for group in candidates.values():
        if len(group) > 1:
            for sid in group:
                duplicates[sid].update(set(group) - {sid})
    for sid, row in rows.items():
        row['duplicate_candidates'] = ';'.join(sorted(duplicates[sid]))
    fields = list(dict.fromkeys(SCREENING_FIELDS + old_fields))
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tempname = tempfile.mkstemp(prefix='.' + output.name, dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows[sid] for sid in sorted(rows))
            stream.flush()
            os.fsync(stream.fileno())
        # Hard link publishes exclusively, preventing a concurrent overwrite.
        os.link(tempname, output)
    finally:
        Path(tempname).unlink(missing_ok=True)
    return {'ok': True, 'output': str(output), 'record_count': len(rows), 'preserved_count': len(old), 'duplicate_candidate_count': sum(bool(v) for v in duplicates.values())}


def add_parsers(subparsers):
    index = subparsers.add_parser('index')
    nested = index.add_subparsers(dest='index_command', required=True)
    build = nested.add_parser('build')
    build.add_argument('corpus')
    build.add_argument('--db', required=True)
    build.add_argument('--manifest')
    query = nested.add_parser('query')
    query.add_argument('corpus')
    query.add_argument('expression')
    query.add_argument('--db', required=True)
    query.add_argument('--prefix')
    query.add_argument('--kind', default='source', choices=['source', 'discovery', 'screening', 'synthesis', 'protocol', 'all'])
    query.add_argument('--limit', type=int, default=20)
    audit = subparsers.add_parser('audit')
    audit.add_argument('corpus')
    audit.add_argument('--json', action='store_true')
    compare = subparsers.add_parser('compare')
    compare.add_argument('corpus')
    compare.add_argument('--old', required=True)
    compare.add_argument('--new', required=True)
    screening = subparsers.add_parser('screening')
    nested = screening.add_subparsers(dest='screening_command', required=True)
    reconcile = nested.add_parser('reconcile')
    reconcile.add_argument('corpus')
    reconcile.add_argument('--ledger', required=True)
    reconcile.add_argument('--output', required=True)


def dispatch(args):
    if args.command == 'index':
        if args.index_command == 'build':
            return build_index(args.corpus, args.db, args.manifest)
        return query_index(args.corpus, args.db, args.expression, args.prefix, args.kind, args.limit)
    if args.command == 'audit':
        return audit_corpus(args.corpus)
    if args.command == 'compare':
        return compare_runs(args.corpus, args.old, args.new)
    if args.command == 'screening':
        return reconcile_screening(args.corpus, args.ledger, args.output)
    raise error('unknown-command', 'Unknown corpus service command.', 'dispatch')
