import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
HARNESS = r'''
import assert from 'node:assert/strict';
function fixture(specs, {shadow = false, body = true, html = true, instrument = true} = {}) {
  const counts = {reads: 0, queries: 0};
  const make = (spec, id) => {
    const text = spec.text ?? `${id}:` + 'x'.repeat(spec.length ?? 20);
    const node = {
      id, textContent: text, scrollTop: 0, scrollHeight: 1000, clientHeight: 300,
      get innerText() { if (instrument) counts.reads++; return text; },
      querySelectorAll(selector) {
        if (instrument) counts.queries++;
        return selector === 'a' ? [{innerText: 'a'.repeat(spec.links ?? 0)}] : Array(spec.articles ?? 0).fill({});
      },
      getBoundingClientRect: () => ({width: 400, height: spec.height ?? 300}),
      cloneNode: () => ({nodeType: 1, tagName: 'DIV', textContent: text,
        childNodes: [{nodeType: 3, textContent: text}], innerHTML: text, querySelectorAll: () => []})
    };
    return node;
  };
  const candidates = specs.map((spec, index) => make(spec, index));
  const query = selector => selector === '*' ? [] :
    selector.startsWith('article, main,') || selector.startsWith('main, [role="main"],') ? candidates : [];
  const shadowRoot = {querySelectorAll: query};
  const document = {title: 'Fixture', body: body ? make({text: 'body'}, 'body') : null,
    documentElement: html ? make({text: 'html'}, 'html') : null,
    querySelector: () => null,
    querySelectorAll: shadow ? selector => selector === '*' ? [{shadowRoot}] : [] : query};
  Object.assign(globalThis, {document, Node: {TEXT_NODE: 3, ELEMENT_NODE: 1},
    location: {href: 'https://fixture.test/page'}, getComputedStyle: () => ({overflowY: 'auto'}),
    window: {scrollY: 0, scrollTo(x, y) {this.scrollY = y;}}});
  return {counts, candidates, document};
}
const expressions = {extract: extractionExpression({maxContentChars: 100000, maxLinks: 100}),
  frame: frameExtractExpression, scroll: scrollExpression};
function evaluate(kind, specs, options = {}) {
  const state = fixture(specs, options);
  const result = JSON.parse(new Function('return ' + expressions[kind])());
  const selected = kind === 'scroll' ? state.candidates.findIndex(node => node.scrollTop > 0) : result.text;
  return {...state, result, selected};
}
const mode = Bun.argv[2];
if (mode.startsWith('counts-')) {
  for (const kind of [mode.slice(7)]) {
    const specs = Array.from({length: 100}, (_, i) => ({length: (i * 73) % 101}));
    const state = evaluate(kind, specs);
    assert.equal(state.counts.queries, 100, kind + ' must score each candidate once');
    assert.equal(state.counts.reads, kind === 'scroll' ? 100 : 101);
  }
} else {
  for (const kind of Object.keys(expressions)) {
    const specs = [{text: 'first', links: 100}, {text: 'winner'}, {text: 'last'}];
    assert.equal(evaluate(kind, specs).selected, kind === 'scroll' ? 1 : 'winner');
    assert.equal(evaluate(kind, [{text: 'aaaa'}, {text: 'bbbb'}]).selected, kind === 'scroll' ? 0 : 'aaaa');
    assert.equal(evaluate(kind, [{text: 'only'}]).selected, kind === 'scroll' ? 0 : 'only');
    const one = evaluate(kind, [{text: 'only'}]);
    assert.equal(one.counts.queries, 0, 'one candidate needs no score');
    const empty = evaluate(kind, []);
    assert.equal(empty.selected, kind === 'scroll' ? -1 : 'body');
    assert.equal(evaluate(kind, [], {body: false}).selected, kind === 'extract' ? 'html' : kind === 'frame' ? '' : -1);
    assert.equal(evaluate(kind, [], {body: false, html: false}).selected, kind === 'scroll' ? -1 : '');
    if (kind !== 'frame') assert.equal(evaluate(kind, specs, {shadow: true}).selected, kind === 'scroll' ? 1 : 'winner');
  }
  assert.equal(evaluate('scroll', [{text: 'longest', height: 100}, {text: 'b'}]).selected, 1);
  assert.equal(evaluate('scroll', [{text: 'longest'}, {text: 'b', articles: 1}]).selected, 1);
  assert.equal(evaluate('frame', [{text: 'longest', links: 100}, {text: 'b', links: 100}]).selected, 'longest');
}
'''


class DomSelectionTests(unittest.TestCase):
    def run_harness(self, mode):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / 'selection.ts'
            source = (ROOT / 'Tools/web-research').read_text()
            self.assertEqual(source.count('\nconst args = Bun.argv.slice(2);'), 1)
            path.write_text(source.split('\nconst args = Bun.argv.slice(2);')[0] + HARNESS)
            result = subprocess.run(['bun', str(path), mode], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_each_candidate_scored_once(self):
        for kind in ('extract', 'frame', 'scroll'):
            with self.subTest(kind=kind):
                self.run_harness('counts-' + kind)

    def test_selection_ties_fallbacks_and_shadow_roots(self):
        self.run_harness('semantics')
