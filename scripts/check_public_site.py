#!/usr/bin/env python3
"""Validate exact public inventory, projections, links and deterministic hashes."""
import argparse
import json
import math
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, unquote
from build_public_site import STATIC_FILES, SCHEMAS, BASE_PATH, UNSAFE, project, digest, encoded


def local_reference(value):
    value=value.strip(); u=urlsplit(value)
    if not value or value.startswith(('#','//')) or u.scheme in {'https','http','mailto'}: return None
    if u.scheme: raise ValueError('unsafe URL scheme in public site')
    relative=unquote(u.path)
    if not relative: return None
    if relative.startswith(BASE_PATH): relative=relative[len(BASE_PATH):]
    elif relative.startswith('/'): raise ValueError(f'project base-path incompatible: {relative}')
    p=PurePosixPath(relative)
    if '..' in p.parts or '\\' in relative: raise ValueError('public path traversal')
    return str(p)


def validate(root):
    root=Path(root)
    if root.is_symlink(): raise ValueError('public root symlink forbidden')
    paths=list(root.rglob('*'))
    if any(p.is_symlink() for p in paths): raise ValueError('public symlink forbidden')
    found={p.relative_to(root).as_posix() for p in paths if p.is_file()}
    allowed=set(STATIC_FILES)|set(SCHEMAS)|{'deployment.json'}
    if found!=allowed: raise ValueError(f'public inventory mismatch extra={sorted(found-allowed)} missing={sorted(allowed-found)}')
    m=json.loads((root/'deployment.json').read_text(encoding='utf-8'))
    if m.get('base_path')!=BASE_PATH or not m.get('public_files_only') or not re.fullmatch('[0-9a-f]{40}',m.get('commit','')):
        raise ValueError('invalid deployment provenance')
    hashes={f:digest((root/f).read_bytes()) for f in sorted(allowed-{'deployment.json'})}
    if hashes!=m.get('files') or digest(encoded(hashes))!=m.get('site_hash'): raise ValueError('public artifact hash mismatch')
    for f,schema in SCHEMAS.items():
        text=(root/f).read_text(encoding='utf-8'); data=json.loads(text)
        if project(data,schema)!=data: raise ValueError(f'non-public fields/values in {f}')
        if UNSAFE.search(text): raise ValueError(f'sensitive string in {f}')
    html=(root/'index.html').read_text(encoding='utf-8')
    if UNSAFE.search(html): raise ValueError('sensitive string in public HTML')
    refs=re.findall(r'(?:src|href)=[\"\']([^\"\']+)[\"\']',html)
    refs+=re.findall(r'url\([\"\']?([^\"\')]+)',html)
    refs+=re.findall(r"getJSON\(['\"]([^'\"]+)['\"]\)",html)
    refs+=re.findall(r"['\"](images/[^'\"]+\.(?:png|jpg|svg))['\"]",html)
    for ref in refs:
        if '+' in ref or 'esc(' in ref: continue  # JavaScript templates, not literal URLs.
        relative=local_reference(ref)
        if relative and relative not in found: raise ValueError(f'broken/non-public frontend reference: {relative}')
    # Essential display contracts must survive projection, including prices and safety flags.
    runtime=json.loads((root/'data/dashboard_runtime.json').read_text(encoding='utf-8'))
    if not isinstance(runtime.get('teams'),list) or not runtime.get('generated_at'): raise ValueError('public runtime display contract missing')
    graph=runtime.get('graph') or {}
    for key in ('notes','links','records','sources','topics','dangling_links'):
        if type(graph.get(key)) is not int or graph[key] < 0:
            raise ValueError('public graph numeric display contract missing: ' + key)
    market=json.loads((root/'data/market_team.json').read_text(encoding='utf-8'))
    fx=(market.get('health') or {}).get('exchange_rate')
    if type(fx) not in (int,float) or not math.isfinite(fx) or not 500 <= fx <= 3000:
        raise ValueError('public market exchange-rate numeric display contract missing')
    score=json.loads((root/'data/daiso_real/shopify_demand_score.json').read_text(encoding='utf-8'))
    if not isinstance(score.get('all_scored'),list) or not isinstance(score.get('grade_summary'),dict): raise ValueError('public scores missing')
    price=json.loads((root/'data/pricing_model.json').read_text(encoding='utf-8'))
    for offer in (price.get('offers') or {}).values():
        if isinstance(offer,dict):
            for k in ('price_usd','unit_price_usd','net_profit_usd','margin_pct'):
                if type(offer.get(k)) not in (int,float): raise ValueError('public offer numeric contract missing')
    comparison=json.loads((root/'data/daiso_real/candidate_comparison.json').read_text(encoding='utf-8'))
    if comparison.get('may_publish') is not False or comparison.get('may_replace_operating_products') is not False:
        raise ValueError('public comparison safety flags missing')
    return m


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('dist'));a=p.parse_args()
    m=validate(a.root);print(f"PUBLIC_SITE_VALID commit={m['commit']} files={len(m['files'])} site_hash={m['site_hash']}")
    return 0
if __name__=='__main__': raise SystemExit(main())
