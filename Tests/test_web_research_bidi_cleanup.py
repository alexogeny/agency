import os
from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / 'Tools' / 'web-research'
HARNESS = r'''
import assert from 'node:assert/strict';
const nativeSetTimeout = globalThis.setTimeout;
const nativeClearTimeout = globalThis.clearTimeout;
const NativeWebSocket = globalThis.WebSocket;
const activeTimers = new Set();
class FakeWebSocket extends EventTarget {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = 1;
  sent = [];
  sendError = null;
  closeCalls = 0;
  openListeners = new Set();
  addEventListener(type, listener, options) { if (type === 'open') this.openListeners.add(listener); super.addEventListener(type, listener, options); }
  removeEventListener(type, listener, options) { if (type === 'open') this.openListeners.delete(listener); super.removeEventListener(type, listener, options); }
  send(value) { if (this.sendError) throw this.sendError; this.sent.push(JSON.parse(value)); }
  close() { this.closeCalls++; this.readyState = 3; }
  emit(type, message) { this.dispatchEvent(type === 'message' ? new MessageEvent(type, { data: JSON.stringify(message) }) : new Event(type)); }
}
const clients = [];
function make() { const client = new Bidi('ws://fixture.invalid'); clients.push(client); return client; }
async function settled(promise) {
  let timer;
  try {
    return await Promise.race([promise.then(value => ({ value }), error => ({ error })), new Promise(resolve => { timer = nativeSetTimeout(() => resolve({ pending: true }), 100); })]);
  } finally { nativeClearTimeout(timer); }
}
globalThis.WebSocket = FakeWebSocket;
globalThis.setTimeout = (callback, delay) => {
  const timer = nativeSetTimeout(() => { activeTimers.delete(timer); callback(); }, delay);
  activeTimers.add(timer); return timer;
};
globalThis.clearTimeout = timer => { activeTimers.delete(timer); nativeClearTimeout(timer); };
try {
  const scenario = Bun.argv[2];
  if (['explicit', 'close', 'error'].includes(scenario)) {
    const bidi = make();
    const pending = [bidi.command('one', {}, 10000), bidi.command('two', {}, 10000)].map(p => p.catch(error => error));
    assert.equal(activeTimers.size, 2);
    if (scenario === 'explicit') bidi.close(); else bidi.socket.emit(scenario);
    assert.equal(bidi.pending.size, 0, 'pending requests must be removed immediately');
    assert.equal(activeTimers.size, 0, 'command timers must be cleared immediately');
    for (const promise of pending) {
      const result = await settled(promise);
      assert.ok(result.value instanceof Error, 'command must reject promptly');
    }
    const sent = bidi.socket.sent.length;
    const after = await settled(bidi.command('after-close', {}, 10000));
    assert.ok(after.error instanceof Error);
    assert.equal(bidi.socket.sent.length, sent);
    assert.equal(activeTimers.size, 0);
    bidi.socket.emit('close');
    bidi.close();
    assert.equal(bidi.pending.size, 0);
  } else if (scenario === 'ready') {
    const bidi = make();
    assert.equal(bidi.socket.readyState, FakeWebSocket.OPEN);
    const opening = settled(bidi.open());
    assert.equal(bidi.socket.sent.length, 1, 'already-open socket must send session.new immediately');
    assert.equal(bidi.socket.sent[0].method, 'session.new');
    bidi.socket.emit('message', { id: 1, result: { capabilities: { ready: true } } });
    assert.deepEqual(await opening, { value: undefined });
    assert.deepEqual(bidi.capabilities, { ready: true });
    assert.equal(bidi.socket.openListeners.size, 0);
    assert.equal(bidi.openingRejects.size, 0);
    bidi.close();
  } else if (scenario === 'startup') {
    for (const action of ['explicit', 'close', 'error']) {
      const bidi = make();
      bidi.socket.readyState = FakeWebSocket.CONNECTING;
      const waiting = settled(bidi.open());
      if (action === 'explicit') bidi.close(); else bidi.socket.emit(action);
      assert.ok((await waiting).error instanceof Error, `startup ${action} must reject promptly`);
      assert.equal(bidi.socket.openListeners.size, 0);
      assert.equal(bidi.openingRejects.size, 0);
      assert.ok((await settled(bidi.open())).error instanceof Error, 'open after close must reject promptly');
      assert.equal(bidi.socket.openListeners.size, 0);
      assert.equal(bidi.openingRejects.size, 0);
      assert.equal(bidi.socket.sent.length, 0);
    }
    const bidi = make();
    bidi.socket.readyState = FakeWebSocket.CONNECTING;
    const opened = bidi.open();
    bidi.socket.readyState = FakeWebSocket.OPEN;
    bidi.socket.emit('open');
    await Promise.resolve();
    assert.equal(bidi.socket.openListeners.size, 0);
      assert.equal(bidi.openingRejects.size, 0);
    assert.equal(bidi.socket.sent[0].method, 'session.new');
    bidi.socket.emit('message', { id: 1, result: { capabilities: { ready: true } } });
    await opened;
    assert.deepEqual(bidi.capabilities, { ready: true });
    bidi.close();
  } else if (scenario === 'closing') {
    for (const state of [FakeWebSocket.CLOSING, FakeWebSocket.CLOSED]) {
      const bidi = make();
      bidi.socket.readyState = state;
      assert.ok((await settled(bidi.command('late', {}, 10000))).error instanceof Error);
      assert.equal(bidi.socket.sent.length, 0);
      assert.equal(bidi.pending.size, 0);
      assert.equal(activeTimers.size, 0);
    }
  } else if (scenario === 'send') {
    const bidi = make();
    const failure = new Error('send failed');
    bidi.socket.sendError = failure;
    assert.equal((await settled(bidi.command('broken', {}, 10000))).error, failure);
    assert.equal(bidi.pending.size, 0, 'synchronous send failure must remove request');
    assert.equal(activeTimers.size, 0);
    bidi.socket.sendError = null;
    const circular = {}; circular.self = circular;
    assert.ok((await settled(bidi.command('circular', circular, 10000))).error instanceof TypeError);
    assert.equal(bidi.pending.size, 0);
    assert.equal(activeTimers.size, 0);
  } else if (scenario === 'messages') {
    const bidi = make();
    const seen = [];
    const off = bidi.on('event', params => seen.push(params));
    const success = bidi.command('success', {}, 10000);
    bidi.socket.emit('message', { id: 1, result: { answer: 42 } });
    assert.deepEqual(await success, { answer: 42 });
    assert.equal(activeTimers.size, 0);
    const error = bidi.command('error', {}, 10000).catch(error => error);
    bidi.socket.emit('message', { id: 2, type: 'error', error: 'invalid', message: 'bad parameter' });
    assert.equal((await error).message, 'invalid: bad parameter');
    bidi.socket.emit('message', { method: 'event', params: { first: true } });
    off();
    bidi.socket.emit('message', { method: 'event', params: { second: true } });
    bidi.socket.emit('message', { id: 999, result: {} });
    assert.deepEqual(seen, [{ first: true }]);
    const timeout = await settled(bidi.command('slow', {}, 5));
    assert.equal(timeout.error.message, 'slow timed out');
    assert.equal(bidi.pending.size, 0);
    assert.equal(activeTimers.size, 0);
    bidi.close();
  } else if (scenario === 'local' || scenario === 'local-ready') {
    globalThis.WebSocket = NativeWebSocket;
    let peer;
    const server = Bun.serve({ hostname: '127.0.0.1', port: 0,
      fetch(request, server) { if (server.upgrade(request)) return; return new Response('upgrade required', { status: 400 }); },
      websocket: {
        open(socket) { peer = socket; },
        message(socket, raw) {
          const request = JSON.parse(String(raw));
          if (request.method === 'session.new') socket.send(JSON.stringify({ id: request.id, result: { capabilities: { browserName: 'fixture' } } }));
          else socket.close();
        },
      },
    });
    const bidi = new Bidi(`ws://127.0.0.1:${server.port}`);
    clients.push(bidi);
    try {
      if (scenario === 'local-ready') {
        await new Promise(resolve => bidi.socket.addEventListener('open', resolve, { once: true }));
        assert.equal(bidi.socket.readyState, NativeWebSocket.OPEN);
      }
      assert.deepEqual(await settled(bidi.open()), { value: undefined });
      assert.deepEqual(bidi.capabilities, { browserName: 'fixture' });
      const result = await settled(bidi.command('disconnect', {}, 10000));
      assert.ok(result.error instanceof Error, 'local disconnect must reject without timeout');
      assert.equal(bidi.pending.size, 0);
      assert.equal(activeTimers.size, 0);
    } finally { bidi.close(); peer?.close(); server.stop(true); }
  }
  console.log('ok');
} finally {
  for (const bidi of clients) for (const request of bidi.pending.values()) nativeClearTimeout(request.timer);
  for (const timer of activeTimers) nativeClearTimeout(timer);
  globalThis.setTimeout = nativeSetTimeout;
  globalThis.clearTimeout = nativeClearTimeout;
  globalThis.WebSocket = NativeWebSocket;
}
'''


