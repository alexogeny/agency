import argparse
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


MAX_RESPONSE = 16 * 1024 * 1024


class BrowserError(ValueError):
    pass


class Deferred(BrowserError):
    pass


class ServiceError(BrowserError):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.retry_after = retry_after
        super().__init__('Hosted service returned HTTP ' + str(status) + '; action was not retried.')


def origin(url):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
            raise ValueError
        host = p.hostname.lower()
        port = p.port
    except (ValueError, AttributeError, TypeError):
        raise BrowserError('Supply an HTTP(S) URL without credentials.') from None
    if ':' in host:
        host = '[' + host + ']'
    return p.scheme + '://' + host + (':' + str(port) if port and port != {'http':80,'https':443}[p.scheme] else '')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare_packet(snapshot, page_url, goal, refs, context):
    origin(page_url)
    if (not isinstance(snapshot, str) or len(snapshot.encode()) > MAX_RESPONSE
            or not isinstance(refs, list) or not 1 <= len(refs) <= 32
            or any(not isinstance(r, str) or not re.fullmatch(r'(?:f\d+)?e\d+', r) for r in refs)
            or len(set(refs)) != len(refs)):
        raise BrowserError('Supply 1 to 32 distinct snapshot refs.')
    if any(not isinstance(s, str) or not s.strip() or len(s) > 4096 for s in (goal, context)):
        raise BrowserError('Goal and bounded context must be nonempty text.')
    controls = {}
    lines = snapshot.splitlines()
    for i, line in enumerate(lines):
        match = re.search(r'\b(link|button) "((?:\\.|[^"\\])*)".*\[ref=((?:f\d+)?e\d+)\]', line)
        if not match or match[3] not in refs:
            continue
        role, label, ref = match.groups()
        if '[disabled]' in line or '[aria-hidden]' in line or not label or len(label) > 1024:
            raise BrowserError('Candidate is disabled, hidden, or has an invalid name.')
        if ref in controls:
            raise BrowserError('Snapshot contains a duplicate candidate ref.')
        url = None
        if role == 'link' and i + 1 < len(lines):
            url_match = re.search(r'- /url: (\S+)', lines[i + 1])
            if url_match:
                url = urllib.parse.urljoin(page_url, url_match[1])
                origin(url)
        controls[ref] = {'target':ref, 'role':role, 'label':label, 'url':url}
    if set(controls) != set(refs):
        raise BrowserError('A supplied ref is not a named link or button in this snapshot.')
    state = {'goal':goal, 'context':context,
             'candidates': {ref: value['role'] + ': ' + value['label'] for ref,value in controls.items()}}
    return {'page_url':page_url, 'snapshot_sha256':digest(snapshot), 'state':state, 'targets':controls}


def bind_selection(packet, decision):
    label = decision.get('decision')
    if label not in packet['targets'] and label not in ('done','unsure'):
        raise BrowserError('Decision does not name a supplied candidate.')
    return {**decision, 'page_url':packet['page_url'], 'snapshot_sha256':packet['snapshot_sha256'],
            'packet_sha256':digest(json.dumps(packet, sort_keys=True)),
            'target':packet['targets'][label]['target'] if label in packet['targets'] else None}


def validate_selection(selection, packet, current_snapshot, current_url):
    if (selection.get('packet_sha256') != digest(json.dumps(packet, sort_keys=True))
            or selection.get('snapshot_sha256') != digest(current_snapshot)
            or current_url != packet['page_url'] or selection.get('page_url') != current_url):
        raise BrowserError('Observation changed; obtain a fresh packet and decision.')
    label = selection.get('decision')
    target = packet['targets'].get(label)
    if not target or selection.get('target') != target['target']:
        raise BrowserError('This recommendation has no valid click target.')
    return dict(target)


def retry_after(value, now):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r'\d+', value):
        try:
            seconds = float(value)
            return seconds if math.isfinite(seconds) else None
        except (ValueError, OverflowError):
            return None
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0, date.timestamp() - now)
    except (ValueError, TypeError, OverflowError):
        return None


