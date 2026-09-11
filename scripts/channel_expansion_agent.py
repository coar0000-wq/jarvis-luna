#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS Channel Expansion Agent.

湲곌? ?섏쭛? + 梨꾨꼸 ?댁쁺????꾪빐 ?좉퇋 ?곗씠???먮ℓ/?몃젋??梨꾨꼸 ?꾨낫瑜?吏?띿쟻?쇰줈 諛쒓뎬?섍퀬, ?묎렐 媛?μ꽦/肄섑뀗痢?議댁옱 ?щ?瑜??뺤씤?????꾨낫 DB???꾩쟻?쒕떎.

?덉쟾 ?먯튃:
- 湲곗〈 ?댁쁺 梨꾨꼸???먮룞 ??젣/蹂寃쏀븯吏 ?딅뒗??
- Shopify Admin, 寃곗젣, 愿묎퀬, secrets瑜?嫄대뱶由ъ? ?딅뒗??
- ?좉퇋 ?꾨낫??寃利??꾧퉴吏 candidate ?곹깭濡쒕쭔 ??ν븳??
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except Exception:
    requests = None

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "channel_expansion"
CATALOG = OUT_DIR / "channel_candidates.json"
REPORT = ROOT / "data" / "agents" / "channel_expansion.json"

USER_AGENT = "JARVIS-LUNA-Channel-Expansion/1.0 (+https://github.com/coar0000-wq/jarvis-luna)"

SEEDS = [
    # 湲곌?/怨듦났/?곌뎄 ?곗씠??    {"team":"湲곌? ?섏쭛?","name":"Data.gov","url":"https://data.gov/","kind":"public-data","country":"US","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"U.S. Census Bureau","url":"https://www.census.gov/data.html","kind":"government-data","country":"US","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"U.S. Bureau of Labor Statistics","url":"https://www.bls.gov/data/","kind":"government-data","country":"US","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"FDA Data","url":"https://www.fda.gov/about-fda/data-standards","kind":"regulatory-data","country":"US","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"World Bank Open Data","url":"https://data.worldbank.org/","kind":"international-data","country":"GLOBAL","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"OECD Data Explorer","url":"https://data-explorer.oecd.org/","kind":"international-data","country":"GLOBAL","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"WHO Data","url":"https://data.who.int/","kind":"international-data","country":"GLOBAL","priority":1},
    {"team":"湲곌? ?섏쭛?","name":"UN Data","url":"https://data.un.org/","kind":"international-data","country":"GLOBAL","priority":1},
    # ?먮ℓ/由ы뀒??留덉폆
    {"team":"梨꾨꼸 ?댁쁺?","name":"eBay","url":"https://www.ebay.com/b/Beauty/26395/bn_7000259124","kind":"marketplace","country":"US","priority":1},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Etsy","url":"https://www.etsy.com/market/beauty","kind":"marketplace","country":"US","priority":2},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Sephora","url":"https://www.sephora.com/beauty","kind":"beauty-retail","country":"US","priority":1},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Saks Fifth Avenue","url":"https://www.saksfifthavenue.com/c/beauty","kind":"retail","country":"US","priority":3},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Nordstrom Beauty","url":"https://www.nordstrom.com/browse/beauty","kind":"retail","country":"US","priority":3},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Macy's Beauty","url":"https://www.macys.com/shop/makeup-and-cosmetics","kind":"retail","country":"US","priority":3},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Kroger Marketplace","url":"https://www.kroger.com/","kind":"retail","country":"US","priority":3},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Instacart","url":"https://www.instacart.com/","kind":"commerce","country":"US","priority":3},
    # ?뚯뀥/?몃젋??肄섑뀗痢?    {"team":"梨꾨꼸 ?댁쁺?","name":"Pinterest Trends","url":"https://trends.pinterest.com/","kind":"trend","country":"US","priority":1},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Google Shopping","url":"https://shopping.google.com/","kind":"commerce-signal","country":"US","priority":1},
    {"team":"梨꾨꼸 ?댁쁺?","name":"YouTube Trends","url":"https://trends.google.com/trends/","kind":"trend","country":"US","priority":2},
    {"team":"梨꾨꼸 ?댁쁺?","name":"Reddit Beauty Community","url":"https://www.reddit.com/r/SkincareAddiction/","kind":"community-signal","country":"US","priority":2},
]

