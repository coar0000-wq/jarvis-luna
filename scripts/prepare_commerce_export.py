#!/usr/bin/env python3
"""Prepare current evidence, then sign the final immutable export boundary.

Exporter stays strict/nonmutating when stale. This explicit local preparation
never invokes paid models or external storefront writes.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
COMMANDS = (
    ('scripts/build_legal_full.py',),
    ('scripts/build_listing_gate.py',),
    ('scripts/build_product_master.py','--inject-s'),
    ('scripts/build_shopify_shortlist.py',),
    ('scripts/build_mocra_readiness.py',),
    ('scripts/build_listing_gate.py',),
)

def prepare(root=ROOT):
    root = Path(root).resolve()
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', TYPESAFE_ENABLED='0', TYPESAFE_ALLOW_PAID='0', GEMINI_ENABLED='0', GEMINI_ALLOW_PAID='0')
    for key in ('TYPESAFE_SHARED_API_KEY','TYPESAFE_API_KEY','GEMINI_API_KEY'):
        env.pop(key,None)
    for command in COMMANDS:
        subprocess.run([sys.executable,"-X","utf8",*command],cwd=root,env=env,check=True)
    print('COMMERCE_PREPARATION_OK final gate follows all evidence updates')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    try:
        prepare(args.root)
        return 0
    except (OSError,subprocess.CalledProcessError):
        print('COMMERCE_PREPARATION_BLOCKED')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
