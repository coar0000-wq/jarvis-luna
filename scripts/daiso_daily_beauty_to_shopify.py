#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS LUNA - 다이소몰 '오늘의 뷰티 추천' -> Shopify(coarfamily) 일일 자동 등록
==========================================================================

매일 오전 10시(KST)에 GitHub Actions 가 실행한다.

흐름
----
1. 다이소몰 뷰티관 '오늘의 뷰티 추천' 공개 API 에서 카테고리별 후보를 읽는다.
   스킨케어 / 메이크업 / 바디케어 각 1개.
2. 판매 가능(품절 아님, 재고 > 0) 이고, 이미 Shopify 에 등록하지 않은 상품만 고른다.
   중복 판단은 Shopify 태그 `daiso-pd-<다이소 상품번호>` 로 한다 (별도 상태 파일 없음).
3. 영문 제목/설명을 만든다. GEMINI_API_KEY(무료 티어)가 있으면 사용하고,
   없거나 실패하면 정본 사실(브랜드·상품명·용량)만으로 규칙 기반 초안을 쓴다.
   효능·인증·임상 문구는 어느 경로로도 지어내지 않는다.
4. Shopify Admin GraphQL 로 상품을 만들고(ACTIVE), 가격을 설정하고, 온라인 스토어에 게시한다.
   태그: skincare / makeup / body (스마트 컬렉션 자동 분류) + daiso-daily + daiso-pd-<번호>.

환경변수
--------
SHOPIFY_STORE            예: coarfamily.myshopify.com
SHOPIFY_CLIENT_ID        Dev Dashboard 앱 클라이언트 ID (client credentials)
SHOPIFY_CLIENT_SECRET    Dev Dashboard 앱 클라이언트 암호
SHOPIFY_ADMIN_TOKEN      (대안) 이미 발급된 Admin API 토큰
GEMINI_API_KEY           (선택) 무료 티어 키
DRY_RUN                  1 이면 Shopify 에 쓰지 않고 선택 결과만 출력
FX_KRW_PER_USD           기본 1400
PRICE_MULTIPLIER         기본 3.5  (원가 USD x 배수 + PRICE_FIXED_USD)
PRICE_FIXED_USD          기본 5.0  (해외 배송·수수료 고정분)
PRICE_MIN_USD            기본 9.99
ONLY_CATEGORIES          예: "skincare,body" (테스트용)
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DAISO_API = "https://fapi.daisomall.co.kr/ds/recommend/beauty-health-home-v2"
DAISO_CDN = "https://cdn.daisomall.co.kr"
DAISO_ITEM = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo="
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-10")

UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

CATEGORIES = [
    # (태그, 다이소 카테고리명, 다이소 카테고리 번호, Shopify productType)
    ("skincare", "스킨케어", "BH_CTGR_00002", "Skincare"),
    ("makeup", "메이크업", "BH_CTGR_00006", "Makeup"),
    ("body", "바디케어", "BH_CTGR_00012", "Body Care"),
]

BRAND_EN = {
    "VT": "VT",
    "본셉": "Bonsep",
    "본셉 스킨케어": "Bonsep",
    "셀더마": "Celderma",
    "셀더마 데일리": "Celderma",
    "더마펌": "Dermafirm",
    "후시덤": "Fucidin",
    "닥터오라클": "Dr.Oracle",
    "바이플라워": "By Flower",
}

FX = float(os.environ.get("FX_KRW_PER_USD", "1400"))
MULT = float(os.environ.get("PRICE_MULTIPLIER", "3.5"))
FIXED = float(os.environ.get("PRICE_FIXED_USD", "5.0"))
PMIN = float(os.environ.get("PRICE_MIN_USD", "9.99"))
DRY_RUN = os.environ.get("DRY_RUN", "0").strip().lower() in {"1", "true", "yes"}
ONLY = {x.strip() for x in os.environ.get("ONLY_CATEGORIES", "").split(",") if x.strip()}


def log(*a):
    print(*a, flush=True)


def http_json(url, payload=None, headers=None, method=None, timeout=30):
    data = None
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:500]}


# ---------------------------------------------------------------- Daiso


def fetch_daiso(cat_name, cat_no):
    status, body = http_json(
        DAISO_API,
        {"srchTy": "beauty", "categoryId": cat_name, "categoryNo": cat_no, "limit": 29, "minSize": 6},
        headers={"Origin": "https://www.daisomall.co.kr", "Referer": "https://www.daisomall.co.kr/"},
    )
    if status != 200:
        raise RuntimeError(f"daiso {cat_name} HTTP {status}: {str(body)[:200]}")
    return (body.get("data") or {}).get("list") or []


def sellable(p):
    try:
        price = int(str(p.get("pdPrc") or "0"))
    except ValueError:
        return False
    return (
        price > 0
        and p.get("soldOutYn") == "N"
        and p.get("exhYn") != "N"
        and int(p.get("onlStckQy") or 0) > 0
        and bool(p.get("pdImgUrl"))
    )