def download_state(directory, filename):
    if not isinstance(filename,str) or not filename or Path(filename).name != filename or '\\' in filename:
        raise BrowserError('Download filename must be one basename.')
    stem,suffix=os.path.splitext(filename)
    pattern=re.compile(re.escape(stem)+r'(?: \(\d+\))?'+re.escape(suffix)+r'\Z')
    found={}
    for path in Path(directory).iterdir():
        if not pattern.fullmatch(path.name):
            continue
        info=path.lstat()
        if stat.S_ISREG(info.st_mode):
            found[path]=(info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    return found


def wait_for_download(directory,filename,expected_size,before,timeout=120,clock=time.monotonic,sleep=time.sleep):
    if type(expected_size) is not int or expected_size < 0 or not _finite(timeout,0.1,600):
        raise BrowserError('Supply an expected byte size and bounded download timeout.')
    deadline=clock()+timeout
    while True:
        found=download_state(directory,filename)
        candidates=[path for path,fingerprint in found.items()
                    if fingerprint != before.get(path) and fingerprint[1] == expected_size]
        if len(candidates) > 1:
            raise BrowserError('Multiple completed downloads match; inspect them before choosing.')
        if candidates:
            return candidates[0]
        remaining=deadline-clock()
        if remaining <= 0:
            raise Deferred('Download remains unverified; inspect the transfer before any further download.')
        sleep(min(1,remaining))


def _finite(value, low, high):
    return type(value) in (int,float) and math.isfinite(value) and low <= value <= high


def private_json(path, data):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)


class Pacer:
    """One in-flight action per origin across processes sharing this state directory."""
    def __init__(self, directory, minimum=2, jitter=2, backoff=10, max_wait=30,
                 clock=time.time, sleep=time.sleep, random=random.uniform):
        for value, low, high in ((minimum,0.1,3600),(jitter,0,3600),(backoff,1,3600),(max_wait,0,60)):
            if not _finite(value, low, high):
                raise BrowserError('Invalid pacing policy; minimum gap must be positive and all values finite.')
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.minimum, self.jitter, self.backoff, self.max_wait = minimum,jitter,backoff,max_wait
        self.clock, self.sleep, self.random = clock,sleep,random

    @contextmanager
    def _locked(self, url):
        path = self.directory / (digest(origin(url)) + '.json')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BrowserError('Pacing state must be a private regular file owned by this user.')
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Deferred('Another action for this origin is in progress.') from None
            raw = stream.read(8193)
            try:
                state = json.loads(raw) if raw else {'next_at':0,'failures':0}
                if (set(state) != {'next_at','failures'} or not _finite(state['next_at'],0,1e15)
                        or type(state['failures']) is not int or not 0 <= state['failures'] <= 30):
                    raise ValueError
            except (ValueError, TypeError):
                raise BrowserError('Invalid pacing state; refusing to discard its cooldown.') from None
            yield stream,state

    def _save(self, stream, state):
        stream.seek(0)
        json.dump(state, stream, allow_nan=False)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())

    def run(self, url, operation):
        with self._locked(url) as (stream,state):
            wait = max(0, state['next_at'] - self.clock())
            if wait > self.max_wait:
                raise Deferred('Origin cooldown has ' + str(round(wait,1)) + ' seconds remaining.')
            if wait:
                self.sleep(wait)
            # Persist a reservation before I/O so an interrupted process leaves a gap.
            delay = self.minimum + self.random(0,self.jitter)
            state['next_at'] = self.clock() + delay
            self._save(stream,state)
            try:
                result = operation()
            except ServiceError as error:
                if error.status in (429,503):
                    state['failures'] = min(30,state['failures'] + 1)
                    delay = max(delay,min(3600,self.backoff * 2 ** (state['failures']-1))
                                + self.random(0,self.jitter),retry_after(error.retry_after,self.clock()) or 0)
                raise
            else:
                state['failures'] = 0
                return {'result':result,'wait_seconds':round(wait,6),'origin':origin(url)}
            finally:
                state['next_at'] = self.clock() + delay
                self._save(stream,state)