class WebResearchBidiCleanupTests(unittest.TestCase):
    def run_scenario(self, scenario):
        source = TOOL.read_text()
        source = source[source.index('class Bidi {'):source.index('\ntype BrowserOptions = {')]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'bidi.ts'
            script.write_text(source + '\n' + HARNESS)
            result = subprocess.run(['bun', script, scenario], text=True, capture_output=True, timeout=10,
                env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(root / 'data')})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'ok\n')

    def test_explicit_close_clears_pending_without_waiting_for_close_event(self):
        self.run_scenario('explicit')

    def test_remote_close_clears_pending_and_rejects_future_commands(self):
        self.run_scenario('close')

    def test_error_clears_pending_and_rejects_future_commands(self):
        self.run_scenario('error')

    def test_synchronous_send_and_serialization_failures_clear_pending(self):
        self.run_scenario('send')

    def test_success_protocol_error_events_and_normal_timeout(self):
        self.run_scenario('messages')

    def test_local_websocket_disconnect_after_successful_session_startup(self):
        self.run_scenario('local')

    def test_commands_during_closing_or_closed_state_fail_before_send(self):
        self.run_scenario('closing')

    def test_startup_close_error_and_already_closed_remove_open_listener(self):
        self.run_scenario('startup')

    def test_already_open_socket_starts_session_without_another_open_event(self):
        self.run_scenario('ready')

    def test_local_websocket_session_can_start_after_open_event(self):
        self.run_scenario('local-ready')
