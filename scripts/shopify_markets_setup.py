#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shopify 마켓 정리: 대한민국 마켓 삭제 + 한국을 뺀 전 세계 판매 지역 구성.

사용자 지시(2026-10-10): 한국에는 팔지 않는다. 미국·영국·유럽·남미·중동 등 한국을 뺀 모든 곳에서 판다.

기본은 점검만 한다(APPLY=0). APPLY=1 일 때만 변경한다.
필요 권한: read_markets, write_markets, read_shipping.

주의: 화장품은 EU/UK 판매 시 현지 책임자(Responsible Person) 와 제품 신고(CPNP/SCPN), 캐나다 CNF 등 규제가 있다.
이 스크립트는 마켓(판매 지역)만 바꾸며 규제 적합성을 보증하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

STORE = os.environ["SHOPIFY_STORE"]
API = os.environ.get("SHOPIFY_API_VERSION", "2025-10")
APPLY = os.environ.get("APPLY", "0").strip().lower() in {"1", "true", "yes"}

EXCLUDED = {"KR"}  # 절대 팔지 않는 나라
# 제재·수출 제한 대상은 넣지 않는다.
SANCTIONED = {"RU", "BY", "IR", "SY", "KP", "CU"}

PLAN = {
    "Latin America": ["AR", "BO", "BR", "BZ", "CL", "CO", "CR", "DO", "EC", "GT", "GY", "HN", "JM", "MX", "NI", "PA", "PE", "PY", "SV", "TT", "UY", "VE"],
    "Middle East": ["AE", "BH", "EG", "IL", "IQ", "JO", "KW", "LB", "OM", "QA", "SA", "TR"],
    "Asia Pacific": ["AU", "HK", "ID", "IN", "JP", "MY", "NZ", "PH", "SG", "TH", "TW", "VN"],
    "Rest of World": ["CA", "CH", "NO", "IS", "ZA", "NG", "KE", "MA", "GH", "UA", "GE", "AM", "KZ"],
}


def token():
    t = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if t:
        return t
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": os.environ["SHOPIFY_CLIENT_ID"],
                                   "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}).encode()
    req = urllib.request.Request(f"https://{STORE}/admin/oauth/access_token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    print("token scopes:", d.get("scope"))
    return d["access_token"]


TOK = None


def gql(q, v=None):
    global TOK
    TOK = TOK or token()
    req = urllib.request.Request(
        f"https://{STORE}/admin/api/{API}/graphql.json", data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": TOK}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    if d.get("errors"):
        raise RuntimeError(json.dumps(d["errors"])[:600])
    return d["data"]


def list_markets():
    d = gql("""{markets(first:50){nodes{id name handle status type
        conditions{regionsCondition{regions(first:250){nodes{... on MarketRegionCountry{code name}}}}}}}}""")
    out = []
    for m in d["markets"]["nodes"]:
        regs = (((m.get("conditions") or {}).get("regionsCondition") or {}).get("regions") or {}).get("nodes") or []
        out.append({"id": m["id"], "name": m["name"], "status": m["status"], "type": m.get("type"),
                    "countries": sorted(r["code"] for r in regs if r.get("code"))})
    return out


def main():
    ms = list_markets()
    print("현재 마켓:")
    for m in ms:
        print(f"  - {m['name']} [{m['status']}] {len(m['countries'])}개국 {m['countries'][:6]}{'...' if len(m['countries']) > 6 else ''}")

    # 1) 한국 마켓 삭제 (한국만 들어 있는 마켓)
    for m in ms:
        if m["countries"] and set(m["countries"]) <= EXCLUDED:
            print(f"한국 마켓 발견: {m['name']} -> {'삭제' if APPLY else '(점검 모드: 삭제 안 함)'}")
            if APPLY:
                r = gql("mutation($id:ID!){marketDelete(id:$id){deletedId userErrors{field message}}}", {"id": m["id"]})["marketDelete"]
                print("  결과:", r)
        elif set(m["countries"]) & EXCLUDED:
            print(f"경고: '{m['name']}' 마켓에 한국이 포함돼 있다 -> 수동 확인 필요")

    # 2) 이미 다른 마켓에 속한 나라는 중복 지정할 수 없다
    ms = list_markets()
    taken = {c for m in ms for c in m["countries"]}
    for name, countries in PLAN.items():
        want = [c for c in countries if c not in EXCLUDED | SANCTIONED and c not in taken]
        if any(m["name"] == name for m in ms) or not want:
            print(f"'{name}': 이미 있거나 추가할 나라 없음")
            continue
        print(f"'{name}' 생성 예정: {len(want)}개국 {want}")
        if APPLY:
            r = gql("""mutation($i:MarketCreateInput!){marketCreate(input:$i){market{id name status}
                 userErrors{field message code}}}""",
                    {"i": {"name": name, "status": "ACTIVE",
                           "conditions": {"regionsCondition": {"regions": [{"countryCode": c} for c in want]}}}})["marketCreate"]
            print("  결과:", json.dumps(r, ensure_ascii=False)[:400])
            taken |= set(want)

    # 3) 배송 구역에 한국이 남아 있는지 점검
    try:
        d = gql("""{deliveryProfiles(first:10){nodes{name profileLocationGroups{locationGroupZones(first:50){nodes{
            zone{name countries{code{countryCode}}}}}}}}}""")
        for prof in d["deliveryProfiles"]["nodes"]:
            for lg in prof["profileLocationGroups"]:
                for z in lg["locationGroupZones"]["nodes"]:
                    codes = [c["code"]["countryCode"] for c in z["zone"]["countries"] if c.get("code") and c["code"].get("countryCode")]
                    print(f"배송구역 [{prof['name']}] {z['zone']['name']}: {len(codes)}개국{' <- 한국 포함!' if 'KR' in codes else ''}")
    except Exception as exc:  # noqa: BLE001
        print("배송구역 점검 실패:", str(exc)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