def parse_response(raw, content_type, identifier):
    if len(raw) > MAX_RESPONSE:
        raise BrowserError('MCP response exceeds the size limit.')
    try:
        text = raw.decode('utf-8')
        if 'text/event-stream' in content_type:
            messages, data = [],[]
            for line in text.splitlines() + ['']:
                if line.startswith('data:'):
                    data.append(line[5:].lstrip(' '))
                elif not line and data:
                    messages.append(json.loads('\n'.join(data)))
                    data = []
            matches = [m for m in messages if isinstance(m,dict) and m.get('id') == identifier]
            if len(matches) != 1:
                raise ValueError
            response = matches[0]
        else:
            response = json.loads(text)
        if not isinstance(response,dict) or response.get('id') != identifier:
            raise ValueError
    except (UnicodeError, ValueError):
        raise BrowserError('Invalid or mismatched MCP response.') from None
    if 'error' in response:
        raise BrowserError('MCP returned a protocol error.')
    return response


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tool_text(result):
    return '\n'.join(c.get('text','') for c in result.get('content',[]) if c.get('type') == 'text')


def read_snapshot(result, server_output):
    text = tool_text(result)
    url_match = re.search(r'^- Page URL: (\S+)$',text,re.MULTILINE)
    if not url_match:
        raise BrowserError('Snapshot response has no page URL.')
    inline = re.search(r'### Snapshot\n```yaml\n([\s\S]*?)```',text)
    if inline:
        return inline[1],url_match[1]
    link = re.search(r'### Snapshot\n- \[Snapshot\]\(([^)]+)\)',text)
    if not link:
        # Recent MCP versions omit the fence for small inline snapshots.
        if '### Snapshot\n' in text:
            snapshot=text.split('### Snapshot\n',1)[1].split('\n### ',1)[0]
            if snapshot.startswith('- '):
                return snapshot.rstrip()+'\n',url_match[1]
        raise BrowserError('Snapshot response has no supported structured snapshot.')
    root = Path(server_output).resolve()
    path = (root/link[1]).resolve()
    if not path.is_relative_to(root) or path.stat().st_size > MAX_RESPONSE:
        raise BrowserError('Snapshot path is outside the server output or exceeds its limit.')
    return path.read_text(encoding='utf-8'),url_match[1]


