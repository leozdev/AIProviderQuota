"""Test-only executable-engine fixture, copied into an isolated test package."""
import argparse
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument('--providers', default='codex,claude,ollama')
parser.add_argument('--force', action='store_true')
args = parser.parse_args()
cache = Path(os.environ['XDG_CACHE_HOME'])
selected = args.providers.split(',') if args.providers else []
with (cache / 'fixture-requests.jsonl').open('a') as record:
    record.write(json.dumps(selected) + '\n')
# Give the integration test time to change configuration during collection.
time.sleep(1)
data = json.loads(Path(__file__).with_name('quota-demo.json').read_text())
now = time.time()
offset = now - data['generated_at']
data['generated_at'] = now
data['providers'] = [p for p in data['providers'] if p['id'] in selected]
for provider in data['providers']:
    provider['fetched_at'] += offset
    for window in provider['windows']:
        if window['resets_at']:
            window['resets_at'] += offset
with (cache / 'fixture-completions.jsonl').open('a') as record:
    record.write(json.dumps(selected) + '\n')
print(json.dumps(data), flush=True)
