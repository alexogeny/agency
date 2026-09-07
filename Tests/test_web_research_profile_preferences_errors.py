from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "Tools" / "web-research"
HARNESS = r'''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join } from 'node:path';
const [phase, workspace] = process.argv.slice(2);
const root = join(workspace, 'profile');
const ephemeral = phase.endsWith('-ephemeral');
const managed = phase !== 'unmanaged' && phase !== 'read-failure-unmanaged';
const lock = ephemeral ? join(root, '.agency.lock') : `${root}.lock`;
const userJs = join(root, 'user.js');
const originalBytes = Buffer.from('user_pref("custom.enabled", true);\r\nuser_pref("custom.name", "héllo");');
const failure = Object.assign(new Error('cannot read user.js'), {code: 'EACCES'});
const prepareFailure = new Error('cannot prepare preferences');
const writeFailure = Object.assign(new Error('cannot write user.js'), {code: 'EACCES'});
let actualReadFailure: unknown;
let reads = 0, closes = 0;
const descriptors = new Set<number>();
function profileRoot() { return root; }
const mkdirSync = fs.mkdirSync, existsSync = fs.existsSync, rmSync = fs.rmSync, unlinkSync = fs.unlinkSync;
function openSync(...args) { const descriptor = fs.openSync(...args); descriptors.add(descriptor); return descriptor; }
function closeSync(descriptor) { closes++; fs.closeSync(descriptor); descriptors.delete(descriptor); }
function readFileSync(path, ...args) {
  if (path === userJs) {
    reads++;
    if (phase.startsWith('read-failure')) throw failure;
  }
  try { return fs.readFileSync(path, ...args); }
  catch (error) { actualReadFailure = error; throw error; }
}
function writeFileSync(path, ...args) {
  if (path === userJs && phase === 'write-failure') throw writeFailure;
  return fs.writeFileSync(path, ...args);
}
fs.mkdirSync(root);
if (phase === 'directory') fs.mkdirSync(userJs);
else if (phase !== 'new') fs.writeFileSync(userJs, originalBytes);
const transient = phase === 'prepare-failure'
  ? new Proxy([], {get(target, key) {if (key === Symbol.iterator) throw prepareFailure; return Reflect.get(target, key);}})
  : [['transient.enabled', true]];
try {
  let claimed, caught;
  try { claimed = claimProfile('fixture', transient, managed, ephemeral); }
  catch (error) { caught = error; }
  assert.equal(closes, 1);
  assert.equal(descriptors.size, 0);
  if (phase.startsWith('read-failure') || ['directory', 'prepare-failure', 'write-failure'].includes(phase)) {
    const expected = phase.startsWith('read-failure') ? failure : phase === 'directory' ? actualReadFailure : phase === 'prepare-failure' ? prepareFailure : writeFailure;
    assert.ok(expected instanceof Error);
    assert.equal(caught, expected);
    assert.equal(fs.existsSync(lock), false, 'owned lock must be removed');
    if (ephemeral) assert.equal(fs.existsSync(root), false);
    else if (phase === 'directory') assert.equal(fs.statSync(userJs).isDirectory(), true);
    else assert.deepEqual(fs.readFileSync(userJs), originalBytes);
  } else {
    assert.equal(caught, undefined);
    assert.equal(fs.existsSync(lock), true);
    if (phase === 'new') assert.equal(claimed.previousUserJs, null);
    else assert.equal(claimed.previousUserJs, originalBytes.toString());
    if (managed) assert.match(fs.readFileSync(userJs, 'utf8'), /user_pref\("transient.enabled", true\);/);
    else {
      assert.equal(reads, 1);
      assert.deepEqual(fs.readFileSync(userJs), originalBytes);
      fs.writeFileSync(userJs, 'external update');
    }
    releaseProfile(claimed);
    assert.equal(fs.existsSync(lock), false);
    if (ephemeral) assert.equal(fs.existsSync(root), false);
    else if (phase === 'new') assert.equal(fs.existsSync(userJs), false);
    else if (managed) assert.deepEqual(fs.readFileSync(userJs), originalBytes);
    else assert.equal(fs.readFileSync(userJs, 'utf8'), 'external update');
  }
  console.log('ok');
} finally {
  for (const descriptor of descriptors) fs.closeSync(descriptor);
}
'''


class WebResearchProfilePreferencesErrorsTests(unittest.TestCase):
    def run_phase(self, phase):
        source = TOOL.read_text()
        source = source[source.index("function claimProfile("):source.index("\nclass Bidi {")]
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            script = workspace / "preferences.ts"
            script.write_text(source + HARNESS)
            result = subprocess.run(["bun", script, phase, workspace], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "ok\n")

    def test_read_failures_remove_owned_locks_and_ephemeral_roots(self):
        for phase in ("read-failure", "read-failure-ephemeral", "read-failure-unmanaged", "directory"):
            with self.subTest(phase=phase):
                self.run_phase(phase)

    def test_preparation_and_write_failures_preserve_original_preferences(self):
        for phase in ("prepare-failure", "write-failure"):
            with self.subTest(phase=phase):
                self.run_phase(phase)

    def test_success_restores_existing_preferences_and_preserves_unmanaged_behavior(self):
        for phase in ("existing", "new", "unmanaged", "existing-ephemeral"):
            with self.subTest(phase=phase):
                self.run_phase(phase)


if __name__ == "__main__":
    unittest.main()