KEYWORDS = [
    "beauty marketplace US", "K-beauty US retailer", "beauty trends US", "cosmetics trend data",
    "public consumer data US", "retail data API US", "beauty product reviews US",
]


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def normalize_url(url):
    p = urlparse(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}"


def test_url(url):
    if requests is None:
        return {"reachable": None, "status_code": None, "error": "requests_not_installed"}
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        text = (r.text or '')[:300000]
        return {
            "reachable": 200 <= r.status_code < 400,
            "status_code": r.status_code,
            "final_url": r.url,
            "content_length": len(r.text or ''),
            "has_html": bool(re.search(r'<html|<body|<main', text, re.I)),
        }
    except Exception as exc:
        return {"reachable": False, "status_code": None, "error": f"{type(exc).__name__}: {exc}"}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = load(CATALOG, {"schema_version": 1, "candidates": []})
    if not isinstance(existing, dict):
        existing = {"schema_version": 1, "candidates": []}
    rows = existing.get("candidates") if isinstance(existing.get("candidates"), list) else []
    by_url = {normalize_url(str(x.get("url"))): x for x in rows if isinstance(x, dict) and x.get("url")}

    results = []
    checked = []
    for seed in SEEDS:
        key = normalize_url(seed["url"])
        probe = test_url(seed["url"])
        item = {**seed, **probe, "status": "candidate" if probe.get("reachable") else "unverified", "checked_at": now()}
        prior = by_url.get(key, {})
        merged = {**prior, **item}
        by_url[key] = merged
        checked.append(merged)

    candidates = sorted(by_url.values(), key=lambda x: (int(x.get("priority") or 9), str(x.get("name") or "")))
    out = {
        "schema_version": 1,
        "generated_at": now(),
        "discovery_mode": "seed_catalog_plus_health_probe",
        "candidate_count": len(candidates),
        "verified_count": sum(1 for x in candidates if x.get("reachable") is True),
        "candidates": candidates,
        "next_expansion_queries": KEYWORDS,
    }
    save(CATALOG, out)

    report = {
        "agent": "Channel-Expansion",
        "generated_at": now(),
        "institutions_team": {
            "role": "湲곌?/怨듦났/?곌뎄/洹쒖젣 ?곗씠???좉퇋 ?뚯뒪 諛쒓뎬",
            "checked": sum(1 for x in checked if x.get("team") == "湲곌? ?섏쭛?"),
            "verified": sum(1 for x in checked if x.get("team") == "湲곌? ?섏쭛?" and x.get("reachable") is True),
        },
        "channel_team": {
            "role": "?먮ℓ/由ы뀒???몃젋??而ㅻ??덊떚 ?좉퇋 梨꾨꼸 諛쒓뎬",
            "checked": sum(1 for x in checked if x.get("team") == "梨꾨꼸 ?댁쁺?"),
            "verified": sum(1 for x in checked if x.get("team") == "梨꾨꼸 ?댁쁺?" and x.get("reachable") is True),
        },
        "verified_candidates": [x for x in candidates if x.get("reachable") is True],
        "unverified_candidates": [x for x in candidates if x.get("reachable") is not True],
        "safety": {"auto_activation": False, "shopify_write": False, "ads_write": False, "secrets_write": False},
        "catalog_path": str(CATALOG.relative_to(ROOT)),
    }
    save(REPORT, report)
    print("CHANNEL EXPANSION COMPLETE")
    print("candidates:", len(candidates))
    print("verified:", out["verified_count"])
    print("institutions verified:", report["institutions_team"]["verified"])
    print("channel verified:", report["channel_team"]["verified"])


if __name__ == "__main__":
    main()
