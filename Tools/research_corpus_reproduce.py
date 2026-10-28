"""Verify portable inputs and execute their archived offline export processor."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from research_corpus_core import (CorpusError, RECORD_SCHEMA, _atomic_bytes, _fsync_dir,
                                  atomic_json, canonical_bytes, corpus_lock,
                                  load_record, read_manifest, safe_path, sha256)


def _software_refs(root, manifest):
    refs = {run['software']['path']: run['software'] for run in manifest['runs']}
    for entry in manifest['records']:
        record = load_record(root, entry)
        if record.get('software'):
            refs[record['software']['path']] = record['software']
    return list(refs.values())


def _verify(root, manifest):
    if any(safe_path(root, path).exists() for path in ['pending/result.json', 'pending/request.json']):
        raise CorpusError('export-pending', 'Resume pending result before reproduction', 'reproduce')
    if not manifest['records']:
        raise CorpusError('empty-selection', 'No committed records to reproduce', 'reproduce')
    for entry in manifest['records']:
        record = load_record(root, entry)
        expected = {'json': canonical_bytes(record), 'text': (record['text'] + '\n').encode(), 'markdown': (record['markdown'] + '\n').encode()}
        for kind, data in expected.items():
            if safe_path(root, entry['paths'][kind]).read_bytes() != data:
                raise CorpusError('sibling-inconsistent', 'Record siblings disagree with retained input', 'reproduce', artifact=entry['paths'][kind])
    for software in _software_refs(root, manifest):
        if software.get('schema') != 'agency/research-software/1':
            raise CorpusError('unsupported-version', 'Unsupported archived processing software schema', 'reproduce')
        if not {'research_corpus_core.py', 'research_corpus_reproduce.py'} <= software['hashes'].keys():
            raise CorpusError('software-unavailable', 'Archived offline processor is incomplete', 'reproduce')
        identity = json.loads(safe_path(root, software['path'] + '/software.json').read_text())
        if identity != software:
            raise CorpusError('software-integrity', 'Archived software identity manifest differs', 'reproduce')
        for name, digest in software['hashes'].items():
            data = safe_path(root, software['path'] + '/' + name).read_bytes()
            if sha256(data) != digest:
                raise CorpusError('software-integrity', 'Archived software hash mismatch', 'reproduce', artifact=name)
    return len(manifest['records'])


def _worker(root, output, selected_software=None):
    """This function is executed from the retained package inside the OS sandbox."""
    def deny_network(event, args):
        if event.startswith('socket.') or event in ['subprocess.Popen', 'os.system']:
            raise RuntimeError('Offline processor cannot open network or launch processes')
    sys.addaudithook(deny_network)
    root, output = Path(root), Path(output)
    manifest = read_manifest(root)
    _verify(root, manifest)
    selected_count = 0
    for entry in manifest['records']:
        record = load_record(root, entry)
        software = record.get('software') or next(run['software'] for run in manifest['runs'] if run['run_id'] == record['run_id'])
        if selected_software and software['path'] != selected_software:
            continue
        selected_count += 1
        data = {'json': canonical_bytes(record), 'text': (record['text'] + '\n').encode(), 'markdown': (record['markdown'] + '\n').encode()}
        for kind, content in data.items():
            _atomic_bytes(safe_path(output, entry['paths'][kind]), content)
        journal = 'journal/' + entry['record_id'] + '.json'
        source = safe_path(root, journal)
        if not source.is_file():
            raise CorpusError('invalid-checkpoint', 'Committed record checkpoint missing', 'reproduce')
        _atomic_bytes(safe_path(output, journal), source.read_bytes())
    copied = set()
    for software in _software_refs(root, manifest):
        if software['path'] in copied:
            continue
        copied.add(software['path'])
        for name in [*software['hashes'], 'software.json']:
            relative = software['path'] + '/' + name
            _atomic_bytes(safe_path(output, relative), safe_path(root, relative).read_bytes())
    atomic_json(safe_path(output, 'manifest.json'), manifest)
    print(json.dumps({'verified_records': selected_count, 'processor': 'archived', 'network': 'disabled', 'status': 'reproduced'}))


def reproduce(root, output):
    root, output = Path(root).absolute(), Path(output).absolute()
    safe_path(output.parent, output.name)
    if output.exists():
        raise CorpusError('output-exists', 'Reproduction output already exists', 'reproduce')
    if root == output or root in output.parents:
        raise CorpusError('unsafe-output', 'Reproduction output must be outside the input corpus', 'reproduce')
    sandbox = shutil.which('sandbox')
    if not sandbox:
        raise CorpusError('offline-isolation-unavailable', 'Install Agency sandbox to reproduce without network or browser state', 'reproduce')
    with corpus_lock(root):
        manifest = read_manifest(root)
        count = _verify(root, manifest)
        references = _software_refs(root, manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.reproduce-', dir=output.parent))
        try:
            verified_count = 0
            executed = []
            for software in references:
                package = safe_path(root, software['path'])
                invocation = 'import sys; sys.path.insert(0,sys.argv[1]); import research_corpus_reproduce as r; r._worker(sys.argv[2],sys.argv[3],sys.argv[4])'
                command = [sandbox, '--workspace', str(root), '--workspace-ro', '--rw', str(temporary), '--', sys.executable, '-I', '-B', '-c', invocation, str(package), str(root), str(temporary), software['path']]
                completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
                if completed.returncode:
                    raise CorpusError('offline-processing-failed', 'Archived processor failed inside offline sandbox', 'reproduce', next_action='Verify archived runtime compatibility and sandbox availability', detail=completed.stderr.decode(errors='replace')[-2000:])
                result = json.loads(completed.stdout)
                verified_count += result['verified_records']
                executed.append(software['path'])
            result = {'verified_records': verified_count, 'processor': 'archived', 'processors': executed, 'network': 'disabled', 'status': 'reproduced'}
            _verify(temporary, read_manifest(temporary))
            if result['verified_records'] != count:
                raise CorpusError('reproduction-mismatch', 'Archived processor returned inconsistent count', 'reproduce')
            os.rename(temporary, output)
            _fsync_dir(output.parent)
            return {**result, 'output': str(output)}
        except subprocess.TimeoutExpired as exc:
            raise CorpusError('offline-processing-timeout', 'Archived processing exceeded bounded duration', 'reproduce') from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
