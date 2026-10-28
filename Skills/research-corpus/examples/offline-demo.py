#!/usr/bin/env python3
"""Exercise the public corpus CLI using synthetic evidence and no network."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path, help='New directory outside the checkout')
parser.add_argument('--tool', type=Path, default=Path(__file__).resolve().parents[3] / 'Tools/research-corpus')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
root = args.output / 'corpus'
protocol = args.output / 'protocol.json'
protocol.write_text(json.dumps({'question': 'Synthetic telescope evidence', 'scope': 'offline fixture only', 'eligibility': 'Synthetic page', 'date_window': {'start': '2025-01-01', 'end': '2025-12-31'}, 'stopping_rule': 'one search and one source'}))
backend = args.output / 'synthetic-web'
backend.write_text('#!' + sys.executable + '\n' + '''import json, sys
if sys.argv[1] == 'search':
    value = {'query':'synthetic telescope','results':[{'title':'Synthetic telescope','url':'https://example.invalid/telescope','snippet':'Synthetic evidence only'}]}
else:
    value = {'title':'Synthetic telescope','url':'https://example.invalid/telescope','text':'Synthetic telescope evidence.\\nKnown offline observation.','extraction':{'coverage':'abstract-only','limitations':['Synthetic abstract; no full text']},'retrieval':{'access':'public','mode':'synthetic'}}
print(json.dumps(value))
''')
backend.chmod(0o700)
env = {**os.environ, 'RESEARCH_CORPUS_WEB_COMMAND': str(backend)}
def run(*words):
    process = subprocess.run([str(args.tool.resolve()), *map(str, words)], env=env, check=True, capture_output=True, text=True)
    result = json.loads(process.stdout)
    if not result.get('ok'):
        raise RuntimeError(result)
    return result
run('init', root, '--protocol', protocol)
run('discover', root, '--query', 'synthetic telescope', '--operation-id', 'fixture-search', '--profile', 'fixture-no-browser')
manifest = json.loads((root / 'manifest.json').read_text())
source_id = next(iter(manifest['sources']))
run('open', root, '--source-id', source_id, '--profile', 'fixture-no-browser')
run('index', 'build', root, '--db', args.output / 'index.sqlite')
hits = run('index', 'query', root, 'telescope', '--db', args.output / 'index.sqlite')
assert hits['hits'] and hits['hits'][0]['coverage'] == 'abstract-only'
assert run('audit', root)['ok']
ledger = args.output / 'screening-old.csv'
ledger.write_text('source_id,title_abstract_decision,title_abstract_reason,full_text_decision\\n'.replace('\\n','\n') + source_id + ',exclude,Synthetic exclusion,pending\n')
run('screening', 'reconcile', root, '--ledger', ledger, '--output', args.output / 'screening-new.csv')
relocated = args.output / 'relocated'
shutil.copytree(root, relocated)
run('reproduce', relocated, '--offline', '--output', args.output / 'reproduced')
print(json.dumps({'ok': True, 'corpus': str(root), 'relocated': str(relocated), 'source_id': source_id, 'checks': ['committed discovery', 'opened abstract', 'source-only index query', 'audit', 'screening', 'relocated offline reproduction']}))
