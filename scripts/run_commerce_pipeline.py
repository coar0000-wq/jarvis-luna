#!/usr/bin/env python3
"""Run the existing offline commerce policy chain before runtime/quality checks."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def commands(root=ROOT):
    policy = json.loads((root / 'config/publish_policy.json').read_text(encoding='utf-8'))
    rows = policy['commerce_commands']
    for row in rows:
        if not isinstance(row, list) or not row or not all(isinstance(v, str) for v in row):
            raise ValueError('invalid commerce command')
        script = (root / row[0]).resolve()
        if not script.is_relative_to((root / 'scripts').resolve()) or script.suffix != '.py' or not script.is_file():
            raise ValueError('invalid commerce script path')
    return rows


def main():
    for row in commands():
        print('COMMERCE_STAGE ' + ' '.join(row), flush=True)
        result = subprocess.run([sys.executable, '-B', *row], cwd=ROOT)
        if result.returncode:
            return result.returncode
    print('COMMERCE_PIPELINE_OK offline policy chain complete; authority=false', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