class MCPClient:
    def __init__(self, endpoint, session=None, timeout=90):
        p = urllib.parse.urlsplit(endpoint)
        if (p.scheme not in ('http','https') or p.hostname not in ('localhost','127.0.0.1','::1')
                or p.username or p.password or p.query or p.fragment):
            raise BrowserError('MCP endpoint must be a loopback HTTP(S) URL without credentials or query data.')
        if not _finite(timeout,0.1,300):
            raise BrowserError('Invalid MCP timeout.')
        self.endpoint, self.session, self.timeout = endpoint,session,timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.identifier = 0

    def request(self, method, params=None, notification=False):
        self.identifier += 1
        payload = {'jsonrpc':'2.0','method':method}
        if not notification:
            payload['id'] = self.identifier
        if params is not None:
            payload['params'] = params
        headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        if self.session:
            headers.update({'Mcp-Session-Id':self.session['id'],'MCP-Protocol-Version':self.session['version']})
        req = urllib.request.Request(self.endpoint,json.dumps(payload,allow_nan=False).encode(),headers,method='POST')
        try:
            with self.opener.open(req,timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE+1)
                headers = dict(response.headers)
                response_type = response.headers.get('Content-Type','')
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise BrowserError('Local MCP request failed (HTTP ' + str(code) + '); no retry performed.') from None
        except (urllib.error.URLError,OSError):
            raise BrowserError('Local MCP request could not complete; no retry performed.') from None
        if notification and not raw.strip():
            return None,headers
        return parse_response(raw,response_type,self.identifier),headers

    def initialize(self):
        response,headers = self.request('initialize',{
            'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'agency-browser','version':'0.1'}})
        identifier = next((v for k,v in headers.items() if k.lower() == 'mcp-session-id'),None)
        if not identifier:
            raise BrowserError('MCP server did not return a session identifier.')
        self.session = {'id':identifier,'version':response['result']['protocolVersion']}
        self.request('notifications/initialized',notification=True)
        return dict(self.session)

    def call(self, tool, arguments):
        response,_ = self.request('tools/call',{'name':tool,'arguments':arguments})
        result = response.get('result',{})
        if result.get('isError'):
            raise BrowserError('Browser tool failed; inspect the current page before another action.')
        return result

    def fetch_json(self, url, pacer, allowed_prefix):
        parsed = urllib.parse.urlsplit(url)
        decoded_path = urllib.parse.unquote(parsed.path)
        if (origin(url) != origin(allowed_prefix) or not url.startswith(allowed_prefix)
                or parsed.fragment or not allowed_prefix.endswith('/') or '\\' in decoded_path
                or any(part in ('.','..') for part in decoded_path.split('/'))):
            raise BrowserError('JSON request is outside the explicit allowed URL prefix.')
        expression = ('async () => {if(location.origin !== '+json.dumps(origin(url))+') '
                      'return {scope_error:true}; const r=await fetch('+json.dumps(url)+', '
                      '{credentials:"same-origin"}); const raw=await r.text(); return {status:r.status, '
                      'retry_after:r.headers.get("Retry-After"),link:r.headers.get("Link"), '
                      'data:r.ok ? JSON.parse(raw) : null};}')
        def operation():
            text = tool_text(self.call('browser_evaluate',{'function':expression}))
            try:
                data = json.JSONDecoder().raw_decode(text.split('### Result\n',1)[1])[0]
            except (IndexError,ValueError):
                raise BrowserError('Browser did not return structured JSON.') from None
            if data.get('scope_error'):
                raise BrowserError('Browser is not currently on the requested origin.')
            if data.get('status') != 200:
                raise ServiceError(data.get('status'),data.get('retry_after'))
            return data
        return pacer.run(url,operation)

    def click(self, selection, packet, server_output, pacer):
        observed = pacer.run(packet['page_url'],lambda:self.call('browser_snapshot',{}))
        snapshot,url = read_snapshot(observed['result'],server_output)
        target = validate_selection(selection,packet,snapshot,url)
        return pacer.run(url,lambda:self.call('browser_click',{'target':target['target'],'element':target['label']}))

    def download(self,url,destination,download_directory,filename,expected_size,pacer,timeout=120):
        origin(url)
        if type(expected_size) is not int or expected_size < 0 or not _finite(timeout,0.1,600):
            raise BrowserError('Supply an expected byte size and bounded download timeout.')
        destination=Path(destination)
        if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
            raise BrowserError('Download destination must be new with an existing parent directory.')
        def operation():
            before=download_state(download_directory,filename)
            code=('async (page) => {await page.goto('+json.dumps(url)+',{waitUntil:"commit"}).catch(e=>{'
                  'if(!String(e).includes("ERR_ABORTED")&&!String(e).includes("Download is starting"))throw e;});'
                  'return {started:true};}')
            self.call('browser_run_code_unsafe',{'code':code})
            completed=wait_for_download(download_directory,filename,expected_size,before,timeout=timeout)
            try:
                descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            except FileExistsError:
                raise BrowserError('Download destination appeared during transfer; both files were preserved.') from None
            checksum=hashlib.sha256()
            with os.fdopen(descriptor,'wb') as out, completed.open('rb') as source:
                while chunk:=source.read(1024*1024):
                    out.write(chunk)
                    checksum.update(chunk)
            if destination.stat().st_size != expected_size:
                raise BrowserError('Downloaded file changed during copying; both files were preserved.')
            completed.unlink()
            return {'path':str(destination),'bytes':destination.stat().st_size,'sha256':checksum.hexdigest()}
        return pacer.run(url,operation)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bounded structured browser choices and persistent per-origin pacing.')
    sub = parser.add_subparsers(dest='command',required=True)
    packet = sub.add_parser('packet')
    packet.add_argument('--snapshot',required=True,type=Path)
    packet.add_argument('--url',required=True)
    packet.add_argument('--goal',required=True)
    packet.add_argument('--context',required=True)
    packet.add_argument('--refs',required=True,nargs='+')
    choose = sub.add_parser('choose')
    choose.add_argument('--packet',required=True,type=Path)
    choose.add_argument('--dry-run',action='store_true')
    call = sub.add_parser('call')
    call.add_argument('tool')
    call.add_argument('--arguments',required=True,type=Path)
    call.add_argument('--endpoint',default='http://localhost:8937/mcp')
    call.add_argument('--session',required=True,type=Path)
    call.add_argument('--origin',required=True)
    call.add_argument('--pace-state',type=Path,default=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'agency/browser/pacing')
    call.add_argument('--minimum',type=float,default=2)
    call.add_argument('--jitter',type=float,default=2)
    get = sub.add_parser('get-json')
    get.add_argument('--url',required=True)
    get.add_argument('--allow-prefix',required=True)
    click = sub.add_parser('click')
    click.add_argument('--packet',required=True,type=Path)
    click.add_argument('--choice',required=True,type=Path)
    click.add_argument('--server-output',required=True,type=Path)
    download = sub.add_parser('download')
    download.add_argument('--url',required=True)
    download.add_argument('--destination',required=True,type=Path)
    download.add_argument('--download-directory',required=True,type=Path)
    download.add_argument('--filename',required=True)
    download.add_argument('--expected-size',required=True,type=int)
    download.add_argument('--timeout',type=float,default=120)
    batch = sub.add_parser('download-batch')
    batch.add_argument('--manifest',required=True,type=Path)
    batch.add_argument('--destination',required=True,type=Path)
    batch.add_argument('--download-directory',type=Path)
    batch.add_argument('--timeout',type=float,default=120)
    batch.add_argument('--progress',action='store_true')
    batch.add_argument('--retry-interrupted',action='store_true',help='Retry missing files after inspecting interrupted Chrome transfers.')
    mode = batch.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--verify-only',action='store_true')
    for command in (get,click,download,batch):
        command.add_argument('--endpoint',default='http://localhost:8937/mcp')
        command.add_argument('--session',required=command is not batch,type=Path)
        command.add_argument('--pace-state',type=Path,default=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'agency/browser/pacing')
        command.add_argument('--minimum',type=float,default=2)
        command.add_argument('--jitter',type=float,default=2)
    for command in (packet,choose,call,get,click,download,batch):
        command.add_argument('--output',type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'packet':
            result = prepare_packet(args.snapshot.read_text(),args.url,args.goal,args.refs,args.context)
        elif args.command == 'choose':
            from agency_decisions import build_request,evaluate
            packet = json.loads(args.packet.read_text())
            result = (build_request(packet['state'],'browser-workflow/next-control') if args.dry_run else
                      bind_selection(packet,evaluate(packet['state'],'browser-workflow/next-control')))
        elif args.command == 'download-batch':
            from agency_browser_downloads import download_batch,load_manifest,plan_batch
            manifest = load_manifest(args.manifest)
            if not _finite(args.timeout,0.1,600):
                raise BrowserError('Invalid download timeout.')
            if args.dry_run:
                result = plan_batch(manifest,args.destination)
            else:
                client = None
                pacer = None
                def transfer(item,path):
                    nonlocal client,pacer
                    if client is None:
                        if not args.session or not args.download_directory or not args.session.parent.is_dir():
                            raise BrowserError('New downloads require a session path and Chrome download directory.')
                        client = MCPClient(args.endpoint,json.loads(args.session.read_text()) if args.session.exists() else None)
                        pacer = Pacer(args.pace_state,minimum=args.minimum,jitter=args.jitter)
                        if not client.session:
                            private_json(args.session,client.initialize())
                    return client.download(item['url'],path,args.download_directory,item['filename'],
                                           item['expected_size'],pacer,args.timeout)
                progress = (lambda row:print(row['status']+' '+row['id']+' '+str(row['bytes']),file=sys.stderr)) if args.progress else None
                result = download_batch(manifest,args.destination,transfer if not args.verify_only else None,
                                        verify_only=args.verify_only,progress=progress,retry_interrupted=args.retry_interrupted)
        else:
            client = MCPClient(args.endpoint,json.loads(args.session.read_text()) if args.session.exists() else None)
            if not client.session:
                private_json(args.session,client.initialize())
            pacer = Pacer(args.pace_state,minimum=args.minimum,jitter=args.jitter)
            if args.command == 'get-json':
                result = client.fetch_json(args.url,pacer,args.allow_prefix)
            elif args.command == 'click':
                result = client.click(json.loads(args.choice.read_text()),json.loads(args.packet.read_text()),args.server_output,pacer)
            elif args.command == 'download':
                result = client.download(args.url,args.destination,args.download_directory,args.filename,args.expected_size,pacer,args.timeout)
            else:
                result = pacer.run(args.origin,lambda:client.call(args.tool,json.loads(args.arguments.read_text())))
        if args.output:
            private_json(args.output,result)
        else:
            print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 1 if args.command == 'download-batch' and not args.dry_run and not result['complete'] else 0
    except (BrowserError,OSError,ValueError,KeyError) as error:
        print(str(error),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
