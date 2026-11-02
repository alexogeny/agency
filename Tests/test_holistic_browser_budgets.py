"""Browser/MCP resource acceptance tests; actual function bodies, offline fixtures.

No browser, network socket or external service starts. Harnesses isolate the
current TypeScript functions at filesystem/stream/process boundaries. Frame,
read-chunk and queue ceilings are explicit proposed acceptance budgets.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'Tools'
sys.path.insert(0, str(TOOLS))
import agency_browser as browser


class HolisticBrowserBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def function(self, filename, start, end):
        source = (TOOLS / filename).read_text()
        return source[source.index(start):source.index(end, source.index(start))]

    def bun(self, source):
        path = self.base / 'harness.ts'
        path.write_text(source)
        executable = shutil.which('bun')
        self.assertIsNotNone(executable, 'Bun is required for actual TypeScript execution')
        result = subprocess.run([executable, path], capture_output=True, text=True,
                                timeout=10, env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(self.base / 'data')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_over_budget_backend_stream_is_canceled(self):
        function = self.function('web-research-mcp', 'async function boundedStream(', '\nasync function closeBackendWorker(')
        result = self.bun(function + '''
let canceled=0, message='';
const stream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array(8));controller.enqueue(new Uint8Array(8));},cancel(){canceled++;}});
try { await boundedStream(stream,10); } catch(error) { message=String(error); }
const small=await boundedStream(new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('valid'));controller.close();}}),10);
console.log(JSON.stringify({canceled,message,small,locked:stream.locked}));
''')
        self.assertIn('exceeds 10 bytes', result['message'])
        self.assertEqual(result['small'], 'valid')
        self.assertFalse(result['locked'])
        self.assertEqual(result['canceled'], 1, 'Over-budget reader released its lock without canceling upstream work')

    def test_invalid_batch_query_does_not_buffer_entire_oversized_line(self):
        path = self.base / 'queries.txt'
        path.write_text('x' * (1024 * 1024))
        valid_path = self.base / 'valid-queries.txt'
        valid_path.write_text('valid query\n')
        functions = self.function('web-research', 'function batchQueries(', '\nfunction completedBatchQueries(')
        functions += self.function('web-research', 'function* utf8FileLines(', '\nfunction completedBatchUrls(')
        result = self.bun('''
import {realpathSync,statSync,openSync,closeSync,readSync as readReal} from 'node:fs';
import {resolve} from 'node:path';
import {StringDecoder} from 'node:string_decoder';
let readBytes=0;
function readSync(...args:any[]){const n=(readReal as any)(...args);readBytes+=n;return n;}
function fail(message:string):never {throw new Error(message);}
''' + functions + '\nconst valid=batchQueries(' + json.dumps(str(valid_path)) + ');readBytes=0;let message="";try{batchQueries(' + json.dumps(str(path)) + ''');}catch(error){message=String(error);}
console.log(JSON.stringify({message,readBytes,queries:valid.queries}));
''')
        self.assertEqual(result['queries'], ['valid query'])
        self.assertIn('at most 1000 characters', result['message'])
        self.assertLessEqual(result['readBytes'], 65536,
                             f'Invalid 1000-character query read {result["readBytes"]} bytes before rejection')

    def test_capture_manifest_collision_work_does_not_grow_quadratically(self):
        function = self.function('web-research', 'function storedCapture(', '\nfunction checkedCaptureId(')
        result = self.bun('''
import {createHash} from 'node:crypto';
import {join} from 'node:path';
const fixedDate=globalThis.Date;
class Date extends fixedDate {constructor(){super('2026-11-02T00:00:00Z');}}
const pageCaptures=new WeakMap<any,any>();
function evidenceJson(value:any,...args:any[]){return JSON.stringify(value,...args);}
function captureInputForStorage(value:any){return value;}
function captureDirectories(){return {objects:'objects',manifests:'manifests'};}
function redactedOutputUrl(value:any){return value;}
function fusePageCapture(value:any,hash:string){return {url:value.requested_url,hash};}
let files=new Map<string,string>(), probes=0;
function existsSync(path:string){probes++;return files.has(path);}
function readFileSync(path:string){return Buffer.from(files.get(path)!);}
function writeFileSync(path:string,value:string,options:any){if(files.has(path)&&options?.flag==='wx')throw Error('collision');files.set(path,value);}
''' + function + '''
function workload(n:number){files=new Map();probes=0;const ids=[];for(let i=0;i<n;i++){const page={url:'https://example.test',sources:[]};pageCaptures.set(page,{requested_url:page.url,captures:[{url:page.url}],options:{}});ids.push(storedCapture(page,{bidi:{capabilities:{browserVersion:'fixture'}}}).capture_id);}return {probes,unique:new Set(ids).size};}
console.log(JSON.stringify({small:workload(16),large:workload(32)}));
''')
        self.assertEqual(result['small']['unique'], 16)
        self.assertEqual(result['large']['unique'], 32)
        small, large = result['small']['probes'], result['large']['probes']
        self.assertLessEqual(large, 2.6 * small,
                             f'Doubled captures under same timestamp probed {large}/{small} paths')

    def test_capture_replay_does_not_materialize_whole_object_for_hash(self):
        data = {'schema':'agency/web-capture-input/1', 'requested_url':'https://example.test/',
                'captures':[{'url':'https://example.test/'}], 'access_states':[], 'actions':[],
                'scroll_targets':[], 'network':[], 'frames':[],
                'options':{'max_content_chars':1000,'max_links':100}, 'padding':'x' * 262144}
        serialized = json.dumps(data).encode()
        digest = hashlib.sha256(serialized).hexdigest()
        manifests, objects = self.base / 'manifests', self.base / 'objects'
        manifests.mkdir(); objects.mkdir()
        identity = 'a' * 64
        (manifests / (identity + '.json')).write_text(json.dumps({'schema':'agency/web-capture-manifest/1','id':identity,'object_sha256':digest}))
        (objects / (digest + '.json')).write_bytes(serialized)
        function = self.function('web-research', 'function checkedCaptureId(', '\nfunction browserOptions(')
        result = self.bun('''
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {readFileSync as readReal,existsSync} from 'node:fs';
let largest=0;
function readFileSync(...args:any[]){const value=(readReal as any)(...args);largest=Math.max(largest,Buffer.byteLength(value));return value;}
function fail(message:string):never{throw Error(message);}
function fusePageCapture(input:any,hash:string){return {url:input.requested_url,hash};}
function captureDirectories(){return ''' + json.dumps({'manifests':str(manifests),'objects':str(objects)}) + ';}\n' + function + '\nconst result=loadedCapture(' + json.dumps(identity) + ''');console.log(JSON.stringify({largest,id:result.page.capture_id,url:result.page.url,hash:result.page.hash}));
''')
        self.assertEqual(result['id'], identity)
        self.assertEqual(result['url'], data['requested_url'])
        self.assertEqual(result['hash'], digest)
        self.assertLessEqual(result['largest'], 65536,
                             f'Capture replay materialized a {result["largest"]}-byte file read')

    def test_bridge_token_limit_is_checked_before_whole_file_read(self):
        token = self.base / 'token'
        token.write_text('x' * 262144)
        function = self.function('agent_work_bridge.ts', 'async function websocketRpc(', '\nasync function main(')
        result = self.bun('''
import {readFileSync as readReal} from 'node:fs';
let largest=0,sockets=0;
function readFileSync(...args:any[]){const value=(readReal as any)(...args);largest=Math.max(largest,Buffer.byteLength(value));return value;}
class WebSocket{constructor(...args:any[]){sockets++;throw Error('must not connect');}}
''' + function + '\nlet message="";try{await websocketRpc("ws://127.0.0.1:1234",' + json.dumps(str(token)) + ''');}catch(error){message=String(error);}
console.log(JSON.stringify({message,largest,sockets}));
''')
        self.assertIn('Invalid app-server token file', result['message'])
        self.assertEqual(result['sockets'], 0)
        self.assertLessEqual(result['largest'], 4097,
                             f'Bridge allocated {result["largest"]} credential bytes before its 4096-character gate')

    def bridge(self, scenario):
        classes = self.function('agent_work_bridge.ts', 'export class CodexDelivery', '\nasync function websocketRpc(')
        main = self.function('agent_work_bridge.ts', 'async function main(', '\nif (import.meta.main)')
        return self.bun('''
import {EventEmitter} from 'node:events';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const randomUUID=()=> 'fixture-uuid';
const Bun={argv:['bun','bridge','--client','codex','--session','fixture','--url','ws://127.0.0.1:1234']};
const input=new EventEmitter() as any;input.close=()=>{};
const process=new EventEmitter() as any;process.stdin=input;
const watcher=new EventEmitter() as any;watcher.stdout=new EventEmitter();watcher.stdin=new EventEmitter();const acknowledgements:any[]=[];watcher.stdin.write=(line:string)=>{acknowledgements.push(JSON.parse(line));return true;};watcher.kill=()=>true;
let pauses=0,deliveries=0,unblock:any,blocked=true;watcher.stdout.pause=()=>{pauses++;};watcher.stdout.resume=()=>{};
const forwards:any[]=[],diagnostics:string[]=[];
const console={log:(...args:any[])=>globalThis.console.log(...args),error:(...args:any[])=>diagnostics.push(args.join(' '))};
function spawn(...args:any[]){return watcher;}
function createInterface(options:any){return options.input;}
async function websocketRpc(...args:any[]){return {send:(value:any)=>forwards.push(value),close:()=>{},rpc:async(method:string)=>{if(method==='thread/read')return {thread:{status:{type:'idle'}}};if(method==='turn/start'){deliveries++;if(blocked)return new Promise(resolve=>{unblock=()=>{blocked=false;resolve({});};});return {};}return {};}};}
''' + classes + main + '\nawait main();\n' + scenario)

    def test_bridge_stdin_forwarding_rejects_over_budget_frames(self):
        result = self.bridge('''
input.emit('line',JSON.stringify({method:'valid',params:{value:'small'}}));
input.emit('line',JSON.stringify({method:'oversized',params:{value:'x'.repeat(262144)}}));
console.log(JSON.stringify({forwarded:forwards.map(value=>({method:value.method,bytes:Buffer.byteLength(JSON.stringify(value))})),diagnostics}));
''')
        self.assertTrue(any(frame['method'] == 'valid' for frame in result['forwarded']))
        largest = max(frame['bytes'] for frame in result['forwarded'])
        self.assertLessEqual(largest, 65536,
                             f'Bridge forwarded a {largest}-byte client frame without enforcing a frame budget')
        self.assertTrue(result['diagnostics'], 'Oversized frames must be explicitly rejected, not silently dropped')

    def test_bridge_watcher_applies_backpressure_while_delivery_is_blocked(self):
        result = self.bridge('''
let sent=0;for(let i=0;i<64;i++){watcher.stdout.emit('line',JSON.stringify({event:'messages',id:String(i),context:'x'.repeat(32768)}));sent++;if(pauses)break;}
await new Promise(resolve=>setImmediate(resolve));
const atBlock=deliveries;unblock();
for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));
console.log(JSON.stringify({pauses,deliveries,atBlock,sent,acknowledgements,diagnostics}));
''')
        self.assertEqual(result['atBlock'], 1, 'Fixture must block the first delivery while later batches queue')
        acknowledged = {item['delivered'] for item in result['acknowledgements']}
        self.assertEqual(len(acknowledged) + len(result['diagnostics']), result['sent'],
                         'Every batch must be delivered or explicitly rejected, with no silent drops')
        self.assertTrue(result['pauses'] > 0 or result['deliveries'] <= 16,
                        f'Bridge accepted {result["deliveries"]} queued deliveries without pausing or rejecting overflow')

    def test_browser_json_fetch_enforces_response_budget_before_full_text(self):
        client = browser.MCPClient('http://127.0.0.1:1234')
        captured = []

        class Pacer:
            def run(self, url, operation):
                return operation()

        def call(tool, arguments):
            captured.append(arguments['function'])
            return {'content':[{'type':'text','text':'### Result\n{"status":200,"data":{"ok":true}}'}]}

        with patch.object(client, 'call', side_effect=call):
            self.assertEqual(client.fetch_json('https://example.test/api/items', Pacer(),
                                              'https://example.test/api/')['data'], {'ok':True})
        function = captured[0]
        result = self.bun('''
let textCalls=0;const location={origin:'https://example.test'};
let payload=JSON.stringify({data:'x'.repeat(16*1024*1024+1)});
async function fetch(...args:any[]){return {ok:true,status:200,headers:{get:(name:string)=>name.toLowerCase()==='content-length'?String(Buffer.byteLength(payload)):null},body:new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(payload));controller.close();}}),text:async()=>{textCalls++;return payload;}};}
const operation=(''' + function + ''');
let result:any,error='';try{result=await operation();}catch(value){error=String(value);}
const overBudgetTextCalls=textCalls;payload=JSON.stringify({ok:true});const small=await operation();
console.log(JSON.stringify({textCalls:overBudgetTextCalls,returnedBytes:result?Buffer.byteLength(JSON.stringify(result)):0,error,small:small.data}));
''')
        self.assertEqual(result['small'], {'ok': True})
        self.assertTrue(result['error'] or result['returnedBytes'] <= browser.MAX_RESPONSE,
                        f'Browser-side JSON fetch returned {result["returnedBytes"]} bytes beyond its response budget')
        self.assertEqual(result['textCalls'], 0,
                         'Browser-side JSON fetch calls response.text() with no bounded streaming read')


if __name__ == '__main__':
    unittest.main()
