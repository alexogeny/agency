from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / 'Tools' / 'web-research'
HARNESS = r'''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join } from 'node:path';
const phase = Bun.argv[2], workspace = Bun.argv[3];
const ephemeral = phase === 'write-failure-ephemeral';
const root = join(workspace, 'profile'), lock = ephemeral ? join(root, '.agency.lock') : `${root}.lock`;
const denied = Object.assign(new Error('permission denied'), { code: 'EACCES' });
const writeFailure = Object.assign(new Error('lock write failed'), { code: 'ENOSPC' });
const ownerDenied = Object.assign(new Error('owner probe denied'), { code: 'EPERM' });
const stale = Object.assign(new Error('owner gone'), { code: 'ESRCH' });
const stopped = new Error('bounded recursion proof stopped');
let roots = 0, attempts = 0, writes = 0, closes = 0, unlinks = 0;
const descriptors = new Set();
function profileRoot() { if (++roots > 4) throw stopped; return root; }
const mkdirSync = fs.mkdirSync, existsSync = fs.existsSync, rmSync = fs.rmSync;
function openSync(...args) {
  attempts++;
  if (phase === 'open-denied') throw denied;
  const fd = fs.openSync(...args); descriptors.add(fd); return fd;
}
function writeFileSync(path, ...args) {
  if (typeof path === 'number') { writes++; if (phase.startsWith('write-failure')) throw writeFailure; }
  return fs.writeFileSync(path, ...args);
}
function closeSync(fd) { closes++; fs.closeSync(fd); descriptors.delete(fd); }
function readFileSync(path, ...args) {
  if (path === lock && phase === 'read-denied') throw denied;
  return fs.readFileSync(path, ...args);
}
function unlinkSync(path) {
  unlinks++;
  if (phase === 'unlink-denied') throw denied;
  return fs.unlinkSync(path);
}
const originalKill = process.kill;
process.kill = (owner, signal) => {
  assert.equal(signal, 0);
  if (phase === 'owner-denied') throw ownerDenied;
  if (!Number.isSafeInteger(owner) || owner <= 0) throw Object.assign(new Error('invalid owner'), { code: 'EINVAL' });
  if (phase === 'stale' || phase === 'unlink-denied') throw stale;
  return true;
};
const existing = ['live', 'stale', 'unlink-denied', 'owner-denied', 'read-denied', 'invalid-owner'].includes(phase);
if (existing) { fs.mkdirSync(root); fs.writeFileSync(lock, phase === 'invalid-owner' ? 'not-a-pid' : '43210'); }
try {
  let caught, claimed;
  try { claimed = claimProfile('fixture', [], false, ephemeral); } catch (error) { caught = error; }
  if (phase === 'new' || phase === 'stale') {
    assert.equal(caught, undefined);
    assert.equal(fs.readFileSync(lock, 'utf8'), String(process.pid));
    assert.equal(closes, 1);
    assert.equal(attempts, phase === 'new' ? 1 : 2);
    assert.equal(unlinks, phase === 'new' ? 0 : 1);
    assert.equal(claimed.root, root);
  } else if (phase.startsWith('write-failure')) {
    assert.equal(caught, writeFailure);
    assert.equal(attempts, 1);
    assert.equal(closes, 1);
    assert.equal(descriptors.size, 0);
    assert.equal(fs.existsSync(lock), false);
    if (ephemeral) assert.equal(fs.existsSync(root), false);
  } else {
    assert.ok(caught instanceof Error);
    if (['open-denied', 'unlink-denied', 'read-denied'].includes(phase)) assert.equal(caught, denied);
    if (phase === 'owner-denied') assert.equal(caught, ownerDenied);
    if (phase === 'live') assert.match(caught.message, /already in use by process 43210/);
    assert.equal(attempts, 1, 'failed acquisition must not recurse');
    assert.equal(writes, 0);
    if (existing) assert.equal(fs.readFileSync(lock, 'utf8'), phase === 'invalid-owner' ? 'not-a-pid' : '43210');
    if (phase !== 'unlink-denied') assert.equal(unlinks, 0);
  }
  console.log('ok');
} finally {
  process.kill = originalKill;
  for (const fd of descriptors) fs.closeSync(fd);
}
'''


class WebResearchProfileClaimErrorsTests(unittest.TestCase):
    def run_phase(self, phase):
        source = TOOL.read_text()
        source = source[source.index('function claimProfile('):source.index('\nfunction releaseProfile(')]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'claim.ts'
            script.write_text(source + HARNESS)
            result = subprocess.run(['bun', script, phase, root], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'ok\n')

    def test_open_permission_error_is_returned_once(self):
        self.run_phase('open-denied')

    def test_lock_write_failure_closes_descriptor_and_removes_owned_lock(self):
        for phase in ('write-failure', 'write-failure-ephemeral'):
            with self.subTest(phase=phase):
                self.run_phase(phase)

    def test_stale_lock_unlink_error_is_returned_once(self):
        self.run_phase('unlink-denied')

    def test_unknown_owner_and_read_errors_do_not_remove_lock(self):
        for phase in ('owner-denied', 'read-denied', 'invalid-owner'):
            with self.subTest(phase=phase):
                self.run_phase(phase)

    def test_new_live_and_known_stale_lock_controls(self):
        for phase in ('new', 'live', 'stale'):
            with self.subTest(phase=phase):
                self.run_phase(phase)
