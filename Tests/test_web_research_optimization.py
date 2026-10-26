from Tests.web_research_support import WebResearchTestCase, source_prefix


class StreamingInputTests(WebResearchTestCase):

    def test_batch_and_checkpoint_avoid_whole_file_reads(self):
        source = source_prefix()
        source = source.replace('  readFileSync,', '  readFileSync as originalReadFileSync,', 1)
        source = source.replace('  readSync,', '  readSync as originalReadSync,', 1)
        harness = r'''
import assert from 'node:assert/strict';
let wholeReads = 0, mutatePath = "";
function readSync(...args) {
  const length = originalReadSync(...args);
  if (mutatePath) {
    writeFileSync(mutatePath, "changed during hash");
    mutatePath = "";
  }
  return length;
}
function readFileSync(...args) { wholeReads++; return originalReadFileSync(...args); }
fail = message => { throw new Error(message); };
mkdirSync(dataRoot, {recursive:true});
const input = join(dataRoot, 'input'), output = join(dataRoot, 'output');
writeFileSync(input, 'https://example.test/é\r\nhttps://example.test/é\nhttps://example.test/b\n');
writeFileSync(output, '');
assert.deepEqual(batchUrls(input).urls, ['https://example.test/%C3%A9', 'https://example.test/b']);
healthCheckpoint(output, false, 'scrape-batch', 'fixture', false, input);
healthCheckpoint(output, true, 'scrape-batch', 'fixture', false, input);
writeFileSync(input, 'https://example.test/c\n', {flag:'a'});
healthCheckpoint(output, true, 'scrape-batch', 'fixture', false, input, true);
writeFileSync(input, 'changed\n');
assert.throws(() => healthCheckpoint(output, true, 'scrape-batch', 'fixture', false, input, true), /unchanged byte prefix/);
writeFileSync(input, 'α\nβ\nα\n');
assert.deepEqual(batchQueries(input).queries, ['α','β']);
writeFileSync(output, JSON.stringify({schema:'agency/web-search-result/1',query:'α',outcome:'searched'})+'\r\n');
assert.deepEqual([...completedBatchQueries(output,false)], ['α']);
const large = Buffer.from('x'.repeat(65533)+'😀é\r\n'+ 'y'.repeat(100000));
writeFileSync(input,large);
const actual = fileDigest(input,Infinity,65536);
assert.equal(actual.sha256,createHash('sha256').update(large).digest('hex'));
assert.equal(actual.prefixSha256,createHash('sha256').update(large.subarray(0,65536)).digest('hex'));
assert.equal(actual.bytes,large.length);
assert.equal(fileDigest(input,65536).sha256,actual.prefixSha256);
assert.equal([...utf8FileLines(input)].join('\n'),large.toString('utf8').replace('\r\n','\n'));
mutatePath=input;
assert.throws(()=>fileDigest(input),/changed while hashing/);
assert.equal(wholeReads, 0, 'batch/checkpoint operations must stream their files');
'''
        self.run_harness(harness, source=source)

    def test_shadow_discovery_is_lazy_and_descendant_counts_are_aggregated(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
let visits=0, descendantQueries=0;
const nodes=Array.from({length:60000},(_,i)=>({
  i,shadowRoot:null,parentElement:null,scrollTop:0,scrollHeight:1000,clientHeight:200,
  innerText:'content',matches(selector) {return selector.includes('section, div') || (selector==='article, [role="article"]' && this.i===99);},
  getBoundingClientRect:()=>({width:400,height:300}),
  querySelectorAll() {descendantQueries++;return [];},
}));
for(let i=1;i<nodes.length;i++) nodes[i].parentElement=nodes[i-1];
const document={readyState:'complete',title:'Fixture',documentElement:{scrollHeight:1000},
  createTreeWalker(root) {let i=0;return {nextNode(){visits++;return nodes[i++]||null;}};},
  querySelectorAll(selector) {throw new Error('unbounded selector allocation: '+selector);},
};
Object.assign(globalThis,{document,location:{href:'https://example.test/'},NodeFilter:{SHOW_ELEMENT:1},
  getComputedStyle:()=>({overflowY:'auto'}),window:{scrollY:0,scrollTo(){}}});
const stable=JSON.parse(new Function('return '+pageStabilityExpression)());
assert.ok(visits<=50000,'discovery must stop before traversing the remainder');
assert.equal(stable.dom_truncated,true);
visits=0;
JSON.parse(new Function('return '+scrollExpression)());
assert.ok(visits<=50000);
assert.equal(descendantQueries,0,'overlapping candidates must share descendant article aggregates');
assert.equal(nodes[0].scrollTop,1000,'stable ranking must retain first maximum');
'''
        self.run_harness(harness, source=source)

    def test_download_verification_reads_bounded_regions(self):
        source = source_prefix()
        source = source.replace('  readFileSync,', '  readFileSync as originalReadFileSync,', 1)
        source = source.replace('  readSync,', '  readSync as originalReadSync,', 1)
        harness = r'''
import assert from 'node:assert/strict';
function readFileSync() {throw new Error('download verification must not read whole files');}
let largestRead=0;
function readSync(...args) {largestRead=Math.max(largestRead,args[3]);return originalReadSync(...args);}
mkdirSync(dataRoot,{recursive:true});
const path=join(dataRoot,'large.pdf');
writeFileSync(path,Buffer.concat([Buffer.from('%PDF-'),Buffer.alloc(2000000,120)]));
verifyDownloadFile(path,'pdf');
assert.throws(()=>verifyDownloadFile(path,'png'),/signature/);
assert.throws(()=>verifyDownloadFile(path,'docx'),/expected docx signature/);
const digest=fileDigest(path);
assert.equal(digest.bytes,2000005);
const office = names => {
  const prefix=Buffer.concat([Buffer.from([80,75,3,4]),Buffer.alloc(2000000)]);
  const entries=names.map(name=>{const encoded=Buffer.from(name),header=Buffer.alloc(46);header.writeUInt32LE(0x02014b50);header.writeUInt16LE(encoded.length,28);return Buffer.concat([header,encoded]);});
  const end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(names.length,10);end.writeUInt32LE(prefix.length,16);
  return Buffer.concat([prefix,...entries,end]);
};
for(const [type,directory] of [['docx','word/'],['xlsx','xl/'],['pptx','ppt/']]) {
  for(const names of [['[Content_Types].xml',directory+'document.xml'],['wrong.xml'],['[Content_Types].xml','other/document.xml']]) {
    const bytes=office(names);writeFileSync(path,bytes);
    let expectedError,actualError;
    try{verifyDownload(bytes,type);}catch(error){expectedError=error;}
    try{verifyDownloadFile(path,type);}catch(error){actualError=error;}
    assert.equal(actualError?.message,expectedError?.message);
    assert.equal(actualError?.code,expectedError?.code);
  }
}
assert.ok(largestRead<=65557,'verification must read only signature/ZIP-tail/individual entries');
'''
        self.run_harness(harness, source=source)

    def test_nested_candidate_rendered_text_reads_are_capped_and_reported(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
for(const count of [256,1024,4096]) {
  let reads=0;
  const nodes=Array.from({length:count},(_,i)=>({i,shadowRoot:null,parentElement:null,scrollTop:0,scrollHeight:1000,clientHeight:200,
    get innerText(){reads++;return 'text'.repeat(count-i);},
    matches(selector){return selector.includes('section, div');},getBoundingClientRect:()=>({width:400,height:300}),
    querySelectorAll:()=>[],
  }));
  for(let i=1;i<count;i++) nodes[i].parentElement=nodes[i-1];
  const document={documentElement:{scrollHeight:1000},createTreeWalker(){let i=0;return {nextNode:()=>nodes[i++]||null};}};
  Object.assign(globalThis,{document,getComputedStyle:()=>({overflowY:'auto'}),window:{scrollY:0,scrollTo(){}}});
  const result=JSON.parse(new Function('return '+scrollExpression)());
  assert.ok(reads<=128,'candidate rendered text reads must be bounded independently of nested DOM size');
  assert.equal(result.ranking_truncated,true);
  assert.equal(result.dom_truncated,true);
  assert.equal(nodes[0].scrollTop,1000);
}
'''
        self.run_harness(harness, source=source)

    def test_text_cleaning_retains_only_bounded_normalized_prefix(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
const cleanPrefix = new Function(boundedTextCleanHelper+';return cleanPrefix;')();
const legacy = value=>value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g,'').replace(/[ \t\f\v]+/g,' ').replace(/ *\n */g,'\n').replace(/\n{3,}/g,'\n\n').trim();
const fixtures=['',' a  b ','a \n \n \n b','\u0000 a\u0001 b','a\r\n b','a\u00a0\u00a0b','\u00a0\n\t a  b \n\n', ' '.repeat(200000)+'evidence\n'+ 'x'.repeat(200000)];
for(const value of fixtures) for(const budget of [0,1,2,10,1000]) assert.equal(cleanPrefix(value,budget),legacy(value).slice(0,budget+1));
'''
        self.run_harness(harness, source=source)

    def test_extraction_does_not_deep_clone_unbounded_source(self):
        source = source_prefix()
        harness = r'''
import assert from 'node:assert/strict';
const text='x'.repeat(2000000);
let largestCloneText=0;
const textNode={nodeType:3,textContent:text,nextSibling:null};
const makeClone=()=>({nodeType:1,tagName:'MAIN',childNodes:[],attributes:[],querySelectorAll:()=>[],
  appendChild(child){this.childNodes.push(child);largestCloneText=Math.max(largestCloneText,(child.textContent||'').length);},
  get textContent(){return this.childNodes.map(node=>node.textContent).join('');},
  get innerHTML(){return this.textContent;},
});
const sourceNode={nodeType:1,tagName:'MAIN',firstChild:textNode,attributes:[],innerText:text,
  matches:selector=>selector.startsWith('article, main,'),
  cloneNode(deep){assert.equal(deep,false,'large source must be copied with bounded shallow traversal');return makeClone();},
};
const document={title:'Fixture',body:sourceNode,documentElement:sourceNode,querySelector:()=>null,
  createTextNode:value=>({nodeType:3,textContent:value}),
  createTreeWalker(){let done=false;return {nextNode(){if(done)return null;done=true;return sourceNode;}};},
};
Object.assign(globalThis,{document,Node:{TEXT_NODE:3,ELEMENT_NODE:1},location:{href:'https://example.test/page'}});
const result=JSON.parse(new Function('return '+extractionExpression({maxContentChars:1000,maxLinks:10}))());
assert.equal(result.text,'x'.repeat(1000));
assert.equal(result.markdown,'x'.repeat(1000));
assert.ok(largestCloneText<=2000,'clone text allocation must obey extraction work budget');
assert.equal(result.truncated.dom,true);
'''
        self.run_harness(harness, source=source)