def score(p):
    try:
        rating = float(p.get("avgStscVal") or 0)
        reviews = int(p.get("revwCnt") or 0)
    except ValueError:
        return 0.0
    return rating * math.log(reviews + 1)


# ---------------------------------------------------------------- Shopify


class Shopify:
    def __init__(self):
        self.store = os.environ["SHOPIFY_STORE"].replace("https://", "").strip("/")
        self.token = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
        self.token_at = time.time()
        if not self.token:
            self._exchange()

    def _exchange(self):
        cid = os.environ["SHOPIFY_CLIENT_ID"]
        sec = os.environ["SHOPIFY_CLIENT_SECRET"]
        body = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}
        ).encode()
        req = urllib.request.Request(
            f"https://{self.store}/admin/oauth/access_token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                self.token = json.loads(r.read().decode())["access_token"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Shopify token exchange failed: HTTP {e.code} {e.read().decode()[:200]}")

    def gql(self, query, variables=None):
        status, body = http_json(
            f"https://{self.store}/admin/api/{API_VERSION}/graphql.json",
            {"query": query, "variables": variables or {}},
            headers={"X-Shopify-Access-Token": self.token},
        )
        if status != 200 or body.get("errors"):
            raise RuntimeError(f"Shopify GraphQL HTTP {status}: {json.dumps(body)[:600]}")
        return body["data"]

    def exists(self, pd_no):
        d = self.gql(
            "query($q:String!){products(first:1,query:$q){nodes{id title}}}",
            {"q": f"tag:daiso-pd-{pd_no}"},
        )
        return bool(d["products"]["nodes"])

    def existing_titles(self):
        d = self.gql("{products(first:250){nodes{title}}}")
        return {n["title"].lower() for n in d["products"]["nodes"]}

    def online_store_publication(self):
        d = self.gql("{publications(first:20){nodes{id name}}}")
        for n in d["publications"]["nodes"]:
            if n["name"].lower().startswith("online store") or "온라인" in n["name"]:
                return n["id"]
        return None

    def create(self, item, pub_id):
        d = self.gql(
            """
mutation($product:ProductCreateInput!,$media:[CreateMediaInput!]){
  productCreate(product:$product,media:$media){
    product{id handle onlineStoreUrl variants(first:1){nodes{id}}}
    userErrors{field message}
  }
}""",
            {
                "product": {
                    "title": item["title"],
                    "descriptionHtml": item["description_html"],
                    "vendor": item["vendor"],
                    "productType": item["product_type"],
                    "tags": item["tags"],
                    "status": item.get("status", "ACTIVE"),
                },
                "media": [
                    {"originalSource": u, "alt": item["title"], "mediaContentType": "IMAGE"}
                    for u in item["images"]
                ],
            },
        )["productCreate"]
        if d["userErrors"]:
            raise RuntimeError(f"productCreate: {d['userErrors']}")
        prod = d["product"]
        vid = prod["variants"]["nodes"][0]["id"]
        u = self.gql(
            """
mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$pid,variants:$v){userErrors{field message}}
}""",
            {"pid": prod["id"], "v": [{"id": vid, "price": f"{item['price_usd']:.2f}"}]},
        )["productVariantsBulkUpdate"]
        if u["userErrors"]:
            raise RuntimeError(f"variant price: {u['userErrors']}")
        if pub_id and item.get("status", "ACTIVE") == "ACTIVE":
            p = self.gql(
                """
mutation($id:ID!,$input:[PublicationInput!]!){
  publishablePublish(id:$id,input:$input){userErrors{field message}}
}""",
                {"id": prod["id"], "input": [{"publicationId": pub_id}]},
            )["publishablePublish"]
            if p["userErrors"]:
                raise RuntimeError(f"publish: {p['userErrors']}")
        return prod


# ---------------------------------------------------------------- Copy


