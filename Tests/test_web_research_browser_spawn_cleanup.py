import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import assert from 'node:assert/strict';
const phase = Bun.argv[2];
const actual = phase === 'persistent' || phase === 'ephemeral';
const originalClaim = claimProfile;
const originalRelease = releaseProfile;
const originalSpawn = Bun.spawn;
const originalPath = process.env.PATH;
const failure = new Error('forced spawn failure');
const restoreFailure = new Error('forced profile restoration failure');
const proxyFailure = new Error('forced proxy close failure');
let released = 0, closed = 0;
let claimed, spawnFailure, unexpectedChild;
const previous = 'user_pref("fixture.original", true);\n';
if (actual) {
  const emptyPath = join(dataRoot, 'empty-path');
  mkdirSync(emptyPath, { recursive: true });
  process.env.PATH = emptyPath;
  if (phase === 'persistent') {
    const root = profileRoot('fixture', false);
    mkdirSync(root, { recursive: true });
    writeFileSync(join(root, 'user.js'), previous);
  }
}
safeProxy = async () => ({ port: 1234, async close() {
  closed++;
  if (phase === 'proxy-failure') throw proxyFailure;
} });
claimProfile = (...args) => {
  claimed = actual ? originalClaim(...args) : { root: '/fixture' };
  return claimed;
};
releaseProfile = value => {
  assert.equal(value, claimed);
  released++;
  if (phase === 'release-failure') throw restoreFailure;
  if (actual) originalRelease(value);
};
Bun.spawn = (...args) => {
  if (!actual) throw failure;
  try {
    unexpectedChild = originalSpawn(...args);
    unexpectedChild.kill();
    throw new Error('missing-firefox fixture unexpectedly found an executable');
  }
  catch (error) { spawnFailure = error; throw error; }
};
try {
  let caught;
  try {
    await startBrowser({ headless: true, allowPrivate: false, profile: 'fixture',
      ephemeral: phase === 'ephemeral', templatePreferences: [] });
  } catch (error) { caught = error; }
  assert.equal(released, 1, 'spawn failure must release profile exactly once');
  assert.equal(closed, 1, 'spawn failure must close proxy even if profile release fails');
  assert.equal(caught, phase === 'release-failure' ? restoreFailure : phase === 'proxy-failure' ? proxyFailure : actual ? spawnFailure : failure);
  assert.ok(caught instanceof Error);
  if (actual) {
    assert.equal(spawnFailure.code, 'ENOENT');
    assert.equal(existsSync(claimed.lock), false);
    if (phase === 'ephemeral') assert.equal(existsSync(claimed.root), false);
    else assert.equal(readFileSync(claimed.userJs, 'utf8'), previous);
  }
  console.log('ok');
} finally {
  if (unexpectedChild) await unexpectedChild.exited;
  process.env.PATH = originalPath;
  if (actual && claimed && existsSync(claimed.lock)) originalRelease(claimed);
}
'''


class WebResearchBrowserSpawnCleanupTests(unittest.TestCase):
    def run_phase(self, phase):
        source = (ROOT / 'Tools' / 'web-research').read_text().split('\nconst args = Bun.argv.slice(2);', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'spawn.ts'
            script.write_text(source + HARNESS)
            environment = {**os.environ, 'WEB_RESEARCH_DATA_DIR': str(root / 'data')}
            if phase in ('persistent', 'ephemeral'):
                empty_path = root / 'empty-path'
                empty_path.mkdir()
                environment['PATH'] = str(empty_path)
            result = subprocess.run([shutil.which('bun'), script, phase], capture_output=True, text=True, timeout=10,
                env=environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'ok\n')

    def test_spawn_failure_releases_resources_and_preserves_error(self):
        self.run_phase('spawn')

    def test_profile_release_failure_still_closes_proxy_and_propagates(self):
        self.run_phase('release-failure')

    def test_proxy_close_failure_is_not_suppressed(self):
        self.run_phase('proxy-failure')

    def test_missing_firefox_restores_persistent_profile_and_unlocks(self):
        self.run_phase('persistent')

    def test_missing_firefox_removes_ephemeral_profile(self):
        self.run_phase('ephemeral')
