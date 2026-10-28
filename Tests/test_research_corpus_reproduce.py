import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Tools'))
import research_corpus_core as core
import research_corpus_reproduce as replay


class ReproduceTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, PATH=str(Path(__file__).resolve().parents[1] / 'Tools')
                                 + os.pathsep + os.environ.get('PATH', ''))
        environment.start()
        self.addCleanup(environment.stop)

    def test_archived_software_identity_metadata_must_match_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            protocol = base / 'protocol.json'
            protocol.write_text('{"scope":"fixture"}')
            root = base / 'corpus'
            core.init_corpus(root, protocol)
            with patch.object(core, 'run_backend', return_value=({'results': []}, {'exit_code': 0})):
                core.discover(root, 'query', 'fixture', 'one')
            software = core.read_manifest(root)['runs'][0]['software']
            path = root / software['path'] / 'software.json'
            changed = json.loads(path.read_text())
            changed['runtime']['python'] = 'altered provenance'
            path.write_text(json.dumps(changed))
            with self.assertRaises(core.CorpusError) as caught:
                replay.reproduce(root, base / 'output')
            self.assertEqual(caught.exception.code, 'software-integrity')
            self.assertFalse((base / 'output').exists())

    def test_relocated_rebuild_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            protocol = directory / 'protocol.json'
            protocol.write_text('{"scope":"fixture"}')
            original = directory / 'original'
            core.init_corpus(original, protocol)
            with patch.object(core, 'run_backend', return_value=({'results': [{'url': 'https://example.org/a', 'title': 'Alpha'}]}, {'exit_code': 0})):
                core.discover(original, 'alpha', 'fixture', 'one')
            moved = directory / 'moved'
            shutil.copytree(original, moved)
            shutil.rmtree(original)
            result = replay.reproduce(moved, directory / 'rebuilt')
            self.assertEqual(result['verified_records'], 1)
            self.assertEqual(core.read_manifest(moved), core.read_manifest(directory / 'rebuilt'))
            entry = core.committed_records(moved)[0]
            core.safe_path(moved, entry['paths']['text']).write_text('tampered')
            with self.assertRaises(core.CorpusError):
                replay.reproduce(moved, directory / 'bad')

    def test_unsupported_software_version(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            protocol = directory / 'protocol.json'; protocol.write_text('{"scope":"fixture"}')
            root = directory / 'corpus'; core.init_corpus(root, protocol)
            manifest = core.read_manifest(root)
            manifest['runs'][0]['software']['schema'] = 'future/999'
            core.atomic_json(root / 'manifest.json', manifest)
            with self.assertRaises(core.CorpusError):
                replay.reproduce(root, directory / 'output')


if __name__ == '__main__':
    unittest.main()
