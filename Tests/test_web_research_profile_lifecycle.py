import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / 'Tools/web-research'


class WebResearchProfileLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / 'profiles/task'
        self.profile.mkdir(parents=True)
        self.environment = dict(os.environ, WEB_RESEARCH_DATA_DIR=str(self.root))

    def run_state(self, *arguments):
        return subprocess.run(['bun', str(TOOL), 'profile-state', '--profile', 'task', *arguments],
                              env=self.environment, capture_output=True, text=True, timeout=10)

    def test_explicit_legacy_registration_is_pinned_and_records_real_use(self):
        result = self.run_state('--purpose', 'completed audit evidence')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['owner'], 'web-research')
        self.assertEqual(value['purpose'], 'completed audit evidence')
        self.assertTrue(value['pinned'])
        self.assertGreater(value['last_used_at'], 0)
        self.assertIsNone(value['completed_at'])
        self.assertFalse(Path(str(self.profile) + '.lock').exists())

    def test_completed_unpinned_state_is_explicit_and_default_read_is_read_only(self):
        result = self.run_state('--purpose', 'disposable task', '--unpinned', '--completed')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertFalse(value['pinned'])
        self.assertGreater(value['completed_at'], 0)
        metadata = Path(str(self.profile) + '.agency.json')
        before = metadata.read_bytes(), metadata.stat().st_mtime_ns
        result = self.run_state()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), value)
        self.assertEqual((metadata.read_bytes(), metadata.stat().st_mtime_ns), before)

    def test_live_lock_and_symlink_metadata_cannot_be_overwritten(self):
        lock = Path(str(self.profile) + '.lock')
        lock.write_text(str(os.getpid()))
        result = self.run_state('--purpose', 'blocked')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('in use', result.stderr)
        self.assertEqual(lock.read_text(), str(os.getpid()))
        lock.unlink()
        protected = self.root / 'protected.json'
        protected.write_text('{"secret": "preserve"}')
        Path(str(self.profile) + '.agency.json').symlink_to(protected)
        result = self.run_state('--purpose', 'blocked')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(protected.read_text(), '{"secret": "preserve"}')
        self.assertFalse(lock.exists())

    def test_metadata_edits_preserve_completion_and_activity_timestamps(self):
        result = self.run_state('--purpose', 'finished research', '--completed')
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = Path(str(self.profile) + '.agency.json')
        original = json.loads(result.stdout)
        original.update(last_used_at=1000, last_released_at=1100)
        metadata.write_text(json.dumps(original))
        for arguments, expected in (
            (('--unpinned',), {'pinned': False}),
            (('--purpose', 'archived research'), {'purpose': 'archived research'}),
            (('--pinned',), {'pinned': True}),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_state(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                original.update(expected)
                self.assertEqual(json.loads(result.stdout), original)
                self.assertFalse(Path(str(self.profile) + '.lock').exists())

    def test_active_explicitly_clears_completion_without_recording_browser_use(self):
        result = self.run_state('--completed')
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = Path(str(self.profile) + '.agency.json')
        original = json.loads(result.stdout)
        original.update(last_used_at=1000, last_released_at=1100)
        metadata.write_text(json.dumps(original))
        result = self.run_state('--active')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {**original, 'completed_at': None})

    def test_normal_claim_records_use_clears_completion_and_preserves_pinning(self):
        result = self.run_state('--purpose', 'fixture', '--unpinned', '--completed')
        self.assertEqual(result.returncode, 0, result.stderr)
        source = TOOL.read_text()
        source = source[source.index('function readProfileLifecycle('):source.index('\nclass Bidi {')]
        harness = '''
import {closeSync,existsSync,lstatSync,mkdirSync,openSync,readFileSync,renameSync,rmSync,unlinkSync,writeFileSync} from 'node:fs';
import {join,dirname} from 'node:path';
const root = Bun.argv[2];
function profileRoot() {return root;}
const claimed = claimProfile('task', [], false);
releaseProfile(claimed);
console.log(readFileSync(`${root}.agency.json`, 'utf8'));
'''
        script = self.root / 'claim.ts'
        script.write_text(source + harness)
        result = subprocess.run(['bun', str(script), str(self.profile)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertIsNone(value['completed_at'])
        self.assertFalse(value['pinned'])
        self.assertGreater(value['last_released_at'], 0)

    def test_metadata_write_failure_preserves_state_and_removes_owned_temporary_and_lock(self):
        result = self.run_state('--purpose', 'preserved state')
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = Path(str(self.profile) + '.agency.json')
        before = metadata.read_bytes()
        source = TOOL.read_text()
        source = source[source.index('function readProfileLifecycle('):source.index('\nclass Bidi {')]
        harness = '''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import {closeSync,existsSync,lstatSync,mkdirSync,readFileSync,renameSync,rmSync,unlinkSync} from 'node:fs';
import {join,dirname} from 'node:path';
const root = Bun.argv[2], metadataDescriptors = new Set();
function profileRoot() {return root;}
function openSync(path, ...args) {
  const fd = fs.openSync(path, ...args);
  if (String(path).endsWith('.tmp')) metadataDescriptors.add(fd);
  return fd;
}
function writeFileSync(target, ...args) {
  if (String(target).endsWith('.tmp') || metadataDescriptors.has(target)) {
    fs.writeFileSync(target, 'partial');
    throw new Error('fixture metadata write failure');
  }
  return fs.writeFileSync(target, ...args);
}
assert.throws(() => claimProfile('task', [], false), /fixture metadata write failure/);
assert.equal(fs.existsSync(`${root}.lock`), false);
assert.equal(fs.readdirSync(dirname(root)).some(name => name.endsWith('.tmp')), false);
console.log('ok');
'''
        script = self.root / 'failure.ts'
        script.write_text(source + harness)
        result = subprocess.run(['bun', str(script), str(self.profile)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(metadata.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