def clean_name(name):
    name = re.sub(r"\[[^\]]*\]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def usd_price(krw):
    raw = krw / FX * MULT + FIXED
    return max(PMIN, math.floor(raw) + 0.99)


def fallback_copy(p, cat):
    brand = (p.get("brndNm") or "").strip()
    brand_en = BRAND_EN.get(brand, brand)
    name = clean_name(p.get("pdNm") or "")
    for k in (brand, brand_en):
        if k and name.startswith(k):
            name = name[len(k):].strip()
    title = f"{brand_en} {name}".strip()
    html = (
        f"<p>{title} from Daiso Korea's daily beauty picks.</p>"
        f"<p><strong>Category:</strong> {cat[3]}</p>"
        f"<p><strong>Origin:</strong> Made for the Korean market and sourced from Daiso Mall (Korea).</p>"
    )
    return title, html


def gemini_copy(p, cat):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    facts = {
        "korean_name": clean_name(p.get("pdNm") or ""),
        "brand_korean": p.get("brndNm"),
        "category": cat[3],
    }
    prompt = (
        "You write product listings for an English-language Korean beauty store. "
        "Translate ONLY the facts below into an English title (brand + product name + size, "
        "like 'VT PDRN Radiance Cream 50 ml') and a 2-sentence neutral description. "
        "Do NOT invent ingredients, effects, clinical claims, certifications, or numbers that are "
        "not in the facts. Return JSON: {\"title\":\"...\",\"description\":\"...\"}.\n"
        f"FACTS: {json.dumps(facts, ensure_ascii=False)}"
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    status, body = http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        },
    )
    if status != 200:
        log(f"  gemini skipped: HTTP {status}")
        return None
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        j = json.loads(text)
        title = re.sub(r"\s+", " ", j["title"]).strip()
        desc = re.sub(r"\s+", " ", j["description"]).strip()
        if not title or len(title) > 120 or re.search(r"[가-힣]", title):
            return None
        return title, f"<p>{desc}</p>"
    except (KeyError, IndexError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------- Main


def pick(cat, shop, titles):
    items = [p for p in fetch_daiso(cat[1], cat[2]) if sellable(p)]
    items.sort(key=score, reverse=True)
    for p in items:
        if shop is not None and shop.exists(p["pdNo"]):
            continue
        return p
    return None


def main():
    shop = None
    titles = set()
    pub = None
    have_creds = bool(os.environ.get("SHOPIFY_STORE")) and (
        os.environ.get("SHOPIFY_ADMIN_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET")
    )
    if have_creds:
        shop = Shopify()
        titles = shop.existing_titles()
        pub = shop.online_store_publication()
        log(f"Shopify OK. online store publication: {pub}")
    elif not DRY_RUN:
        log("ERROR: Shopify credentials are missing (SHOPIFY_STORE + token/client secret).")
        return 2
    else:
        log("DRY_RUN without Shopify credentials: duplicate check skipped.")

    results, failures = [], 0
    for cat in CATEGORIES:
        if ONLY and cat[0] not in ONLY:
            continue
        log(f"== {cat[1]} ({cat[0]})")
        try:
            p = pick(cat, shop, titles)
            if not p:
                log("  no eligible product")
                results.append({"category": cat[0], "status": "skipped_no_candidate"})
                continue
            krw = int(p["pdPrc"])
            copy = gemini_copy(p, cat) or fallback_copy(p, cat)
            title, html = copy
            html += f'<p><small>Source: Daiso Mall item {p["pdNo"]}.</small></p>'
            images = [DAISO_CDN + u for u in (p.get("pdImgUrlList") or [p["pdImgUrl"]])[:4]]
            item = {
                "title": title,
                "description_html": html,
                "vendor": BRAND_EN.get((p.get("brndNm") or "").strip(), p.get("brndNm") or "Daiso"),
                "product_type": cat[3],
                "tags": [cat[0], "daiso-daily", f"daiso-pd-{p['pdNo']}", "k-beauty"],
                "images": images,
                "price_usd": usd_price(krw),
                # 영문 제목을 만들지 못하면(Gemini 실패) 한글 제목 상품을 공개하지 않고 초안으로 둔다.
                "status": "DRAFT" if re.search(r"[가-힣]", title) else "ACTIVE",
            }
            log(f"  pick: {p['pdNo']} {clean_name(p['pdNm'])} | {krw} KRW -> ${item['price_usd']:.2f} | {title}")
            rec = {
                "category": cat[0],
                "daiso_pdNo": p["pdNo"],
                "daiso_name": clean_name(p["pdNm"]),
                "daiso_url": DAISO_ITEM + p["pdNo"],
                "krw": krw,
                "usd": item["price_usd"],
                "title": title,
                "images": images,
            }
            if DRY_RUN or shop is None:
                rec["status"] = "dry_run"
            else:
                prod = shop.create(item, pub)
                rec["status"] = "created" if item["status"] == "ACTIVE" else "created_draft_needs_english_title"
                rec["shopify_id"] = prod["id"]
                rec["handle"] = prod["handle"]
                rec["url"] = f"https://{shop.store}/products/{prod['handle']}"
                titles.add(title.lower())
            results.append(rec)
        except Exception as exc:  # keep going so one category failure doesn't block the others
            failures += 1
            log(f"  FAILED: {exc}")
            results.append({"category": cat[0], "status": "failed", "error": str(exc)[:500]})

    out = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": DRY_RUN,
        "results": results,
    }
    os.makedirs("out", exist_ok=True)
    with open("out/daiso_daily_beauty_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## 다이소 오늘의 뷰티 추천 -> Shopify 등록\n\n")
            f.write("| 카테고리 | 상태 | 상품 | 가격 | 링크 |\n|---|---|---|---|---|\n")
            for r in results:
                f.write(
                    f"| {r['category']} | {r['status']} | {r.get('title', r.get('error', ''))} | "
                    f"{('$%.2f' % r['usd']) if 'usd' in r else ''} | {r.get('url', r.get('daiso_url', ''))} |\n"
                )
    log(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
