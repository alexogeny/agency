from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / 'Tools' / 'web-research'
HARNESS = r'''
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { join } from 'node:path';
const phase = Bun.argv[2], root = Bun.argv[3], lock = join(root, 'profile.lock');
const failure = new Error('forced browser command failure');
const nativeSpawn = Bun.spawn;
let released = 0, kills = 0, unrefs = 0;
const killSignals = [];
let actualChild;
const messages = [];
const info = text => messages.push(text);
const sleep = ms => Bun.sleep(ms);
const checkedProfile = value => value;
const checkedUrl = value => new URL(value);
function fail(message) { throw new Error(message); }
function takeOption(args, key, fallback) {
  const index = args.indexOf(key);
  return index < 0 ? fallback : args.splice(index, 2)[1];
}
function takeFlag(args, key) {
  const index = args.indexOf(key);
  if (index < 0) return false;
  args.splice(index, 1); return true;
}
function claimProfile(profile, preferences, manage) {
  assert.equal(profile, 'fixture');
  assert.deepEqual(preferences, []);
  assert.equal(manage, false);
  fs.writeFileSync(lock, String(process.pid));
  return { root, lock };
}
function releaseProfile(claimed) {
  assert.equal(claimed.lock, lock);
  released++;
  fs.unlinkSync(lock);
}
function writeFileSync(path, value, options) {
  if (phase === 'handoff' || phase === 'real-handoff') throw failure;
  return fs.writeFileSync(path, value, options);
}
let resolveExited;
const fakeChild = {
  pid: 43210,
  exitCode: phase === 'attached' ? 0 : phase === 'nonzero' ? 7 : null,
  exited: phase === 'attached' ? Promise.resolve(0) : phase === 'nonzero' ? Promise.resolve(7) : new Promise(resolve => { resolveExited = resolve; }),
  kill() { kills++; this.exitCode = 143; resolveExited(143); },
  unref() { unrefs++; },
};
Bun.spawn = (command, options) => {
  assert.deepEqual(command, ['firefox', '--no-remote', '--profile', root, 'about:blank']);
  assert.equal(options.stdin, ['attached', 'nonzero'].includes(phase) ? 'inherit' : 'ignore');
  if (phase === 'spawn') throw failure;
  if (phase === 'real-handoff') {
    actualChild = nativeSpawn([process.execPath, '-e', 'await Bun.sleep(30000)'], { stdin: 'ignore', stdout: 'ignore', stderr: 'ignore' });
    const nativeKill = actualChild.kill.bind(actualChild);
    actualChild.kill = (...args) => { kills++; killSignals.push(args[0]); return nativeKill(...args); };
    return actualChild;
  }
  return fakeChild;
};
try {
  let caught;
  const detach = !['attached', 'nonzero'].includes(phase);
  try { await commandBrowser(['--profile', 'fixture', ...(detach ? ['--detach'] : [])]); }
  catch (error) { caught = error; }
  if (phase === 'detached') {
    assert.equal(caught, undefined);
    assert.equal(released, 0);
    assert.equal(kills, 0);
    assert.equal(unrefs, 1);
    assert.equal(fs.readFileSync(lock, 'utf8'), String(fakeChild.pid));
    assert.equal(fakeChild.exitCode, null);
    assert.deepEqual(messages, ["opened detached persistent profile 'fixture' in Firefox"]);
  } else {
    assert.equal(released, 1, 'failed or attached browser must release profile');
    assert.equal(fs.existsSync(lock), false);
    if (phase === 'attached') assert.equal(caught, undefined);
    else if (phase === 'nonzero') assert.equal(caught.message, 'Firefox exited with status 7');
    else assert.equal(caught, failure);
    if (phase === 'handoff' || phase === 'real-handoff') {
      if (actualChild) {
        assert.ok(kills === 1 || kills === 2);
        assert.equal(killSignals[0], undefined);
        if (kills === 2) assert.equal(killSignals[1], 9);
        assert.ok(actualChild.exitCode !== null || actualChild.signalCode);
        await actualChild.exited;
      } else {
        assert.equal(kills, 1);
        assert.notEqual(fakeChild.exitCode, null);
      }
      assert.deepEqual(messages, []);
    } else assert.equal(kills, 0);
    if (!detach) assert.deepEqual(messages, ["opened persistent profile 'fixture'; close Firefox to continue"]);
  }
  console.log('ok');
} finally {
  Bun.spawn = nativeSpawn;
  if (actualChild && actualChild.exitCode === null && !actualChild.signalCode) { actualChild.kill(9); await actualChild.exited; }
}
'''


class WebResearchBrowserCommandCleanupTests(unittest.TestCase):
    def run_phase(self, phase):
        source = TOOL.read_text()
        helper = source[source.index('async function terminateBrowserProcess('):source.index('\nasync function startBrowser(')]
        command = source[source.index('async function commandBrowser('):source.index('\nfunction help()', source.index('async function commandBrowser('))]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'browser.ts'
            script.write_text(helper + command + HARNESS)
            result = subprocess.run(['bun', script, phase, root], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'ok\n')

    def test_spawn_failure_releases_claim_and_preserves_error(self):
        self.run_phase('spawn')

    def test_failed_detached_handoff_terminates_child_and_releases_claim(self):
        self.run_phase('handoff')

    def test_real_owned_child_is_terminated_after_failed_handoff(self):
        self.run_phase('real-handoff')

    def test_successful_detached_handoff_leaves_child_and_pid_lock(self):
        self.run_phase('detached')

    def test_attached_success_and_nonzero_exit_release_profile(self):
        for phase in ('attached', 'nonzero'):
            with self.subTest(phase=phase):
                self.run_phase(phase)
