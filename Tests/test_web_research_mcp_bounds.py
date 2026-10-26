import json
from pathlib import Path
import shutil
import subprocess

from Tests.web_research_support import (
    ROOT,
    MCP_SERVER,
    MCP_BOUNDARY,
    WebResearchTestCase,
    fixture_directory,
    source_prefix,
)


SERVER = MCP_SERVER


class McpBoundsTests(WebResearchTestCase):

    def harness(self, body):
        return self.run_harness(
            '\nimport assert from "node:assert/strict";\n' + body,
            tool=SERVER,
            boundary=MCP_BOUNDARY,
            filename='bounds.ts',
        )

    def test_reference_eviction_reloads_stable_handles_and_citations(self):
        self.harness(r'''
const first = addPageReference({url:'https://example.test/first',markdown:'evidence\nsecond',title:'First'});
const expected = pageCitation(first);
for (let i=0;i<100;i++) addPageReference({url:`https://example.test/${i}`,markdown:'😀'.repeat(50000)});
assert.ok(references.size < 100, 'full page references must be evicted under the byte budget');
for(let i=0;i<3000;i++) pageReferences.set('https://example.test/alias/'+i,first);
assert.ok(pageReferences.size < 3000, 'URL aliases must also be bounded');
assert.ok(references.retainedBytes <= referenceByteBudget);
assert.ok(pageAliases.retainedBytes <= 64*1024);
const loaded = await loadPage(first.ref_id, 'transient', '');
assert.deepEqual(pageCitation(loaded),expected);
assert.equal(loaded.ref_id,first.ref_id);
assert.equal(addPageReference({url:first.url,markdown:'updated'}).ref_id,first.ref_id);
''')

    def test_find_splits_same_page_only_once_per_command(self):
        self.harness(r'''
const page = addPageReference({url:'https://example.test/page',markdown:'alpha\nbeta'});
loadPages = async () => [{...page},{...page}];
let splits = 0;
const original = String.prototype.split;
String.prototype.split = function(...args) {if(this.toString()==='alpha\nbeta') splits++;return original.apply(this,args);};
await performFind([{ref_id:page.ref_id,pattern:'alpha'},{ref_id:page.ref_id,pattern:'beta'}],'transient','');
assert.equal(splits,1,'repeated finds must share command-local lines');
''')

    def test_common_path_keeps_references_in_memory_without_spilling(self):
        self.harness(r'''
const reference = addPageReference({url:'https://example.test/common',markdown:'evidence'});
for(let i=0;i<10;i++) addSearchReference({url:'https://example.test/'+i,title:'Title'});
assert.equal((await loadPage(reference.ref_id,'transient','')).ref_id,reference.ref_id);
assert.equal(referenceDirectory, '', 'ordinary small requests must not create a disk spill');
''')

    def test_protocol_bounds_partial_unicode_frames_and_recovers(self):
        oversized_request = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'ping',
            'params': {'text': '😀' * 20000},
        }
        oversized = json.dumps(oversized_request, ensure_ascii=False).encode()
        ping = json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}).encode()
        frames = oversized + b'\n' + ping + b'\n{'
        result = subprocess.run(['bun', SERVER], input=frames, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[0]['error']['code'], -32600)
        self.assertEqual(responses[1], {'jsonrpc': '2.0', 'id': 2, 'result': {}})
        self.assertEqual(responses[2]['error']['code'], -32700)

    def assert_pi_fixture(self, mode='lifecycle'):
        result = subprocess.run(
            [
                'bun', ROOT / 'Tests/fixtures/web_research_efficiency.ts',
                ROOT / 'Agents/pi/agency-web.ts', mode,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pi ' + mode + ' passed', result.stdout)

    def test_pi_cancel_restart_ignores_old_child_events(self):
        self.assert_pi_fixture()

    def test_pi_response_request_queue_and_deadline_bounds(self):
        modes = ('oversized', 'queue', 'deadline', 'request', 'retire', 'shutdown-wait')
        for mode in modes:
            with self.subTest(mode=mode):
                self.assert_pi_fixture(mode)

    def test_server_response_and_backend_stream_bounds(self):
        self.harness(r'''
const original=process.stdout.write.bind(process.stdout);
let frame='';
process.stdout.write=value=>{frame+=value;return true;};
write({jsonrpc:'2.0',id:19,result:{text:'x'.repeat(4*1024*1024)}});
process.stdout.write=original;
assert.equal(JSON.parse(frame).error.code,-32603);
assert.ok(Buffer.byteLength(frame)<1024);
const stream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array(65536));controller.enqueue(new Uint8Array(65536));controller.close();}});
await assert.rejects(()=>boundedStream(stream,65536),/output exceeds/);
''')

    def test_backend_deadline_terminates_worker_and_clears_state(self):
        self.harness(r'''
const timers=new Map();
const nativeTimeout=globalThis.setTimeout,nativeClear=globalThis.clearTimeout;
globalThis.setTimeout=(callback,delay)=>{const timer={callback,delay};timers.set(timer,timer);return timer;};
globalThis.clearTimeout=timer=>timers.delete(timer);
let output,finish,kills=0;
Bun.spawn=()=>({stdin:{write(){},flush:async()=>{}},
  stdout:new ReadableStream({start(controller){output=controller;}}),
  stderr:new ReadableStream({start(controller){controller.close();}}),
  exited:new Promise(resolve=>{finish=resolve;}),
  kill(signal){assert.equal(signal,'SIGTERM');kills++;output.close();finish(143);},
});
const pending=invoke(['local','fixture','--json']);
await Promise.resolve();await Promise.resolve();
const timer=[...timers.values()].find(timer=>timer.delay===150000);
assert.ok(timer);timer.callback();
await assert.rejects(pending,/deadline exceeded/);
assert.equal(kills,1);assert.equal(timers.size,0);
assert.equal(backendWorker,undefined);assert.equal(backendReader,undefined);
globalThis.setTimeout=nativeTimeout;globalThis.clearTimeout=nativeClear;
''')

    def test_session_spill_is_removed_on_graceful_exit(self):
        source = source_prefix(SERVER, MCP_BOUNDARY)
        body = "\nfor(let i=0;i<40;i++)addPageReference({url:'https://example.test/'+i,markdown:'😀'.repeat(50000)});\nconsole.log(referenceDirectory);\nsetInterval(()=>{},1000);\n"
        with fixture_directory() as directory:
            path = directory / 'spill.ts'
            path.write_text(source + body)
            for graceful in (True, False):
                with self.subTest(graceful=graceful):
                    child = subprocess.Popen(
                        ['bun', path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    spill = Path(child.stdout.readline().strip())
                    self.assertTrue(spill.is_dir())
                    if graceful:
                        child.terminate()
                    else:
                        child.kill()
                    _, errors = child.communicate(timeout=10)
                    if graceful:
                        self.assertEqual(child.returncode, 0, errors)
                        self.assertFalse(spill.exists())
                    else:
                        self.assertTrue(
                            spill.exists(),
                            'SIGKILL cannot run exit cleanup; this limitation is documented',
                        )
                        shutil.rmtree(spill)

    def test_default_backend_reuses_one_bun_process_across_local_queries(self):
        self.harness(r'''
let starts=0,output,finish;
Bun.spawn=arguments_=>{
  assert.equal(arguments_[1],'worker');starts++;
  return {stdin:{write(frame){const request=JSON.parse(frame);output.enqueue(Buffer.from(JSON.stringify({result:{query:request.args[1],results:[{url:'https://example.test/'+request.args[1]}]}})+'\n'));},flush:async()=>{}},
    stdout:new ReadableStream({start(controller){output=controller;}}),stderr:new ReadableStream({start(controller){controller.close();}}),
    exited:new Promise(resolve=>{finish=resolve;}),kill(){output.close();finish(0);},
  };
};
const first=await invoke(['local','one','--json']);
const second=await invoke(['local','two','--json']);
assert.equal(first.query,'one');assert.equal(second.query,'two');
assert.equal(starts,1,'local commands must share the MCP-owned Bun worker');
await closeBackendWorker();
''')

    def test_protocol_waits_for_output_drain_before_next_frame(self):
        source = SERVER.read_text()
        instrumentation = r'''
import assert from 'node:assert/strict';
let blocked=false;
Object.defineProperty(process.stdout,'writableNeedDrain',{get:()=>blocked});
const nativeHandle=handle;
handle=async message=>{
  assert.equal(blocked,false,'next request ran before output drained');
  await nativeHandle(message);
  blocked=true;
  setImmediate(()=>{blocked=false;process.stdout.emit('drain');});
};
'''
        source = source.replace('let inputBuffer = "";', instrumentation + '\nlet inputBuffer = "";', 1)
        with fixture_directory() as directory:
            path = directory / 'backpressure.ts'
            path.write_text(source)
            payload = ''.join(
                json.dumps({'jsonrpc': '2.0', 'id': i, 'method': 'ping'}) + '\n'
                for i in range(3)
            )
            result = subprocess.run(
                ['bun', path], input=payload, capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        expected = [{'jsonrpc': '2.0', 'id': i, 'result': {}} for i in range(3)]
        self.assertEqual(responses, expected)
