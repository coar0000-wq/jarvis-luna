#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 상품 고시 항목과 상세 이미지를 수집한다.

중요 (다이소 실제 구조):
  - 고시 API(/pd/pdr/pdDtl/selPdDtlNtfc)는 대부분 "상세페이지 참조"만 돌려준다.
  - 사용자가 '상품설명 더보기'에서 보는 고시 표는 **상세 이미지**에 있다.
  - 상세 HTML(pdDtlDc)도 텍스트가 아니라 <img> 목록이다.
  - 그래서 텍스트 필드가 비어 있다고 해서 페이지에 고시가 없는 것이 아니다.

이 스크립트는
  1) API에서 쓸 수 있는 값(원산지 등)을 채우고
  2) 상세 이미지 URL을 받아 저장·다운로드하고
  3) 상품명/소개문에서 용량을 보조 추출하고
  4) **이미 채워진 값은 절대 빈 값으로 덮어쓰지 않는다.**
"""

from __future__ import annotations

import html as H
import json
import re
import time
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.gosi_observation_history import (validate_document, attempt, observe_field, merge_images, mark_stale, publish_observation, receipt, sha, utcnow, ProviderStop, classify_stop, assert_not_stopped, persist_stop)
DATA = ROOT / "data"
GOSI = DATA / "gosi.json"
S_RECOMMENDATIONS = DATA / 'daiso_real' / 'shopify_s_recommendations.json'
IMGDIR = DATA / "daiso_real" / "gosi_img"
API = "https://fapi.daisomall.co.kr"
DELAY = 2.0
TIMEOUT = 30
PLACEHOLDER = (
    "상세페이지 참조",
    "상세 페이지 참조",
    "-",
    "",
    "없음",
    "해당없음",
)

# API 고시 항목 번호 → 필드
FIELD = {
    "1": "volume",
    "5": "maker",
    "6": "origin",
    "7": "ingredients",
    "9": "warnings",
    "3": "expiry",
    "4": "usage",
    "8": "functional",
}

PAGE_URL = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"


def post(path: str, pd_no: str) -> dict[str, Any] | None:
    body = json.dumps({"pdNo": str(pd_no)}).encode()
    request = urllib.request.Request(
        API + path,
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.daisomall.co.kr",
            "Referer": PAGE_URL.format(pd_no),
        },
    )
    try:
        raw = urllib.request.urlopen(request, timeout=TIMEOUT).read()
        provenance = receipt(raw, API + path)
        result = json.loads(raw.decode('utf-8'))
        if not isinstance(result, dict):
            raise ValueError('API response must be an object')
        stop = classify_stop(json.dumps(result.get('error') or {}), 'daiso')
        if stop:
            raise stop
        result['_receipt'] = provenance
        return result
    except ProviderStop:
        raise
    except Exception as exc:
        stop = classify_stop(exc, 'daiso')
        if stop:
            raise stop from exc
        print(f'API failed: {type(exc).__name__}')
        return None


def clean(value: Any) -> str:
    text = H.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def is_placeholder(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    if v in PLACEHOLDER:
        return True
    if "상세페이지" in v or "상세 페이지" in v:
        return True
    return False


def set_if_empty(row, key, value, source, provenance=None):
    if not value or is_placeholder(value):
        return False
    evidence = dict(provenance or {'capture_scope': 'local_parser_only', 'source_received_at': None})
    evidence['source'] = source
    return observe_field(row, key, value, evidence)


def seed_from_s_grade(items: dict[str, Any]) -> list[str]:
    """Retain all existing evidence and add identity-only S-grade observation stubs."""
    try:
        document = json.loads(S_RECOMMENDATIONS.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return []
    rows = document.get('recommendations') if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return []
    added = []
    for row in rows:
        if not isinstance(row, dict) or row.get('grade') != 'S':
            continue
        pd_no = str(row.get('pd_no') or '').strip()
        if not re.fullmatch(r'[0-9]{7}', pd_no) or pd_no in items:
            continue
        items[pd_no] = {'product_id': pd_no, 'name': clean(row.get('name')),
            'seeded_from': 'shopify_s_recommendations.json',
            'product_identity_verified': False}
        added.append(pd_no)
    return added


def volume_from_text(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G|kg|KG)\b",
        text,
    )
    if not m:
        return ""
    return f"{m.group(1)}{m.group(2).lower()}"


def download_image(url, dest):
    clean_url = re.sub(r'/dims/.*$', '', url)
    req = urllib.request.Request(clean_url, headers={'User-Agent': UA, 'Referer': 'https://www.daisomall.co.kr/'})
    try:
        raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
        evidence = receipt(raw, clean_url, 'downloaded_image_bytes')
        if len(raw) < 500:
            return None
        dest = dest.with_name(dest.stem + '_' + sha(raw) + dest.suffix)
        if dest.exists() and dest.read_bytes() != raw:
            raise ValueError('image hash collision/tamper')
        if not dest.exists():
            dest.write_bytes(raw)
        return str(dest.relative_to(ROOT)), evidence
    except Exception as exc:
        stop = classify_stop(exc, 'daiso')
        if stop:
            raise stop from exc
        return None

def collect_one(pd_no, row):
    when = utcnow()
    response = post('/pd/pdr/pdDtl/selPdDtlNtfc', pd_no)
    attempt(row, when, 'daiso_ntfc', 'received' if response else 'failed', capture_scope='notice_api_only')
    if response and response.get('success'):
        for item in response.get('data') or []:
            match = re.match(r'\s*(\d+)\.', str(item.get('ntfcIemNm') or ''))
            value = clean(item.get('ntfcIemCn'))
            key = FIELD.get(match.group(1)) if match else None
            if key:
                set_if_empty(row, key, value, 'daiso_api:selPdDtlNtfc', response['_receipt'])
    else:
        mark_stale(row)
    time.sleep(DELAY)
    desc_res = post('/pd/pdr/pdDtl/selPdDtlDesc', pd_no)
    urls = []
    attempt(row, utcnow(), 'daiso_desc', 'received' if desc_res else 'failed', capture_scope='description_api_only')
    if desc_res and desc_res.get('success'):
        desc = ((desc_res.get('data') or {}).get('pdDtlDesc') or {})
        raw_html = H.unescape(desc.get('pdDtlDc') or '')
        urls = re.findall(r'src="(https?://[^"]+)"', raw_html)
        vsip = clean(desc.get('vsipPdDtl') or '')
        if vsip:
            row.setdefault('detail_blurb', vsip[:800])
            evidence = dict(desc_res['_receipt'], derivation='description_text_parser', capture_scope='description_text_only')
            set_if_empty(row, 'volume', volume_from_text(vsip), 'daiso_api:vsipPdDtl', evidence)
    else:
        mark_stale(row)
    set_if_empty(row, 'volume', volume_from_text(str(row.get('name') or '')), 'product_name')
    saved, observations = [], {}
    IMGDIR.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(urls):
        ext = '.png' if '.png' in url.lower() else '.jpg'
        result = download_image(url, IMGDIR / f'{pd_no}_{i:02d}{ext}')
        if result:
            item_path, evidence = result
            saved.append(item_path)
            observations[item_path] = dict(evidence, url=url, intended_product_id=pd_no, product_identity_verified=False)
        else:
            attempt(row, utcnow(), 'daiso_image', 'failed', url=url)
            mark_stale(row)
        time.sleep(0.3)
    merge_images(row, urls, saved, observations)
def main() -> int:
    try:
        doc = json.loads(GOSI.read_text(encoding='utf-8-sig'))
        items = validate_document(doc)
        assert_not_stopped(doc, {'daiso'})
    except ProviderStop as exc:
        print(str(exc))
        return 0
    except (OSError, ValueError) as exc:
        print(f'gosi input invalid: {exc}')
        return 1
    seed_from_s_grade(items)
    for pd_no, row in items.items():
        try:
            collect_one(pd_no, row)
        except ProviderStop as exc:
            attempt(row, utcnow(), 'daiso', 'stopped', reason=str(exc))
            mark_stale(row)
            persist_stop(doc, exc)
            break
        except Exception as exc:
            attempt(row, utcnow(), 'daiso', 'failed', error_type=type(exc).__name__)
            mark_stale(row)
    publish_observation(ROOT, doc)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
