"""Standard-library checks only: never import inference or download modules."""
import ast
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVISION = '914f7f89142e33e77833254d9c9b90c3cef7303b'
SOURCES = ['download.py', 'search.py', 'smoke.py', 'vision_smoke.py', 'wait_and_run.py']
for name in SOURCES:
    file = ROOT / 'embeddinggemma' / name
    text = file.read_text(encoding='utf-8-sig')
    ast.parse(text, filename=str(file))
    assert 'C:/Users/' not in text and 'C:\\Users\\' not in text, name
print('PASS: five Python source ASTs; no hardcoded user installation paths')
metadata = json.loads((ROOT / 'embeddinggemma' / 'model-api.json').read_text())
assert metadata == {'id': 'google/embeddinggemma-2', 'sha': REVISION}
for name in ['search.py', 'smoke.py', 'vision_smoke.py']:
    text = (ROOT / 'embeddinggemma' / name).read_text()
    for guard in ['HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'local_files_only=True', 'trust_remote_code=False', 'GlobalMemoryStatusEx']:
        assert guard in text, (name, guard)
    assert 'torch.float16' not in text and 'torch.half' not in text, name
assert 'torch.bfloat16' in (ROOT / 'embeddinggemma' / 'search.py').read_text()
assert 'torch.float32' in (ROOT / 'embeddinggemma' / 'vision_smoke.py').read_text()
assert 'previous_attempt' not in (ROOT / 'embeddinggemma' / 'vision_smoke.py').read_text()
print('PASS: pinned public seed, offline/no-remote-code/memory/dtype guard presence')

def run_case(args, expected, marker):
    result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'embeddinggemma' / 'search.py'), *args], capture_output=True, text=True, timeout=15)
    output = result.stdout + result.stderr
    assert result.returncode == expected and marker in output, (args, result.returncode, output)
    assert 'Loading offline' not in output and 'ModuleNotFoundError' not in output, output

run_case(['--help'], 0, '--documents-json')
with tempfile.TemporaryDirectory(prefix='.scratch-', dir=ROOT / 'tests') as folder:
    docs = pathlib.Path(folder) / 'documents.json'
    docs.write_text(json.dumps([{'id': 'fixture', 'text': 'Authored validation-only input.'}]), encoding='utf-8')
    base = ['--documents-json', str(docs)]
    run_case([*base, '--query', ''], 2, 'query must contain')
    run_case([*base, '--query', 'x' * 1001], 2, 'query must contain')
    run_case([*base, '--query', 'x', '--top-k', '0'], 2, 'top-k must be')
    run_case([*base, '--query', 'x', '--top-k', '11'], 2, 'top-k must be')
    run_case([*base, '--query', 'x', '--dimension', '512'], 2, 'invalid choice')
    docs.write_text('[]', encoding='utf-8')
    run_case([*base, '--query', 'x'], 2, 'documents must be a list')
    docs.write_text(json.dumps([{'id': 'same', 'text': 'a'}, {'id': 'same', 'text': 'b'}]), encoding='utf-8')
    run_case([*base, '--query', 'x'], 2, 'document ids must be unique')
    docs.write_text(json.dumps([{'id': 'fixture', 'text': 'x' * 5001}]), encoding='utf-8')
    run_case([*base, '--query', 'x'], 2, 'each document needs')
    docs.write_bytes(b' ' * 4_000_001)
    run_case([*base, '--query', 'x'], 2, 'at most 4MB')
print('PASS: search --help plus nine pre-import invalid-input rejections (15-second timeout each)')
# Parse JavaScript only; never generate or execute the PE fixture.
node = sys.argv[1] if len(sys.argv) > 1 else 'node'
result = subprocess.run([node, '--check', str(ROOT / 'create-owned-fixture.mjs')], capture_output=True, text=True, timeout=15)
assert result.returncode == 0, result.stdout + result.stderr
print('PASS: JavaScript syntax only (15-second timeout); fixture not generated')
print('NO inference, provider execution, downloads, installs, or API calls performed')
