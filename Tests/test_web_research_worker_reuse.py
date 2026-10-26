import json
import sqlite3
import subprocess

from Tests.web_research_support import (
    WEB_TOOL,
    WebResearchTestCase,
    fixture_directory,
    fixture_environment,
    source_prefix,
    worker_frame,
)


class WorkerReuseTests(WebResearchTestCase):

    def test_browser_lease_reuse_options_failure_ephemeral_and_cleanup(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
let starts=0, stops=0, fresh=0;
startBrowser = async options => ({
  context: 'initial',
  processHandle: {exitCode: null},
  bidi: {
    subscriptions: new Set(),
    listeners: new Map(),
    command: async (method, params) => {
      if (method === 'browsingContext.create') {
        fresh++;
        return {context: 'fresh-' + fresh};
      }
      return {};
    },
    tree: async () => ({contexts: []}),
  },
});
stopBrowser = async () => {stops++;};
const actualStart = startBrowser;
startBrowser = async options => {starts++;return actualStart(options);};
workerMode = true;
const options = {profile:'fixture',ephemeral:false,headless:true,allowPrivate:false,templatePreferences:[]};
assert.equal(await withBrowser(options,async browser=>browser.context), 'fresh-1');
assert.equal(await withBrowser(options,async browser=>browser.context), 'fresh-2');
assert.equal(starts,1,'same-compatible-profile operations must reuse Firefox');
assert.equal(stops,0);
await withBrowser({...options,allowPrivate:true},async()=>{});
assert.equal(starts,2,'proxy policy change requires a new browser');
assert.equal(stops,1);
await assert.rejects(()=>withBrowser({...options,allowPrivate:true},async()=>{throw new Error('operation failed');}),/operation failed/);
assert.equal(stops,2,'failed operation must invalidate the lease');
await withBrowser({...options,ephemeral:true},async()=>{});
await withBrowser({...options,ephemeral:true},async()=>{});
assert.equal(starts,4);
assert.equal(stops,4,'ephemeral browsers close per operation');
await withBrowser(options,async()=>{});
await withBrowser(options,async()=>{},[['fixture.preference',true]]);
assert.equal(starts,6);
assert.equal(stops,6,'one-shot transient preferences must first close warm lease');
const retainContextState = browser => {
  browser.bidi.subscriptions.add('event\n' + browser.context);
  browser.bidi.listeners.set('event', new Set([()=>{}]));
};
await withBrowser(options, async browser => retainContextState(browser));
for (let i = 0; i < 50; i++) {
  await withBrowser(options, async browser => {
    assert.equal(browser.bidi.subscriptions.size, 0);
    assert.equal(browser.bidi.listeners.size, 0);
    retainContextState(browser);
  });
}
await closeWorkerBrowser();
assert.equal(starts,7);
assert.equal(stops,7,'worker shutdown closes last lease');
'''
        self.run_harness(harness, source=source)

    def test_worker_serial_protocol_matches_one_shot_local_and_survives_errors(self):
        with fixture_directory() as directory:
            environment = fixture_environment(directory)
            arguments = ['local', 'fixture', '--json']
            direct = subprocess.run(
                [WEB_TOOL, *arguments],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(direct.returncode, 0, direct.stderr)

            page_url = 'https://example.test/fixture'
            title = 'Fixture evidence'
            evidence = 'fixture retained evidence'
            connection = sqlite3.connect(directory / 'data/index.sqlite')
            try:
                connection.execute(
                    'INSERT INTO pages(url,title,text,markdown,fetched_at) VALUES (?,?,?,?,?)',
                    (page_url, title, evidence, evidence, '2026-10-22T00:00:00Z'),
                )
                connection.execute(
                    'INSERT INTO pages_fts(url,title,text) VALUES (?,?,?)',
                    (page_url, title, evidence),
                )
                connection.commit()
            finally:
                connection.close()

            direct = subprocess.run(
                [WEB_TOOL, *arguments],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(direct.returncode, 0, direct.stderr)
            expected = json.loads(direct.stdout)
            self.assertEqual(len(expected['results']), 1)
            self.assertEqual(expected['results'][0]['url'], page_url)

            requests = worker_frame(['invalid']) + worker_frame(arguments) * 2
            worker = subprocess.run(
                [WEB_TOOL, 'worker'],
                input=requests,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(worker.returncode, 0, worker.stderr)
            messages = [json.loads(line) for line in worker.stdout.splitlines()]
            self.assertIn('error', messages[0])
            self.assertEqual(messages[1], {'result': expected})
            self.assertEqual(messages[2], messages[1])

    def test_real_worker_reuses_profile_for_local_browser_fixture(self):
        from Tests.test_web_research import rendered_fixture_server

        with fixture_directory() as directory, rendered_fixture_server() as url:
            arguments = [
                'scrape', url,
                '--format', 'json',
                '--profile', 'reuse-fixture',
                '--allow-private',
                '--wait-ms', '50',
                '--settle-ms', '100',
            ]
            frame = worker_frame(arguments)
            worker = subprocess.run(
                [WEB_TOOL, 'worker'],
                input=frame * 2,
                env=fixture_environment(directory),
                text=True,
                capture_output=True,
                timeout=45,
            )
            self.assertEqual(worker.returncode, 0, worker.stderr)
            messages = [json.loads(line) for line in worker.stdout.splitlines()]
            self.assertEqual(len(messages), 2)
            for message in messages:
                self.assertNotIn('error', message)
                self.assertIn('Hydrated evidence', message['result']['text'])
            for field in ('title', 'url', 'canonicalUrl', 'text', 'markdown', 'html', 'links'):
                self.assertEqual(messages[0]['result'][field], messages[1]['result'][field])
            self.assertFalse(list((directory / 'data').glob('profiles/*.lock')))

    def test_shutdown_during_startup_and_active_ephemeral_operation(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
let released=0, proxies=0, kills=0;
const nativeTimeout=globalThis.setTimeout,nativeClear=globalThis.clearTimeout;
const activeTimers=new Set();
globalThis.setTimeout=(callback,delay)=>{const timer=nativeTimeout(()=>{activeTimers.delete(timer);callback();},delay);activeTimers.add(timer);return timer;};
globalThis.clearTimeout=timer=>{activeTimers.delete(timer);nativeClear(timer);};
const children=[];
safeProxy=async()=>({port:1234,close:async()=>{proxies++;}});
claimProfile=()=>({root:'/fixture',lock:'/fixture.lock'});
releaseProfile=()=>{released++;};
Bun.spawn=()=>{
  let finish;
  const child={exitCode:null,exited:new Promise(resolve=>{finish=resolve;}),kill(){kills++;this.exitCode=143;finish(143);}};
  children.push(child);return child;
};
workerMode=true;
let fetchStarted;
const reachedFetch=new Promise(resolve=>{fetchStarted=resolve;});
globalThis.fetch=async(url,options)=>{fetchStarted();return new Promise((resolve,reject)=>options?.signal?.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));};
const startup=startBrowser({profile:'fixture',headless:true,ephemeral:false,allowPrivate:false,templatePreferences:[]}).catch(error=>error);
await reachedFetch;
await shutdownWorkerBrowsers();
assert.equal(kills,1,'shutdown must terminate child before startup returns');
assert.equal(released,1);
assert.equal(proxies,1);
assert.ok(await startup instanceof Error);
assert.equal(activeBrowserResources.size,0);
workerStopping=false;
globalThis.fetch=async()=>({ok:true});
let closeOperation;
Bidi=class {
  subscriptions=new Set();listeners=new Map();
  open=async()=>{};context=async()=> 'fixture';command=async()=>({});
  close(){closeOperation?.();}
};
let operationStarted;
const reachedOperation=new Promise(resolve=>{operationStarted=resolve;});
const operation=withBrowser({profile:'ephemeral',headless:true,ephemeral:true,allowPrivate:false,templatePreferences:[]},async()=>{
  operationStarted();await new Promise(resolve=>{closeOperation=resolve;});return 'cancelled';
});
await reachedOperation;
await shutdownWorkerBrowsers();
await operation;
assert.equal(kills,2,'active one-shot browser must also be terminated');
assert.equal(released,2);
assert.equal(proxies,2);
assert.equal(activeBrowserResources.size,0);
assert.equal(activeTimers.size,0,'shutdown must clear process termination timers');
globalThis.setTimeout=nativeTimeout;globalThis.clearTimeout=nativeClear;
'''
        self.run_harness(harness, source=source)

    def test_idle_expiry_waits_for_cleanup_before_reacquiring_profile(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
let starts=0,stops=0,finishStop;
let deferStop=true;
const timers=new Map();
const actualTimeout=globalThis.setTimeout,actualClear=globalThis.clearTimeout;
globalThis.setTimeout=(callback,delay)=>{const timer={callback,delay,unref(){}};timers.set(timer,timer);return timer;};
globalThis.clearTimeout=timer=>timers.delete(timer);
startBrowser=async()=>{starts++;return {context:'initial',processHandle:{exitCode:null},bidi:{subscriptions:new Set(),listeners:new Map(),command:async method=>method==='browsingContext.create'?{context:'fresh'}:{},tree:async()=>({contexts:[]})}};};
stopBrowser=async()=>{stops++;if(deferStop)await new Promise(resolve=>{finishStop=resolve;});};
workerMode=true;
const options={profile:'fixture',headless:true,allowPrivate:false,ephemeral:false,templatePreferences:[]};
await withBrowser(options,async()=>{});
assert.equal(timers.size,1);
const timer=[...timers.values()][0];
assert.equal(timer.delay,30000);
timers.delete(timer);timer.callback();
const second=withBrowser(options,async()=>{});
await Promise.resolve();await Promise.resolve();
assert.equal(starts,1,'next launch must wait for expired lease cleanup');
assert.equal(stops,1);
deferStop=false;finishStop();await second;
assert.equal(starts,2);
await closeWorkerBrowser();
assert.equal(stops,2);assert.equal(timers.size,0);
globalThis.setTimeout=actualTimeout;globalThis.clearTimeout=actualClear;
'''
        self.run_harness(harness, source=source)

    def test_cleanup_attempts_every_stage_and_is_idempotent(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
const called=[];
terminateBrowserProcess=async()=>{called.push('process');throw new Error('process cleanup');};
releaseProfile=()=>{called.push('profile');throw new Error('profile cleanup');};
const resources={abort:new AbortController(),bidi:{close(){called.push('bidi');throw new Error('bidi cleanup');}},processHandle:{},claimed:{},proxy:{close:async()=>{called.push('proxy');throw new Error('proxy cleanup');}}};
activeBrowserResources.add(resources);
await assert.rejects(()=>closeBrowserResources(resources),AggregateError);
await assert.rejects(()=>closeBrowserResources(resources),AggregateError);
assert.deepEqual(called,['bidi','process','profile','proxy']);
assert.equal(activeBrowserResources.size,0);
assert.equal(resources.abort.signal.aborted,true);
'''
        self.run_harness(harness, source=source)
