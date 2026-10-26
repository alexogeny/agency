import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
const source = await Bun.file(Bun.argv[2]).text();
const body = source.slice(source.indexOf('class AgencyWebClient {'), source.indexOf('\nexport default function'));
const children: any[] = [];
function spawn() {
  const child = new EventEmitter() as any;
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kills = 0;
  child.signals = [];
  child.frames = [];
  child.kill = signal => {
    child.kills++;
    child.signals.push(signal);
  };
  child.stdin = {
    write(frame, callback) {
      const request = JSON.parse(frame);
      child.frames.push(request);
      if (request.method === 'initialize') {
        const response = JSON.stringify({id:request.id,result:{}}) + '\n';
        queueMicrotask(() => child.stdout.write(response));
      }
      callback?.();
    },
  };
  children.push(child);
  return child;
}
const timers = new Map<number, {callback:()=>void, delay:number}>();
let nextTimer = 1;
const fakeTimeout = (callback, delay) => {
  const id = nextTimer++;
  timers.set(id, {callback, delay});
  return id;
};
const fakeClear = id => timers.delete(id);
const compiled = new Bun.Transpiler({loader:'ts'}).transformSync(body);
const Client = new Function(
  'spawn', 'join', 'homedir', 'setTimeout', 'clearTimeout',
  compiled + '\nreturn AgencyWebClient;',
)(spawn, () => '/fixture', () => '/fixture', fakeTimeout, fakeClear);
const client = new Client();
const mode=Bun.argv[3] || 'lifecycle';
if(mode==='lifecycle') {
  const signal = new AbortController();
  const first = client.call({local_query:[{q:'first'}]},signal.signal);
  await new Promise(resolve=>setImmediate(resolve));
  signal.abort();
  await assert.rejects(first,/aborted/);
  const second = client.call({local_query:[{q:'second'}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(children.length,1,'replacement must wait for old child cleanup');
  children[0].stdout.write('stale partial JSON');
  children[0].emit('error',new Error('stale error'));
  children[0].emit('close',143);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(children.length,2);
  const request=children[1].frames.find(frame=>frame.method==='tools/call');
  const bytes=Buffer.from(JSON.stringify({id:request.id,result:{content:[{type:'text',text:'second 😀'}]}})+'\n');
  for(const byte of bytes) children[1].stdout.write(Buffer.from([byte]));
  assert.equal((await second).content[0].text,'second 😀');
} else if(mode==='oversized') {
  const pending=client.call({local_query:[{q:'fixture'}]});
  await new Promise(resolve=>setImmediate(resolve));
  children[0].stdout.write('x'.repeat(4*1024*1024+1));
  await assert.rejects(pending,/exceeds 4 MiB/);
  assert.equal(children[0].kills,1);
} else if(mode==='queue') {
  await client.start();
  const pending=Array.from({length:16},()=>client.request('tools/call',{}).catch(error=>error));
  await assert.rejects(()=>client.request('tools/call',{}),/queue is full/);
  assert.equal(client.pending.size,16);
  client.close();
  for(const result of await Promise.all(pending)) assert.match(result.message,/closed/);
} else if(mode==='deadline') {
  const pending=client.call({local_query:[{q:'fixture'}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(timers.size,1);
  const timer=[...timers.values()][0];
  assert.equal(timer.delay,180000);
  timer.callback();
  await assert.rejects(pending,/deadline exceeded/);
  assert.equal(children[0].kills,1);
} else if(mode==='retire') {
  const signal=new AbortController();
  const pending=client.call({local_query:[{q:'fixture'}]},signal.signal);
  await new Promise(resolve=>setImmediate(resolve));signal.abort();
  await assert.rejects(pending,/aborted/);
  const next=client.call({local_query:[{q:'next'}]});
  await new Promise(resolve=>setImmediate(resolve));
  const timer=[...timers.values()].find(timer=>timer.delay===5000);assert.ok(timer);
  timer.callback();assert.deepEqual(children[0].signals,['SIGTERM','SIGKILL']);
  assert.equal(children.length,1);
  children[0].emit('close',137);
  await new Promise(resolve=>setImmediate(resolve));
  const request=children[1].frames.find(frame=>frame.method==='tools/call');
  children[1].stdout.write(JSON.stringify({id:request.id,result:{content:[]}})+'\n');
  assert.deepEqual((await next).content,[]);
} else if(mode==='shutdown-wait') {
  const signal=new AbortController();
  const first=client.call({local_query:[{q:'fixture'}]},signal.signal);
  await new Promise(resolve=>setImmediate(resolve));signal.abort();
  await assert.rejects(first,/aborted/);
  const waiting=client.call({local_query:[{q:'waiting'}]}).then(value=>({value}),error=>({error}));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(children.length,1);
  client.close();children[0].emit('close',143);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(children.length,1,'session shutdown must cancel a launch waiting for old-child cleanup');
  assert.match((await waiting).error.message,/closed/);
} else if(mode==='request') {
  await client.start();
  await assert.rejects(()=>client.request('tools/call',{text:'😀'.repeat(20000)}),/exceeds 64 KiB/);
  assert.equal(client.pending.size,0);
} else throw new Error('unknown fixture mode');
client.close();
for(const child of children)child.emit('close',143);
await Promise.resolve();
assert.equal(timers.size,0,'all request timers must be removed');
console.log('pi '+mode+' passed');
