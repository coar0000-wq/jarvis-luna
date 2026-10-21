#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS LUNA - 정본 S등급 다이소 뷰티 후보 -> Shopify 일일 등록
==========================================================================

매일 오전 10시(KST)에 GitHub Actions 가 실행한다.

흐름
----
1. 정본 채점표에서 S등급만 읽고 스킨케어 / 메이크업 / 바디케어 각 최대 1개를 고른다.
   바디 연구 초안 예외는 별도 정책 opt-in과 정확한 비공개 소유자 승인이 모두 있을 때만 시도한다.
2. 판매 가능(품절 아님, 재고 > 0) 이고, 이미 Shopify 에 등록하지 않은 상품만 고른다.
   이력 레지스트리와 Shopify 전체 카탈로그의 번호·이름·태그·SKU로 중복을 막는다.
3. 영문 제목/설명을 만든다. GEMINI_API_KEY(무료 티어)가 있으면 사용하고,
   없거나 실패하면 정본 사실(브랜드·상품명·용량)만으로 규칙 기반 초안을 쓴다.
   효능·인증·임상 문구는 어느 경로로도 지어내지 않는다.
4. Shopify 에 초안으로 만들고 가격·변형·이미지를 다시 확인한 뒤 안전 게이트가 충족될 때만 게시한다.
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
import copy
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import base64
import hashlib
from html import escape
import tempfile
import gate_signature
from datetime import datetime, timezone
from pathlib import Path

DAISO_API = "https://fapi.daisomall.co.kr/ds/recommend/beauty-health-home-v2"
DAISO_CDN = "https://cdn.daisomall.co.kr"
DAISO_ITEM = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo="
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-10")

UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

# 판매 전략 정책 (config/daiso_commerce_strategy.json): 3개 카테고리, S등급 전용, 근거 기반 가격,
# 마진은 경고로만 공개, 이미지는 제품 전용으로 검수 기록이 있는 허용 목록. 파일이 없거나 안전 요건을 푸는 값이면 시작 단계에서 중단한다.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import manufacturer_safety  # noqa: E402
import product_accuracy  # noqa: E402
import gallery_review  # noqa: E402
import owner_draft_approval  # noqa: E402
import body_category_fallback as body_fallback  # noqa: E402
import pricing_model  # noqa: E402
from daiso.collect_gosi_alt import notice_value, clean_maker  # noqa: E402

STRATEGY = pricing_model.load_commerce_strategy()
CATEGORIES = [
    # (태그, 다이소 카테고리명, 다이소 카테고리 번호, Shopify productType)
    (c["tag"], c["daiso_name"], c["daiso_category_no"], c["product_type"]) for c in STRATEGY["categories"]
]

BRAND_EN = {
    "도브": "Dove",
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
# 새 상품 이미지(Gemini 생성)가 준비됐는지. API 무료 키로는 이미지 생성 쿼터가 0 이라 기본은 False.
GENERATED_IMAGES_READY = os.environ.get("GENERATED_IMAGES_READY", "0").strip().lower() in {"1", "true", "yes"}
ALLOW_ORIGINAL_IMAGES = os.environ.get("ALLOW_ORIGINAL_IMAGES", "0").strip().lower() in {"1", "true", "yes"}
DRY_RUN = os.environ.get("DRY_RUN", "0").strip().lower() in {"1", "true", "yes"}
ONLY = {x.strip() for x in os.environ.get("ONLY_CATEGORIES", "").split(",") if x.strip()}
BACKFILL_BANNER = os.environ.get("BACKFILL_BANNER", "1").strip().lower() in {"1", "true", "yes"}
QUARANTINE_BLOCKED_PUBLIC = os.environ.get("QUARANTINE_BLOCKED_PUBLIC", "0").strip().lower() in {"1", "true", "yes"}


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

    def existing_products(self):
        """Read every page, including drafts; an incomplete catalogue must not authorize a create."""
        products, cursor = [], None
        while True:
            d = self.gql("""query($after:String){products(first:50,after:$after){
              nodes{id title descriptionHtml tags variants(first:10){nodes{sku} pageInfo{hasNextPage endCursor}}}
              pageInfo{hasNextPage endCursor}}}""", {"after": cursor})["products"]
            for n in d["nodes"]:
                variants = n["variants"]
                vcursor = None
                while variants["pageInfo"]["hasNextPage"]:
                    next_variant_cursor = variants["pageInfo"].get("endCursor")
                    if not next_variant_cursor or next_variant_cursor == vcursor:
                        raise RuntimeError("Shopify variant pagination incomplete")
                    vcursor = next_variant_cursor
                    more = self.gql("""query($id:ID!,$after:String){product(id:$id){
                      variants(first:100,after:$after){nodes{sku} pageInfo{hasNextPage endCursor}}}}""",
                      {"id": n["id"], "after": vcursor})["product"]
                    if not more:
                        raise RuntimeError("Shopify variant pagination product missing")
                    page = more["variants"]
                    n["variants"]["nodes"].extend(page["nodes"])
                    variants = page
            products.extend(d["nodes"])
            if not d["pageInfo"]["hasNextPage"]:
                return products
            next_cursor = d["pageInfo"]["endCursor"]
            if not next_cursor or next_cursor == cursor:
                raise RuntimeError("Shopify catalogue pagination incomplete")
            cursor = next_cursor

    def read_product(self, product_id, publication_id=None):
        return self.gql("""query($id:ID!,$pub:ID!){product(id:$id){
          id handle title tags descriptionHtml status publishedOnPublication(publicationId:$pub)
          variants(first:100){nodes{title price compareAtPrice sku} pageInfo{hasNextPage}}
          media(first:100){nodes{mediaContentType status}}}}""",
          {"id": product_id, "pub": publication_id or "gid://shopify/Publication/0"})["product"]

    def read_notice_product(self, product_id):
        """Exact draft content read, independent of any publication/channel ID."""
        return self.gql('''query($id:ID!){product(id:$id){
          id title tags status descriptionHtml}}''', {'id': product_id}).get('product')

    def read_gallery(self, product_id):
        """Fresh read-only inventory and actual image bytes, never URL/alt-derived hashes."""
        observed_at = datetime.now(timezone.utc).isoformat()
        product = self.gql("""query($id:ID!){product(id:$id){id status tags
          media(first:100){nodes{id mediaContentType status ... on MediaImage{image{url}}} pageInfo{hasNextPage}}}}""",
          {"id": product_id}).get("product")
        if not isinstance(product, dict):
            return {}
        tags = product.get("tags") or []
        ids = {t.removeprefix("daiso-pd-") for t in tags
               if isinstance(t, str) and re.fullmatch(r"daiso-pd-[0-9]+", t)}
        media = product.get("media") or {}
        nodes = media.get("nodes")
        if product.get("status") == "DRAFT" and len(ids) == 1 and isinstance(nodes, list):
            for node in nodes:
                if node.get("mediaContentType") == "IMAGE" and node.get("status") == "READY":
                    digest = gallery_media_hash((node.get("image") or {}).get("url"))
                    if digest is not None:
                        node["content_sha256"] = digest
        return {"id": product.get("id"), "status": product.get("status"),
                "pd_no": next(iter(ids)) if len(ids) == 1 else None,
                "observed_at": observed_at,
                "complete": (media.get("pageInfo") or {}).get("hasNextPage") is False,
                "media": media.get("nodes")}

    def update_description(self, product_id, description_html):
        d = self.gql("""mutation($p:ProductUpdateInput!){productUpdate(product:$p){
          product{id} userErrors{field message}}}""",
          {"p": {"id": product_id, "descriptionHtml": description_html}})["productUpdate"]
        if d["userErrors"] or not d.get("product") or d["product"]["id"] != product_id:
            raise RuntimeError(f"description update: {d.get('userErrors')}")

    def update_draft_content(self, product_id, description_html, title):
        d = self.gql('''mutation($p:ProductUpdateInput!){productUpdate(product:$p){
          product{id} userErrors{field message}}}''',
          {'p': {'id': product_id, 'descriptionHtml': description_html, 'title': title}})['productUpdate']
        if d['userErrors'] or not d.get('product') or d['product']['id'] != product_id:
            raise RuntimeError('draft_content_update_unverified')

    def set_status(self, product_id, status):
        d = self.gql("""mutation($p:ProductUpdateInput!){productUpdate(product:$p){
          product{id} userErrors{field message}}}""", {"p": {"id": product_id, "status": status}})["productUpdate"]
        if d["userErrors"]:
            raise RuntimeError(f"product status: {d['userErrors']}")

    def publish(self, product_id, publication_id):
        d = self.gql("""mutation($id:ID!,$input:[PublicationInput!]!){
          publishablePublish(id:$id,input:$input){userErrors{field message}}}""",
          {"id": product_id, "input": [{"publicationId": publication_id}]})["publishablePublish"]
        if d["userErrors"]:
            raise RuntimeError(f"publish: {d['userErrors']}")

    def other_publications(self, online_store_id):
        """Online Store 외 모든 판매 채널(Google & YouTube, Facebook & Instagram, Pinterest, Buy Button, POS 등)."""
        d = self.gql("{publications(first:30){nodes{id name}}}")
        return [(n["id"], n["name"]) for n in d["publications"]["nodes"] if n["id"] != online_store_id]

    def publish_channels(self, product_id, online_store_id):
        """공개된 상품을 나머지 판매 채널에도 게시한다(Shopify 카탈로그·광고 채널 노출용). 실패해도 상품 등록은 유지하고 결과만 돌려준다."""
        out = {}
        try:
            targets = self.other_publications(online_store_id)
        except Exception as exc:  # noqa: BLE001
            return {"_error": str(exc)[:200]}
        for pid, name in targets:
            try:
                d = self.gql("""mutation($id:ID!,$input:[PublicationInput!]!){
                  publishablePublish(id:$id,input:$input){userErrors{field message}}}""",
                  {"id": product_id, "input": [{"publicationId": pid}]})["publishablePublish"]
                out[name] = "ok" if not d["userErrors"] else "error:" + str(d["userErrors"])[:120]
            except Exception as exc:  # noqa: BLE001
                out[name] = "error:" + str(exc)[:120]
        return out

    def online_store_publication(self):
        d = self.gql("{publications(first:20){nodes{id name}}}")
        for n in d["publications"]["nodes"]:
            if n["name"].lower().startswith("online store") or "온라인" in n["name"]:
                return n["id"]
        return None

    def upload_jpeg(self, data, filename):
        return self.upload_product_image(data, filename, "image/jpeg")

    def upload_product_image(self, data, filename, mime_type):
        """Shopify staged upload (PRODUCT_IMAGE). 업로드 후 productCreate 의 originalSource 로 쓸 resourceUrl 을 돌려준다."""
        if mime_type not in {"image/jpeg", "image/png"}:
            raise ValueError("Unsupported reviewed product image type")
        d = self.gql(
            """
mutation($i:[StagedUploadInput!]!){
  stagedUploadsCreate(input:$i){stagedTargets{url resourceUrl parameters{name value}} userErrors{field message}}
}""",
            {"i": [{"resource": "PRODUCT_IMAGE", "filename": filename, "mimeType": mime_type, "httpMethod": "POST"}]},
        )["stagedUploadsCreate"]
        if d["userErrors"]:
            raise RuntimeError(f"staged upload: {d['userErrors']}")
        tgt = d["stagedTargets"][0]
        boundary = "----jarvis" + str(int(time.time() * 1000))
        parts = []
        for prm in tgt["parameters"]:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{prm["name"]}"\r\n\r\n{prm["value"]}\r\n'.encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n".encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        req = urllib.request.Request(
            tgt["url"],
            data=b"".join(parts),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                if r.status not in (200, 201, 204):
                    raise RuntimeError(f"staged upload HTTP {r.status}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"staged upload HTTP {e.code}: {e.read()[:200]}")
        return tgt["resourceUrl"]

    def create(self, item, on_created):
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
                    "category": item["category"],
                    "tags": item["tags"],
                    "status": "DRAFT",  # never expose a product before read-after-write verification
                    "productOptions": [{"name": "Pack", "values": [{"name": item["variants"][0]["name"]}]}],
                },
                "media": [
                    {"originalSource": u, "mediaContentType": "IMAGE",
                     "alt": ((item.get("image_alts") or [])[i:i + 1] or [item["title"]])[0] or item["title"]}
                    for i, u in enumerate(item["images"])
                ],
            },
        )["productCreate"]
        if d["userErrors"]:
            raise RuntimeError(f"productCreate: {d['userErrors']}")
        prod = d["product"]
        on_created(prod)  # persist a durable ID before any later mutation can fail
        vid = prod["variants"]["nodes"][0]["id"]
        v0 = item["variants"][0]
        u = self.gql(
            """
mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$pid,variants:$v){userErrors{field message}}
}""",
            {
                "pid": prod["id"],
                "v": [{"id": vid, "price": f"{v0['price']:.2f}", "inventoryItem": {"sku": v0["sku"], "tracked": False}}],
            },
        )["productVariantsBulkUpdate"]
        if u["userErrors"]:
            raise RuntimeError(f"variant price: {u['userErrors']}")
        for v in item["variants"][1:]:
            c = self.gql(
                """
mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkCreate(productId:$pid,variants:$v){userErrors{field message}}
}""",
                {
                    "pid": prod["id"],
                    "v": [
                        {
                            "optionValues": [{"optionName": "Pack", "name": v["name"]}],
                            "price": f"{v['price']:.2f}",
                            "compareAtPrice": f"{v['compare_at']:.2f}" if v.get("compare_at") else None,
                            "inventoryItem": {"sku": v["sku"], "tracked": False},
                        }
                    ],
                },
            )["productVariantsBulkCreate"]
            if c["userErrors"]:
                raise RuntimeError(f"variant create: {c['userErrors']}")
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
        f"<p>{escape(title)} from Daiso Korea's daily beauty picks.</p>"
        f"<p><strong>Category:</strong> {escape(cat[3])}</p>"
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
        "not in the facts. Never use words like treat, cure, repair, anti-aging, wrinkle, whitening, acne, FDA, clinical, dermatologist, safe. Return JSON: {\"title\":\"...\",\"description\":\"...\"}.\n"
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


# ---------------------------------------------------------------- JARVIS pricing (원가 + 배송 + 관세 + 수수료)

# 마진은 경고 기준일 뿐 등록 조건이 아니다 (2026-10-11 사용자 승인). 환경변수로 기준값만 바꿀 수 있다.
_ADVISORY = STRATEGY["price_policy"]["margin_advisory"]
TARGET_MARGIN = float(os.environ.get("TARGET_MARGIN", str(_ADVISORY["target_margin"])))
DUTY_MODE = os.environ.get("DUTY_MODE", "ddu")


def _evidence_dict(source, median, n, query, collected_at):
    return {"source": source, "median_usd": median, "sample_n": n, "query": query, "collected_at": collected_at}


def jarvis_price(pd_no, name, krw):
    """상품별 가격 근거(SerpApi 미국 실판매 중앙값)에서 판매가를 만든다. 마진으로 가격을 올리거나 막지 않는다.

    정책: config/daiso_commerce_strategy.json 의 evidence_based_price.
      - 근거가 있으면 중앙값 x price_factor(95%) 가 판매가다 (pricing_model.evidence_price, offer_for 와 같은 규칙).
      - 근거가 없거나 신선도·표본·용량 비교를 못 맞추면 price_usd=None 과 사유를 돌려준다. 가격을 지어내지 않는다.
      - 원가+배송+관세+목표마진으로 만든 가격은 가격 근거가 아니다(cost_plus_counts_as_evidence=false).
    근거의 신선도와 용량 일치는 실행 시각 기준으로 지금 다시 판정한다 (낡은 data/pricing_model.json 을 믿지 않는다).
    """
    import pricing_model as pm  # noqa: PLC0415

    evidence = pm.product_market_evidence(pd_no)
    verdict = pm.assess_price_evidence(evidence, [name], strategy=STRATEGY)
    base = {"price_usd": None, "evidence": evidence, "evidence_assessment": verdict,
            "price_claim": "reference_price_basis_only_not_market_minimum",
            "basis": "no product-level price evidence" if not evidence else "serpapi_google_shopping x price_factor"}
    if evidence and verdict["ok"]:
        base["price_usd"] = float(pm.evidence_price(evidence, 1, 0.0, STRATEGY))
        base["basis"] = ("data/serpapi_market.json 상품별 미국 실판매 중앙값 x "
                         f"{STRATEGY['price_policy']['price_evidence']['sources']['serpapi_google_shopping']['price_factor']}")
    return base


# ---------------------------------------------------------------- Gosi (상품정보제공고시) - 상세 이미지 판독

GOSI_BUDGET_SEC = float(os.environ.get("GOSI_BUDGET_SEC", "150"))
NEED = ("ingredients", "volume", "maker", "origin")
PLACEHOLDER = {"", "-", "상세페이지 참조", "상세 페이지 참조", "없음", "해당없음"}
FIELD = {"1": "volume", "5": "maker", "6": "origin", "7": "ingredients", "9": "warnings", "3": "expiry"}
VISION_PROMPT = """이 이미지는 한국 화장품의 '상품정보 제공고시' 표이거나 그 일부가 담긴 상세 이미지입니다.
표에 적힌 내용을 그대로 옮겨 JSON 으로만 답하세요.
{"volume":"내용물의 용량 또는 중량","ingredients":"화장품법에 따라 기재해야 하는 모든 성분 전체","maker":"화장품제조업자 및 책임판매업자","origin":"제조국","warnings":"사용할 때의 주의사항","expiry":"사용기한 또는 개봉 후 사용기간"}
규칙: 없거나 읽을 수 없으면 "" . 요약 금지, 전성분은 쉼표까지 원문 그대로. 추측 금지, 보이는 글자만.
- 이 이미지에 다른 품번의 표가 있을 수 있습니다. 반드시 품번이 __PD__ 인 표만 옮기고, 없으면 모든 값을 "" 로 두세요.
JSON 외에 다른 말을 붙이지 마세요."""


def daiso_post(path, pd_no):
    status, body = http_json(
        "https://fapi.daisomall.co.kr" + path,
        {"pdNo": str(pd_no)},
        headers={"Origin": "https://www.daisomall.co.kr", "Referer": DAISO_ITEM + str(pd_no)},
    )
    return body if status == 200 else {}


def _clean(v):
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return "" if v in PLACEHOLDER else v


def gosi_from_api(pd_no):
    out = {}
    body = daiso_post("/pd/pdr/pdDtl/selPdDtlNtfc", pd_no)
    rows = body.get("data") if isinstance(body, dict) else []
    for r in rows if isinstance(rows, list) else []:
        key = FIELD.get(str(r.get("ntfcIemCd") or ""))
        val = _clean(r.get("ntfcIemCn"))
        if key and val:
            out[key] = val
    return out


def detail_image_urls(pd_no):
    import html as H  # noqa: PLC0415

    body = daiso_post("/pd/pdr/pdDtl/selPdDtlDesc", pd_no)
    data = body.get("data") if isinstance(body, dict) else None
    raw = ""
    if isinstance(data, dict):
        desc = data.get("pdDtlDesc") if isinstance(data.get("pdDtlDesc"), dict) else data
        raw = H.unescape(H.unescape(desc.get("pdDtlDc") or ""))
    urls = re.findall(r'src="([^"]+)"', raw)
    return [u if u.startswith("http") else DAISO_CDN + u for u in urls]


def vision_read(img_url, pd_no, key, model):
    req = urllib.request.Request(img_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        mime = r.headers.get_content_type() or "image/jpeg"
    status, body = http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        {
            "contents": [{"parts": [
                {"text": VISION_PROMPT.replace("__PD__", str(pd_no))},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        },
        timeout=60,
    )
    if status != 200:
        raise RuntimeError(f"vision HTTP {status}")
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    j = json.loads(text)
    return {k: _clean(j.get(k)) for k in ("volume", "ingredients", "maker", "origin", "warnings", "expiry")}


GOSI_RENDERED_ALT = os.environ.get("GOSI_RENDERED_ALT", "0").strip().lower() in {"1", "true", "yes"}


def gosi_from_rendered_alt(pd_no):
    """상품 페이지를 그려 '상품설명 더보기' 아래 상세 이미지 alt 에서 고시 항목을 읽는다.

    파싱 규칙은 scripts/daiso/collect_gosi_alt.py 의 parse_alt 를 그대로 쓴다 (한 곳에서만 고친다).
    값은 alt 원문 그대로다. 읽지 못한 칸은 비워 둔다.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "daiso"))
    import collect_gosi_alt as cga  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(locale="ko-KR", user_agent=cga.UA)
            page.goto(cga.PAGE.format(pd_no), timeout=60000, wait_until="domcontentloaded")
            btn = page.locator('button:has-text("상품설명 더보기")')
            try:
                btn.first.wait_for(state="visible", timeout=15000)
            except Exception:  # noqa: BLE001  버튼이 없는 상품도 있다
                pass
            if btn.count():
                btn.first.click(timeout=8000)
            alt, last, stable = "", -1, 0
            for _ in range(cga.MAX_SCROLL):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(1100)
                found = page.evaluate(cga.ALT_JS) or ""
                if len(found) > len(alt):
                    alt = found
                height, bottom = page.evaluate(
                    "() => {const e=document.scrollingElement;return [e.scrollHeight,e.scrollTop+e.clientHeight];}")
                stable = stable + 1 if height == last else 0
                last = height
                if bottom >= height - 80 and stable >= 2:
                    break
        finally:
            browser.close()
    parsed = cga.parse_alt(alt)
    log(f"  gosi rendered alt: {len(alt)} chars, fields {sorted(parsed)}")
    return {k: _clean(v) for k, v in parsed.items() if k in FIELD.values() and _clean(v)}


def collect_gosi(pd_no, allow_ai=True):
    try:
        return _collect_gosi(pd_no, allow_ai=allow_ai)
    except Exception as exc:  # noqa: BLE001  고시 수집이 어떻게 실패해도 작업은 계속한다 (초안으로 남는다)
        log(f"  gosi failed, continuing as draft: {exc}")
        return {"gosi_ok": False, "missing": list(NEED), "_source": "error"}


def _collect_gosi(pd_no, allow_ai=True):
    """고시 4항목(성분·용량·제조사·제조국)을 모은다. 못 채우면 빈 값으로 둔다. 지어내지 않는다."""
    g = {}
    # 0) 이미 수집된 JARVIS 정본 (data/gosi.json)
    try:
        items = json.loads((ROOT / "data/gosi.json").read_text(encoding="utf-8-sig")).get("items") or {}
        if isinstance(items, dict) and isinstance(items.get(str(pd_no)), dict):
            g.update({k: notice_value(k, _clean(v)) for k, v in items[str(pd_no)].items()
                      if k in {'ingredients', 'volume', 'maker', 'origin', 'functional', 'expiry', 'usage', 'warnings'}
                      and notice_value(k, _clean(v))})
            g["_source"] = "jarvis data/gosi.json"
    except (OSError, json.JSONDecodeError):
        pass
    # A transient source outage must not discard complete retained disclosure facts.
    # This is collection completeness only, never label/safety/publication clearance.
    if all(g.get(k) for k in NEED):
        g['gosi_ok'] = True
        g['missing'] = []
        return g
    # 1) 다이소 API 텍스트
    for k, v in gosi_from_api(pd_no).items():
        v = notice_value(k, v)
        if v:
            g.setdefault(k, v)
    # 1.5) 렌더링된 상세 이미지 alt 원문 (AI 없음, 무료). CLAUDE.md 2026-09-13: 고시 전문은
    # editor-content img 의 alt 에 글자로 있다. 그런데 이 단계가 없어서 data/gosi.json 에 없는
    # 상품(S등급이 아닌 바디 대체·메이크업 랭킹 후보)은 고시가 늘 비었다.
    # 2026-10-17 1042249 플루365 바디 스크럽: gosi_missing:ingredients,volume,maker 로 초안 등록.
    if GOSI_RENDERED_ALT and any(not g.get(k) for k in NEED):
        try:
            got = gosi_from_rendered_alt(pd_no)
        except Exception as exc:  # noqa: BLE001  브라우저 실패는 비어 있는 값으로 남긴다
            log(f"  gosi rendered alt failed: {type(exc).__name__}: {exc}")
            got = {}
        for k, v in got.items():
            v = notice_value(k, v)
            if v and not g.get(k):
                g[k] = v
                g["_source"] = "rendered alt (다이소 상세 이미지 alt 원문)"
    # Image-only notices below the expanded detail must not depend on a metered model.
    if GOSI_RENDERED_ALT and any(not g.get(k) for k in NEED):
        try:
            from daiso_notice_recovery import rendered_notice, ocr_notice
            evidence = rendered_notice(pd_no)
            for k, v in evidence['fields'].items():
                v = notice_value(k, _clean(v))
                if k in FIELD.values() and v and not g.get(k):
                    g[k] = v
            if any(not g.get(k) for k in NEED):
                evidence['ocr'] = ocr_notice(evidence['images'])
            g['_notice_evidence'] = evidence
        except Exception as exc:
            g['_notice_evidence'] = {'error': type(exc).__name__, 'review_required': True}
    # 2) 상세 이미지 판독 (표는 상세 이미지 아래쪽에 있다)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if allow_ai and key and any(not g.get(k) for k in NEED):
        model = os.environ.get("GEMINI_VISION_MODEL", "gemini-flash-latest")
        imgs = detail_image_urls(pd_no)
        log(f"  gosi: detail images {len(imgs)}")
        started = time.monotonic()
        for u in reversed(imgs[-6:]):
            if time.monotonic() - started > GOSI_BUDGET_SEC:
                log("  gosi: 시간 예산 초과, 현재까지 읽은 값으로 계속 진행")
                break
            got = None
            for attempt in (1, 2):  # 시간초과·일시 오류는 1번 더 시도하고, 그래도 안 되면 건너뛴다
                try:
                    got = vision_read(u, pd_no, key, model)
                    break
                except Exception as exc:  # noqa: BLE001
                    log(f"  gosi vision attempt {attempt} failed: {exc}")
                    time.sleep(5)
            if got is None:
                continue
            for k, v in got.items():
                v = notice_value(k, v)
                if v and not g.get(k):
                    g[k] = v
                    g["_source"] = "gemini vision (상세 이미지 판독, 사람 확인 전)"
            if all(g.get(k) for k in NEED):
                break
            time.sleep(3)
    g["gosi_ok"] = all(g.get(k) for k in NEED)
    g["missing"] = [k for k in NEED if not g.get(k)]
    return g


ORIGIN_EN = {"한국": "Korea", "대한민국": "Korea", "korea": "Korea", "republic of korea": "Korea",
             "중국": "China", "일본": "Japan"}
ROLE_EN = (("화장품제조업자", "Manufacturer"), ("화장품책임판매업자", "Distributor (responsible seller, Korea)"),
           ("제조업자", "Manufacturer"), ("책임판매업자", "Distributor (responsible seller, Korea)"))
# 미국에서 의약외품/OTC 로 볼 수 있는 제품군. 자동 공개하지 않고 사람이 검토한다.
REGULATED_RE = re.compile(r"자외선|선크림|선스틱|선케어|선쿠션|SPF|미백|주름개선|여드름|탈모|염모|염색|치약|살균|항균|구강", re.I)
# 영문 카피에 들어가면 안 되는 효능·의료·인증 표현 (미국에서 의약품 표방/허위광고가 될 수 있다)
CLAIM_RE = re.compile(r"\b(cure[sd]?|treat(?:s|ed|ment)?|heal(?:s|ing)?|anti-?aging|anti-?wrinkle|wrinkles?|whiten(?:ing|s)?|"
                      r"acne|eczema|dermatitis|FDA|clinical(?:ly)?|dermatolog\w*|medical|therapeutic|prevent\w*|"
                      r"repair\w*|regenerat\w*|collagen (?:production|boost)|hypoallergenic|non-?toxic|safe)\b", re.I)


def has_claims(*texts):
    return bool(CLAIM_RE.search(" ".join(texts)))


def _inci_resolver():
    import sync_gosi_to_us_labels as sg  # noqa: PLC0415
    from inci_resolver import InciResolver, load_manual_overrides  # noqa: PLC0415

    doc = json.loads((ROOT / "data/inci_dictionary.json").read_text(encoding="utf-8-sig"))
    return sg, InciResolver(doc.get("kr_to_inci") or {}, load_manual_overrides(ROOT))


def _net_contents(raw, name_kr=""):
    raw = _clean(raw)
    # "2ml*6개입" 같은 세트는 개당 용량 x 개수로 쓰고 단위 환산은 하지 않는다 (총량으로 오해될 수 있다)
    sm = re.search(r"[*xX×]\s*(\d+)\s*(?:개입|개|ea|매|입)", name_kr or "")
    if sm and re.fullmatch(r"\d+(?:\.\d+)?\s*(?:ml|mL|ML|g|G)", raw):
        base = re.sub(r"\s+", " ", raw)
        return f"{base} x {sm.group(1)} ea"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G)", raw)
    if not m:
        return raw  # 세트·복합 표기는 변환하지 않고 원문 그대로 둔다
    v, unit = float(m.group(1)), m.group(2).lower()
    conv = f"{v / 29.5735:.2f} fl oz" if unit == "ml" else f"{v / 28.3495:.2f} oz"
    return f"{raw} ({conv})"


def build_us_label(pd_no, name_kr, g):
    """고시(한국어)를 미국 상품 페이지용 영문 블록으로 만든다. 법률상 위험한 부분은 기계 번역하지 않는다.

    - 성분: 대한화장품협회 표준화명칭목록(data/inci_dictionary.json)으로만 INCI 변환. 하나라도 못 이으면 성분표를 쓰지 않고 초안.
    - 사용상 주의·사용법: 기계 번역 금지(사람이 확인한 warnings_en 만 사용). 없으면 '포장 참조' 문구만.
    - 기능성/의약외품 성격(자외선차단·미백·주름개선 등): 자동 공개하지 않고 초안.
    - 제조국: 고정 매핑표만 사용. 매핑에 없으면 초안.
    """
    reasons, label = [], {}
    try:
        sg, resolver = _inci_resolver()
        source_ingredients = g.get('ingredients', '')
        lookup_ingredients = source_ingredients
        # Exact inspected body artwork uses trailing * for its ingredient footnote.
        # Preserve raw source; remove only suffix punctuation for dictionary lookup.
        if str(pd_no) in {'1069429', '1069430'}:
            lookup_ingredients = re.sub(r'\*(?=\s*(?:,|$))', '', source_ingredients)
        inci, missing, fixed, review = sg.to_inci(lookup_ingredients, resolver)
        if inci and str(pd_no) in {'1069429', '1069430'} and re.search(r'향료\([^)]*1\.21%\)', source_ingredients):
            inci = re.sub(r'\bFragrance\b(?!\s*\()', 'Fragrance (1.21%)', inci, flags=re.I)
        if inci and str(pd_no) == '1060646' and '하이드롤라이즈드소듐하이알루로네이트(100 ppm)' in source_ingredients:
            inci = re.sub(r'\bHydrolyzed Sodium Hyaluronate\b(?!\s*\()',
                          'Hydrolyzed Sodium Hyaluronate (100 ppm)', inci, flags=re.I)
        if inci:
            label["ingredients_inci"] = inci
            label["inci_fixed"] = len(fixed)
        else:
            reasons.append(f"inci_unresolved:{len(missing)}" if g.get("ingredients") else "ingredients_missing")
    except Exception as exc:  # noqa: BLE001
        log(f"  inci failed: {exc}")
        reasons.append("inci_error")

    if g.get("volume"):
        label["net_contents"] = _net_contents(g["volume"], name_kr)
    origin = ORIGIN_EN.get(_clean(g.get("origin")).lower().replace(" ", "")) or ORIGIN_EN.get(_clean(g.get("origin")).lower())
    if origin:
        label["origin"] = origin
    else:
        reasons.append("origin_unmapped")
    mk = clean_maker(_clean(g.get("maker")))
    for ko, en in ROLE_EN:
        mk = mk.replace(ko, en)
    if re.search(r"[가-힣]{2,}", re.sub(r"\([^)]*\)|주식회사|\(주\)|㈜", "", mk)) or mk:
        label["maker"] = mk  # 회사명은 고유명사라 번역하지 않고 원문 그대로 둔다
    if not mk:
        reasons.append("maker_missing")

    # 사람이 확인한 영문 주의사항이 있을 때만 쓴다
    try:
        labels = json.loads((ROOT / "data/daiso_real/daiso_us_labels.json").read_text(encoding="utf-8-sig"))
        w = _clean((labels.get(str(pd_no)) or {}).get("warnings_en"))
        if w and not re.search(r"실제|확인|TODO|TBD|placeholder|pending", w, re.I):
            label["warnings_en"] = w
    except (OSError, json.JSONDecodeError):
        pass

    if REGULATED_RE.search(name_kr) or REGULATED_RE.search(g.get("functional", "") or ""):
        reasons.append("us_regulatory_review_functional_or_drug_like")

    li = []
    if label.get("net_contents"):
        li.append(("Net contents", label["net_contents"]))
    if label.get("ingredients_inci"):
        li.append(("Ingredients (INCI)", label["ingredients_inci"]))
    if label.get("maker"):
        li.append(("Manufacturer / Distributor (Korea)", label["maker"]))
    if label.get("origin"):
        li.append(("Country of origin", label["origin"]))
    li.append(("Cautions and directions", label.get("warnings_en") or "Please refer to the product packaging."))
    html = "<h4>Product information</h4><ul>" + "".join(f"<li><strong>{escape(k)}:</strong> {escape(str(v))}</li>" for k, v in li) + "</ul>"
    return {"html": html, "reasons": reasons, "label": {k: v for k, v in label.items() if k != "ingredients_inci"}}



# ---------------------------------------------------------------- Shopify 표준 카테고리 (택소노미)

# skincare hb-3-2-9 (Health & Beauty > Personal Care > Cosmetics > Skin Care), makeup hb-3-2-6, body hb-3-2-1 (Bath & Body)
TAXONOMY = {c["tag"]: c["shopify_taxonomy"] for c in STRATEGY["categories"]}

# ---------------------------------------------------------------- 1개 / 1+1(2개 세트) - JARVIS 판매 구성 (pricing_model.py)

BUNDLE_QTY = 2
BUNDLE_DISCOUNT = 0.15  # pricing_model.BUNDLE_DISCOUNT 와 같은 값. 무료배송은 스토어 배송 설정에서 따로 건다.


# ---------------------------------------------------------------- 이미지: 제품 전용 검수 허용 목록 + 얼굴 검증 + 정사각 2048

IMAGE_POLICY = STRATEGY["image_policy"]


def reviewed_image_entries(pd_no, policy=None):
    """'제품만 나오는 사진' 으로 검수해 허용 목록에 올린 이미지 (다이소 이미지 경로 -> 항목).
    검수 주체는 항목의 reviewed_by 에 사실대로 적는다. 자동 시각 검사는 그렇게 밝히며 사람의 승인이 아니다."""
    allow = (policy or IMAGE_POLICY)["reviewed_product_only_allowlist"]
    return {e["path"]: e for e in (allow.get(str(pd_no)) or [])}


def image_path(url):
    return url[len(DAISO_CDN):] if url.startswith(DAISO_CDN) else url


LOCALIZE_POLICY = IMAGE_POLICY.get("detail_localization") or {}
LOCALIZE_DETAIL_IMAGES = (os.environ.get("LOCALIZE_DETAIL_IMAGES", "0").strip().lower() in {"1", "true", "yes"}
                          and LOCALIZE_POLICY.get("enabled") is True)


def localized_images(p, shop, title):
    """상세 이미지 영문 변환은 검토용 준비만 한다. Shopify 업로드는 하지 않는다.

    변환 성공과 갤러리 검토를 분리한다. 실제 검토 자산 추가는 gallery_review의
    현재 SKU·원본/출력 바이트·역할·QA·권리·실물 라벨 근거 경로가 담당한다.
    이 함수의 status=ok나 임의의 준비/완료 플래그는 그 경로의 승인이 아니다.
    """
    if not LOCALIZE_DETAIL_IMAGES:
        return None
    sys.path.insert(0, str(ROOT / "scripts" / "daiso"))
    import localize_detail_images as ldi  # noqa: PLC0415

    out_dir = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "localized" / str(p["pdNo"])
    try:
        man = ldi.localize_product(str(p["pdNo"]), title, out_dir, ldi.translator_from_env())
    except Exception as exc:  # noqa: BLE001  영문화가 어떻게 실패해도 등록 흐름은 계속한다 (초안으로 남는다)
        log(f"  localize failed: {type(exc).__name__}: {exc}")
        return {"status": "failed", "reasons": [f"localize_exception:{type(exc).__name__}"], "outputs": []}
    # Conversion success is not a reviewed gallery or permission to upload.
    # Reviewed additions have a separate exact-byte path through gallery_review
    # and backfill_draft_images; never promote converter flags into that path.
    man = copy.deepcopy(man)
    for key in ("_files", "_alts", "_resource_urls", "_output_sha256s"):
        man.pop(key, None)
    man.update(gallery_status="review_required", gallery_complete=False,
               upload_allowed=False,
               gallery_review_reasons=["localized_conversion_not_upload_authorization"])
    if not DRY_RUN:
        ldi.write_manifest(man)
    log(f"  localize: {man['status']} {man.get('summary')} {man.get('reasons')}; upload held for gallery review")
    return man


def prepare_images(p, shop, title=None):
    """검수 허용 목록 이미지만 등록 후보로 쓰고, 영문화는 별도 검토용으로 준비한다.

    변환 status=ok는 업로드/대표 배치 권한이 아니다. 검토된 갤러리 추가는
    gallery_review의 바이트·SKU·권리·라벨·QA 결합 경로에서 별도로 처리한다.

    다이소 상품 이미지 중 제품 전용으로 검수 기록이 있는 허용 목록(config/daiso_commerce_strategy.json) 항목만 쓴다.
    검수 주체(사람/자동 시각 검사)는 reviewed_by 에 그대로 남는다. 여기서 사람의 승인을 주장하지 않는다.

    사람 얼굴 사진은 금지다. 얼굴 검출기(OpenCV YuNet)는 휴리스틱이라 '얼굴이 없다' 를 보장하지 못한다.
    그래서 결정적 기준은 허용 목록이다: 경로가 목록에 있고, 내려받은 파일의 sha256 이 검수한 값과 같아야 한다.
    받을 후보 = 상품이 광고한 경로(pdImgUrlList) ∪ 허용 목록 경로. 허용 목록 경로는 광고 목록에 없어도(예: 크기가 다른 원본만
    광고하는 경우) 정규 다이소 CDN 아래에서 직접 받는다. 허용 목록 밖의 이미지는 내려받지도 올리지도 않는다.
    허용된 이미지에도 해시 일치와 얼굴 검증(select_images)은 그대로 거친다.
    사용할 이미지가 하나도 없으면 호출한 쪽이 no_usable_product_images 로 초안에 남긴다.
    모두 2048x2048 정사각 JPEG 로 바꿔 Shopify 에 올린다. 판독 도구가 실패한 이미지는 쓰지 않는다."""
    import daiso_images as di  # noqa: PLC0415

    allowed = reviewed_image_entries(p["pdNo"])
    advertised = [DAISO_CDN + u for u in (p.get("pdImgUrlList") or [p["pdImgUrl"]])]
    # 광고 경로 + 허용 목록 경로의 합집합 (순서: 광고 순서, 그다음 허용 목록 순서; 중복 제거). 허용 경로는 CDN 고정이다.
    urls = list(dict.fromkeys(advertised + [DAISO_CDN + path for path in allowed]))
    dropped, blobs = [], []
    for u in urls:
        entry = allowed.get(image_path(u))
        if entry is None:
            dropped.append({"url": u, "reason": "not_in_reviewed_product_only_allowlist"})
            continue
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
        except Exception as exc:  # noqa: BLE001
            log(f"  image download failed: {exc}")
            dropped.append({"url": u, "reason": f"download_failed:{type(exc).__name__}"})
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            dropped.append({"url": u, "reason": "reviewed_image_hash_mismatch"})
            continue
        blobs.append((u, data))
    kept, face_dropped = di.select_images(blobs)
    dropped.extend(face_dropped)
    resource_urls, output_hashes = [], []
    if shop is not None and not DRY_RUN:
        for n, (u, data) in enumerate(kept, 1):
            output = di.to_square_jpeg(data)
            output_hashes.append(hashlib.sha256(output).hexdigest())
            resource_urls.append(shop.upload_jpeg(output, f"daiso-{p['pdNo']}-{n}.jpg"))
    log(f"  images: total {len(urls)}, reviewed {len(blobs)}, kept {len(kept)}, dropped {len(dropped)} {[d['reason'] for d in dropped]}")
    source_urls = [u for u, _ in kept]
    alts = [title or ""] * len(source_urls)
    localization = None
    loc = localized_images(p, shop, title or "") if title is not None else None
    if loc is not None:
        localization = {"status": loc.get("status"), "summary": loc.get("summary"), "reasons": loc.get("reasons"),
                        "translator": loc.get("translator"),
                        "gallery_complete": False, "gallery_status": "review_required",
                        "manifest": f"data/image_localization/{p['pdNo']}.json"}
        localization["upload_allowed"] = False
        localization["gallery_review_reasons"] = ["localized_conversion_not_upload_authorization"]
        if loc.get("status") == "ok":
            # Do not merge even if an untrusted converter returns forged internal
            # URLs, prepared/gallery_complete flags, or prior upload identifiers.
            dropped.append({"url": DAISO_ITEM + str(p["pdNo"]),
                            "reason": "detail_localization_requires_gallery_review"})
        else:
            dropped.append({"url": DAISO_ITEM + str(p["pdNo"]), "reason": "detail_localization_failed:" +
                            ",".join(loc.get("reasons") or [])})
    return {"source_urls": source_urls, "resource_urls": resource_urls, "skipped": dropped, "alts": alts,
            "localization": localization, "total": len(urls), "reviewed_allowlist_entries": len(allowed),
            "gallery_complete": False, "gallery_status": "review_required", "output_sha256s": output_hashes}



# ---------------------------------------------------------------- 용량 파싱·비교 (총량 기준)

def parse_size(s):
    """'2ml*6개입', '2 ml x 6 ea', '90g', '1.69 fl oz' -> {'unit': 개당 용량, 'base': 'ml'|'g', 'count': 입수, 'total': 총량}. 없으면 None."""
    s = (s or "").lower().replace("fl. oz", "fl oz")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|ml|fl oz|oz|g|l)\b", s)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2)
    base, mult = {"ml": ("ml", 1), "l": ("ml", 1000), "fl oz": ("ml", 29.5735), "g": ("g", 1), "kg": ("g", 1000), "oz": ("g", 28.3495)}[u]
    unit = v * mult
    c = re.search(r"[x*×]\s*(\d+)\b", s[m.end():]) or re.search(r"(\d+)\s*(?:ea|pcs|pc|개입|매입|입|ct|pack)\b", s[m.end():])
    pre = re.search(r"(\d+)\s*[x*×]\s*$", s[: m.start()])  # "3 x 90g" 처럼 앞에 입수가 오는 표기
    count = int(c.group(1)) if c else (int(pre.group(1)) if pre else 1)
    return {"unit": round(unit, 2), "base": base, "count": count, "total": round(unit * count, 2)}


def same_total(a, b, tol=0.05):
    return bool(a and b and a["base"] == b["base"] and abs(a["total"] - b["total"]) <= tol * max(a["total"], b["total"]))


# ---------------------------------------------------------------- 가격: 원가+배송+관세+수수료 바닥 + shop.com 최저가 비교

# 최소 마진은 경고 기준이다. 2026-10-11 사용자 승인으로 더 이상 판매가 바닥이나 등록 차단 조건이 아니다.
MIN_MARGIN = float(os.environ.get("MIN_MARGIN", str(STRATEGY["price_policy"]["margin_advisory"]["minimum_margin"])))
_STOP = {"the", "and", "for", "with", "korean", "korea", "new", "set", "of", "by", "ml", "g", "ea", "pcs", "oz", "x"}


def _tokens(s):
    s = re.sub(r"[\[\]()]", " ", (s or "").lower())
    s = re.sub(r"(\d)\s*(ml|g|ea|pcs|oz)\b", r"\1 \2", s)
    return re.findall(r"[a-z0-9]+", s)


def _sizes(s):
    return {(m.group(1), m.group(2)) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(ml|g|ea|pcs|oz)\b", (s or "").lower())} | {
        (m.group(1), "ea") for m in re.finditer(r"x\s*(\d+)\b", (s or "").lower())}


def comparable(ours, cand):
    """같은 상품으로 볼 수 있는 검색 결과만 남긴다: 브랜드 일치, 모델 숫자 일치, 핵심 단어 60% 이상, 용량·입수 충돌 없음."""
    ot, ct = _tokens(ours), set(_tokens(cand))
    if not ot or not ct:
        return False
    brand = ot[0]
    if brand not in ct:
        return False
    size_nums = {n for n, _ in _sizes(ours)}
    model_nums = [x for x in ot if x.isdigit() and x not in size_nums]
    if any(n not in ct for n in model_nums):
        return False
    words = [x for x in ot if not x.isdigit() and x not in _STOP and len(x) > 2]
    if words and sum(1 for w in words if w in ct) / len(words) < 0.6:
        return False
    so, sc = parse_size(ours), parse_size(cand)
    if so:  # 우리 상품에 용량이 있으면 후보도 총량이 같아야 한다 (용량 표기가 없는 후보는 비교하지 않는다)
        if not same_total(so, sc):
            return False
    # 우리 쪽에 없는 구분어(헤어/세트 등)가 후보에 있으면 다른 상품이다
    for bad in ("hair", "set", "kit", "refill", "sample", "bundle", "duo", "trio"):
        if bad in ct and bad not in set(ot):
            return False
    return True


def shop_compare(title):
    """shop.com 검색 결과에서 같은 상품의 최저 판매가(USD). 실패하면 None."""
    import subprocess  # noqa: PLC0415

    words = [w for w in re.sub(r"[\[\]()]", " ", title).split() if w.lower() not in _STOP and not re.fullmatch(r"\d+(ml|g|ea)?", w.lower()) or w.isdigit()]
    query = " ".join(words[:6])
    try:
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "shop_price_compare.py"), query],
                             capture_output=True, text=True, timeout=150, check=False).stdout.strip().splitlines()
        data = json.loads(out[-1]) if out else {"results": [], "error": "no output"}
    except Exception as exc:  # noqa: BLE001
        return {"query": query, "error": f"{type(exc).__name__}: {exc}", "matches": [], "lowest_usd": None}
    matches = [r for r in data.get("results", []) if r.get("usd") and comparable(title, r["title"])]
    prices = sorted(r["usd"] for r in matches)
    if len(prices) >= 3:  # 오등록(1달러 등) 같은 이상치는 중앙값의 40% 미만이면 버린다
        med = prices[len(prices) // 2]
        matches = [r for r in matches if r["usd"] >= med * 0.4]
        prices = sorted(r["usd"] for r in matches)
    lowest = prices[0] if prices else None
    return {"query": query, "error": data.get("error"), "found": len(data.get("results", [])),
            "match_count": len(matches),
            "matches": sorted(matches, key=lambda r: r["usd"])[:5], "lowest_usd": lowest}


_FX = {}


def fx_rate():
    """원/달러. 공개 환율 API(실시간)를 우선 쓰고, 없으면 JARVIS 수집값(collection_status.json). 둘 다 없으면 중단한다(임의 환율 금지)."""
    if "v" in _FX:
        return _FX["v"]
    st = json.loads((ROOT / "data/daiso_real/collection_status.json").read_text(encoding="utf-8"))
    saved = float((st.get("fx") or {}).get("usd_to_krw") or 0)
    live = 0.0
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=20) as r:
            live = float((json.loads(r.read().decode()).get("rates") or {}).get("KRW") or 0)
    except Exception:  # noqa: BLE001
        pass
    rate = live or saved
    if not rate:
        raise RuntimeError("환율이 없어 가격을 계산할 수 없다 (임의 환율 사용 금지)")
    log(f"  fx: live={live or None} saved={saved or None} -> use {rate}")
    _FX["v"] = {"rate": rate, "live": live or None, "saved": saved or None}
    return _FX["v"]


def _landed(pd_no, name, krw, qty):
    import pricing_model as pm  # noqa: PLC0415

    rate = fx_rate()["rate"]
    market = pm.market_benchmark() or {"p25": 0, "median": 0}
    row = pm.analyze({"pd_no": pd_no, "name": name, "price_krw": krw}, rate, qty, market, DUTY_MODE)
    return row["landed_cost_usd"] * qty, pm, row


def final_prices(pd_no, name_kr, krw, title_en, base_price, base_evidence=None):
    """판매가 결정 (정책: evidence_based_price, config/daiso_commerce_strategy.json).

    시장 근거가 있으면 근거 가격을 쓴다. 마진 미달로 가격을 올리거나 등록을 막지 않는다 (2026-10-11 사용자 승인).
      1순위 shop.com 에서 지금 읽은 같은 상품(총량 일치)의 최저가보다 약간 낮게.
      2순위 jarvis_price() 가 돌려준 상품별 SerpApi 중앙값 가격 (base_price + base_evidence).
    두 시장 근거 모두 사용할 수 없으면 비용 기반 임시 USD 가격으로 DRAFT만 허용한다
    (2026-10-18 사업주 승인). 시장 근거의 ok는 계속 False로 남기며 공개하지 않는다.
    착지원가 대비 마진은 profit_warnings 로 공개만 한다 (손익분기 이하여도 등록은 막지 않는다).
    """
    import math  # noqa: PLC0415

    landed1, pm, row1 = _landed(pd_no, name_kr, krw, 1)
    landed2, _, _row2 = _landed(pd_no, name_kr, krw, BUNDLE_QTY)
    estimated = row1.get("weight_source") == "estimated"
    now = datetime.now(timezone.utc)

    def down(v):  # 값보다 낮은 .99
        return math.floor(v - 0.01) - 0.01 if v >= 2 else v

    cmp_ = shop_compare(title_en)
    texts = [name_kr, title_en]
    price_rules = STRATEGY["price_policy"]["price_evidence"]
    chosen, single, basis, rejected = None, None, None, []
    for source in price_rules["source_priority"]:
        if source == "shop_com_live_comparable":
            low = cmp_.get("lowest_usd")
            if not low:
                continue
            best = (cmp_.get("matches") or [{}])[0]
            ev = _evidence_dict(source, low, cmp_.get("match_count") or len(cmp_.get("matches") or []),
                                best.get("title"), now.isoformat())
            verdict = pm.assess_price_evidence(ev, texts, now=now, strategy=STRATEGY)
            if not verdict["ok"]:
                rejected.append({"source": source, "reasons": verdict["reasons"]})
                continue
            target = max(down(low) if down(low) < low else low - 0.5, 0)
            single, chosen, basis = round(target, 2), {**ev, "assessment": verdict, "price_claim": "undercuts_lowest_verified_same_item_comparator"}, \
                "shop.com 동일 상품 최저가보다 낮게 (총량 일치 확인)"
        elif source == "serpapi_google_shopping":
            if not base_evidence or not base_price:
                continue
            verdict = pm.assess_price_evidence(base_evidence, texts, now=now, strategy=STRATEGY)
            if not verdict["ok"]:
                rejected.append({"source": source, "reasons": verdict["reasons"]})
                continue
            single, chosen, basis = round(float(base_price), 2), {**base_evidence, "assessment": verdict,
                                                                   "price_claim": "reference_price_basis_only_not_market_minimum"}, \
                "상품별 미국 실판매 중앙값 기준 참고 가격 (SerpApi, 시장 최저가 아님)"
        if single is not None:
            break

    evidence = ({"ok": True, "source": chosen["source"], "reasons": [], "detail": chosen, "rejected": rejected}
                if chosen else {"ok": False, "source": None, "rejected": rejected,
                                "reasons": ["price_evidence_missing"] + [r for x in rejected for r in x["reasons"]]})

    draft_only = single is None
    floor_applied = False
    if draft_only and krw and krw > 0:
        single = pm.cost_based_draft_price(round(landed1, 2), STRATEGY)
        basis = "원가·배송비·수수료·목표마진 기준 임시 USD 초안 가격 (시장가격 미확인)"
    elif single is not None:
        # 2026-10-18 사업주: 원가+배송+카드수수료 기준 최소 마진 30%(무게 추정 35%) 미만으로 팔지 않는다.
        single, floor_applied = pm.apply_margin_floor(single, landed1, estimated, STRATEGY)
        if floor_applied:
            basis = (basis or "") + " → 최소 마진 하한 적용 (원가·배송·카드수수료 기준)"
            if chosen:
                chosen["price_claim"] = "margin_floor_price_above_evidence"
    single_row = {"price_usd": single, "landed_cost_usd": round(landed1, 2), "margin_floor_applied": floor_applied}
    pack_row = {"price_usd": None, "compare_at_usd": None, "landed_cost_usd": round(landed2, 2), "ok": False}
    warnings = []
    if single is not None:
        pack = round(pm.psych_price(single * BUNDLE_QTY * (1 - BUNDLE_DISCOUNT)), 2)
        pack, _pack_floor = pm.apply_margin_floor(pack, landed2, estimated, STRATEGY)
        adv1 = pm.profitability_advisory(single, landed1, estimated, STRATEGY)
        adv2 = pm.profitability_advisory(pack, landed2, estimated, STRATEGY)
        single_row.update(net_profit_usd=adv1["net_profit_usd"], margin_pct=adv1["margin_pct"],
                          target_price_usd=adv1["target_price_usd"], profit_warnings=adv1["warnings"],
                          profitability_status=adv1["status"])
        pack_row.update(price_usd=pack, compare_at_usd=round(single * BUNDLE_QTY, 2), net_profit_usd=adv2["net_profit_usd"],
                        margin_pct=adv2["margin_pct"], target_price_usd=adv2["target_price_usd"],
                        profit_warnings=adv2["warnings"], profitability_status=adv2["status"],
                        ok=0 < pack < single * BUNDLE_QTY)
        warnings = [f"single:{w}" for w in adv1["warnings"]] + [f"pack:{w}" for w in adv2["warnings"]]
    return {
        "single": single_row, "pack": pack_row,
        "draft_only": draft_only,
        "basis": basis or "근거 없음", "shop_compare": cmp_, "evidence": evidence,
        "profit_warnings": warnings, "profitability_blocks_registration": False,
        "min_margin": MIN_MARGIN + (STRATEGY["price_policy"]["margin_advisory"]["estimated_weight_extra_margin"] if estimated else 0.0),
        "target_margin": TARGET_MARGIN,
        "weight_g": row1.get("weight_g_est"), "weight_source": row1.get("weight_source"), "shipping_usd": row1.get("shipping_unit_usd"),
        "tariff_usd": row1.get("tariff_usd"), "fx": fx_rate(),
    }


# ---------------------------------------------------------------- 중복 방지 레지스트리 (삭제한 상품이 다시 올라오지 않게)

REGISTRY = ROOT / "data" / "shopify_daily_registry.json"


def kst_today():
    from datetime import timedelta  # noqa: PLC0415

    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def family_key(name_kr):
    """같은 상품의 색상·호수·괄호 표기만 다른 변형을 한 묶음으로 본다: 대괄호/괄호 안 글자와 공백을 지운 이름."""
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", name_kr or "")
    return re.sub(r"[\s\-_/·.,]+", "", s).lower()


def load_registry():
    if not REGISTRY.exists():
        return {"items": []}
    d = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        raise ValueError("Invalid daily registry; refusing to create products")
    return d


def save_registry(d):
    """Atomic replace; a broken registry must stop creation, not silently reset history."""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=REGISTRY.parent,
                                         prefix=".shopify_daily_", delete=False) as f:
            name = f.name
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        # Windows can briefly deny replacement while another process holds the
        # destination without delete-sharing. Retry only the same fsynced atomic
        # rename, never truncate/unlink the registry or repeat a remote mutation.
        for attempt in range(5):
            try:
                os.replace(name, REGISTRY)
                break
            except PermissionError as exc:
                if (os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32, 33)
                        or attempt == 4):
                    raise
                time.sleep(0.02 * (2 ** attempt))
    finally:
        if name and os.path.exists(name):
            os.unlink(name)




def bundle_variant_name(single, pack):
    """Truthful 2-pack label: the saving shown is never more than the actual saving vs two singles."""
    import math  # noqa: PLC0415
    try:
        save = math.floor((1 - float(pack) / (2 * float(single))) * 100 + 1e-9)
    except (TypeError, ValueError, ZeroDivisionError):
        return "2-Pack"
    return f"2-Pack (Save {save}%)" if save >= 1 else "2-Pack"


def price_unfit_reason(krw, pr):
    """가격이 '실제로 쓸 수 없는' 상품이면 사유를 돌려준다(없으면 None). 이런 상품은 후보에서 제외한다.

    2026-10-11 사용자 승인: 마진·손익분기 미달은 더 이상 사유가 아니다(profit_warnings 로 공개만 한다).
    2026-10-18: 검증 가능한 비용 기반 임시 가격은 시장 근거 없이 DRAFT로 진행한다.
    원가 없음, 임시 가격 계산 불일치, 판매가·세트가 무효는 계속 차단한다.
    """
    if not krw or krw <= 0:
        return "no_cost_price"
    ev = pr.get("evidence")
    import pricing_model as pm
    single_row = pr.get("single") or {}
    cost_draft = pr.get("draft_only") is True and pm.is_cost_based_draft(single_row.get("price_usd"), single_row.get("landed_cost_usd"), STRATEGY)
    if (not isinstance(ev, dict) or ev.get("ok") is not True) and not cost_draft:
        reasons = ev.get("reasons") if isinstance(ev, dict) else None
        return "price_evidence_invalid:" + ",".join(str(r) for r in (reasons or ["price_evidence_missing"]))
    price = (pr.get("single") or {}).get("price_usd")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price != price or price <= 0:
        return "single_price_invalid"
    pack = pr.get("pack") or {}
    if pack and pack.get("ok") is False:
        return "bundle_price_invalid"
    return None


# ---------------------------------------------------------------- 가격 포지션 기록 (불리한 상품의 대체 전략 학습용)

STRATEGY_LOG = ROOT / "data" / "price_strategy_log.json"


def price_position(our_usd, lowest_usd, margin_pct):
    """우리 단품가 vs shop.com 최저가. 마진 우선이라 최저가를 못 이기는 상품은 가격 외 전략 후보를 함께 적는다.
    판매 데이터가 없는 동안에는 결과(효과)를 추정하지 않고 관측값만 쌓는다."""
    if not lowest_usd:
        return {"position": "no_comparison", "gap_pct": None, "hints": ["shop_com_match_missing: 검증된 동일 상품 비교 없음. 가격은 참고 가격 근거일 뿐 시장 최저가가 아니다"]}
    gap = round((our_usd - lowest_usd) / lowest_usd * 100, 1)
    if gap <= 0:
        return {"position": "cheapest_or_equal", "gap_pct": gap, "hints": []}
    if gap <= 15:
        return {"position": "near", "gap_pct": gap, "hints": ["1+1 세트로 개당가 비교 완화"]}
    return {"position": "unfavorable", "gap_pct": gap,
            "hints": ["1+1 세트·번들로 직접 비교 회피", "상품 이미지·설명(한국 인기 근거) 보강", "가격 외 채널(SNS) 노출 우선", "판매·클릭 데이터가 쌓이면 효과 검증"]}


def log_price_position(entry, pos):
    """data/price_strategy_log.json 에 날짜별로 누적한다. 같은 상품의 같은 날 기록은 덮어쓴다."""
    try:
        d = json.loads(STRATEGY_LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {"schema_version": 1, "note": "판매 데이터가 생기기 전까지는 관측만 기록한다. 효과를 추정하지 않는다.", "items": []}
    row = {"date": entry.get("date"), "pd_no": entry.get("pd_no"), "title": entry.get("title"),
           "our_usd": entry.get("single_usd"), "shop_com_lowest_usd": entry.get("shop_com_lowest_usd"),
           "margin_pct": entry.get("single_margin_pct"), **pos, "observed_sales": None, "observed_clicks": None}
    d["items"] = [r for r in d["items"] if not (r.get("pd_no") == row["pd_no"] and r.get("date") == row["date"])] + [row]
    STRATEGY_LOG.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_LOG.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- Main


# JARVIS 채점(shopify_demand_score.json)의 버킷을 Shopify 3개 카테고리로 묶는다.
BUCKETS = {c["tag"]: set(c["score_buckets"]) for c in STRATEGY["categories"]}
GRADE_ORDER = {"S": 0, "A": 1}
# 정본 등급은 3개 카테고리 모두 S만. 바디 카테고리 초안 예외는 등급을 부여하지 않는다.
ALLOWED_GRADES = {c["tag"]: tuple(c["allowed_grades"]) for c in STRATEGY["categories"]}


def grade_label(cat):
    return "/".join(ALLOWED_GRADES[cat[0]])


def _find_pd(obj, pd_no):
    if isinstance(obj, list):
        for x in obj:
            r = _find_pd(x, pd_no)
            if r:
                return r
    elif isinstance(obj, dict):
        if str(obj.get("pdNo")) == str(pd_no):
            return obj
        for v in obj.values():
            r = _find_pd(v, pd_no)
            if r:
                return r
    return None


def daiso_lookup(pd_no):
    """상품번호로 다이소몰 현재 정보를 읽는다 (이미지 전체·평점·재고·판매상태). 없으면 None."""
    req = urllib.request.Request(
        "https://www.daisomall.co.kr/ssn/search/SearchGoods?" + urllib.parse.urlencode({"searchTerm": str(pd_no)}),
        headers={"User-Agent": UA, "Referer": "https://www.daisomall.co.kr/", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            hit = _find_pd(json.loads(r.read().decode("utf-8", "replace")), pd_no)
    except Exception as exc:  # noqa: BLE001
        log(f"  daiso lookup failed {pd_no}: {exc}")
        return None
    if not hit:
        return None
    info = (daiso_post("/pd/pdr/pdDtl/selPdDtlInfo", pd_no) or {}).get("data") or {}
    p = dict(hit)
    try:
        p["_current_detail_available"] = (int(str(info.get("pdPrc") or "0")) > 0
                                          and int(str(info.get("stckQy") or "0")) > 0
                                          and info.get("exhYn") != "N" and info.get("soldOutYn") != "Y")
    except (TypeError, ValueError):
        p["_current_detail_available"] = False
    p["brndNm"] = str(hit.get("brndNm") or info.get("brndNm") or "").split(">")[0].strip()
    p["onlStckQy"] = info.get("stckQy") or hit.get("ONL_STCK_QY") or 0
    p["pdPrc"] = str(info.get("pdPrc") or hit.get("pdPrc") or "0")
    p["exhYn"] = info.get("exhYn") or "Y"
    p["pdImgUrlList"] = hit.get("pdImgUrlList") or hit.get("PD_IMG_URL_LIST") or ([hit["pdImgUrl"]] if hit.get("pdImgUrl") else [])
    return p


PRIORITY_SOURCE = "scripts/build_beauty_price_strategy.py (offline, recomputed from the actual inputs at run time)"
PRIORITY_FORMULA = "0.6*shopify_score + verified_price_points (only verified_below vs a verified delivered same-item minimum)"
PRIORITY_FALLBACK = "fallback_canonical_order"


def _fallback_priority(reason, as_of=None):
    return {"status": PRIORITY_FALLBACK, "reason": reason, "as_of": as_of, "by_pd": {}}


def _own_shipping_from_env():
    """우리 고객 배송비(단품). 모르면 None -> 배달가 비교가 불가능해 검증된 가격 우위 점수가 0 이 된다. 지어내지 않는다."""
    raw = os.environ.get("OWN_SHIPPING_USD", "").strip()
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value is not None and math.isfinite(value) and value >= 0 else None


def live_s_priority(now=None):
    """상업 우선순위(오프라인). 저장된 리포트를 믿지 않고 실제 입력 파일에서 지금 시각 기준으로 다시 계산한다.

    - 네트워크 호출 없음. 등급(S/A)은 정본 점수표가 유일한 권위이고, 이 계산은 순서만 바꾼다. 후보를 더하거나 빼지 않는다.
    - 전략/입력이 없거나 깨졌거나 정책이 일치하지 않으면 가짜 점수를 만들지 않고 정본 순서로 되돌아간다(status=fallback_canonical_order).
    - 안전·가격 근거·이미지·재고·중복·인증 게이트는 건드리지 않는다. 이후 단계에서 그대로 적용된다.
    """
    as_of = now or datetime.now(timezone.utc)
    stamp = as_of.isoformat()
    try:
        import build_beauty_price_strategy as bps  # noqa: PLC0415

        docs, status = bps.load_inputs(ROOT / "data")
        score = docs.get("score")
        if not isinstance(score, dict) or not isinstance(score.get("all_scored"), list):
            return _fallback_priority("score_input_missing_or_invalid", stamp)
        report = bps.build_strategy(docs, status, as_of, bps.DEFAULT_MAX_AGE_HOURS, _own_shipping_from_env())
        alignment, policy = report.get("config_alignment") or {}, report.get("policy") or {}
        if alignment.get("config_loaded") is not True or alignment.get("policy_id") != STRATEGY.get("policy_id"):
            return _fallback_priority("strategy_config_missing_invalid_or_mismatched", stamp)
        if policy.get("network_calls") is not False or policy.get("grade_changes_allowed") is not False \
                or policy.get("a_auto_upgrade_allowed") is not False:
            return _fallback_priority("strategy_policy_flags_unsafe", stamp)
        if (report.get("s_preservation") or {}).get("grade_changes") != []:
            return _fallback_priority("strategy_changed_grades", stamp)
        canonical = {str(r.get("pd_no")): r.get("grade") for r in score["all_scored"] if isinstance(r, dict)}
        by_pd = {}
        for prod in report.get("products") or []:
            pd = str(prod.get("pd_no"))
            if prod.get("grade") != canonical.get(pd) or prod.get("grade_changed_by_this_report") is not False:
                return _fallback_priority("strategy_grade_differs_from_canonical", stamp)
            pr = prod.get("priority") or {}
            value = pr.get("score")
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            pos = prod.get("price_position") or {}
            by_pd[pd] = {"score": float(value) if valid else None, "evidence_status": pr.get("evidence_status"),
                         "components": pr.get("components") or {}, "price_position": pos.get("status"),
                         "price_position_verified": pos.get("verified") is True, "priority_rank": prod.get("priority_rank")}
        return {"status": "live_strategy", "reason": None, "as_of": stamp, "by_pd": by_pd}
    except Exception as exc:  # noqa: BLE001  깨진 전략이 등록 흐름을 막거나 가짜 순위를 만들지 못하게 한다
        return _fallback_priority(f"strategy_error:{type(exc).__name__}", stamp)


def apply_priority(rows, priority):
    """정본 순서의 S 행에 우선순위 메타를 붙이고, 점수가 있으면 점수순(동점은 정본 순서)으로 정렬한다. 행을 더하거나 빼지 않는다."""
    ordered = []
    for index, row in enumerate(rows):
        info = (priority.get("by_pd") or {}).get(str(row.get("pd_no")))
        live = priority.get("status") == "live_strategy"
        meta = {"source": PRIORITY_SOURCE, "formula": PRIORITY_FORMULA, "as_of": priority.get("as_of"), "canonical_index": index,
                "status": ("live_strategy" if live and info and info["score"] is not None
                           else "row_unscored_canonical_position" if live else PRIORITY_FALLBACK),
                "reason": priority.get("reason") if not live else (None if info and info["score"] is not None else "row_has_no_strategy_score"),
                "shopify_score": row.get("shopify_score"), "score": None, "components": None, "evidence_status": None,
                "price_position": None, "price_position_verified": False, "strategy_rank": None}
        if live and info and info["score"] is not None:
            meta.update(score=info["score"], components=info["components"], evidence_status=info["evidence_status"],
                        price_position=info["price_position"], price_position_verified=info["price_position_verified"],
                        strategy_rank=info["priority_rank"])
        ordered.append(dict(row, _priority=meta))
    scored = sorted((r for r in ordered if r["_priority"]["score"] is not None), key=lambda r: -r["_priority"]["score"])
    return scored + [r for r in ordered if r["_priority"]["score"] is None]


def s_ranked(cat, priority=None):
    """Canonical S-grade rows only; missing or invalid source is an error, not permission to improvise.

    Candidates and grades come only from the canonical score file (S only, config bucket map). The offline commercial
    priority (live_s_priority) may reorder those S rows and annotates each with transparent `_priority` metadata; it never
    adds, removes or upgrades anything. Without a usable strategy the canonical order (grade, shopify_score) is kept."""
    d = json.loads((ROOT / "data/daiso_real/shopify_demand_score.json").read_text(encoding="utf-8-sig"))
    if not isinstance(d.get("all_scored"), list):
        raise ValueError("Canonical grade list unavailable")
    allowed = ALLOWED_GRADES[cat[0]]
    # 2026-10-11 카테고리 전담팀: 점수 파일의 desk(다이소몰 카테고리 목록 기준)가 있으면 그것으로 고른다.
    rows = [r for r in d["all_scored"] if r.get("grade") in allowed
            and ((r.get("desk") == cat[0]) if "desk" in r else (r.get("bucket") in BUCKETS[cat[0]]))]
    rows.sort(key=lambda r: (GRADE_ORDER[r["grade"]], -float(r.get("shopify_score") or 0)))
    if not rows:
        return rows
    return apply_priority(rows, priority if priority is not None else live_s_priority())


def title_key(s):
    return re.sub(r"[^\w]+", "", (s or "").casefold())


def title_family_key(title):
    """Collapse explicit cosmetic shade suffixes without merging strength/volume variants."""
    base = re.sub(r"\s*\([^)]*\)|\s*\[[^]]*\]", "", title or "")
    base = re.sub(r"\s+(?:\d+\s*)?(?:ash\s+)?(?:light\s+|dark\s+)?"
                  r"(?:brown|black|beige|pink|red|coral|rose|gray|grey|ivory)$", "", base, flags=re.I)
    return title_key(base)


def shop_keys(products):
    names, ids = set(), set()
    for p in products:
        names.add(title_key(p.get("title")))
        family = title_family_key(p.get("title"))
        if family and family != title_key(p.get("title")):
            names.add("family:" + family)
        # Older imports may have neither tags nor DS SKUs but include the source item in copy.
        source = re.search(r"Daiso Mall item\s+(\d+)", p.get("descriptionHtml") or "", re.I)
        if source:
            ids.add(source[1])
        for tag in p.get("tags") or []:
            m = re.fullmatch(r"daiso-pd-(\d+)", tag, re.I)
            if m:
                ids.add(m[1])
        for v in (p.get("variants") or {}).get("nodes", []):
            m = re.match(r"DS-(\d+)-\d+$", v.get("sku") or "", re.I)
            if m:
                ids.add(m[1])
    return names, ids


def already_registered(p, reg, names, ids, title=None):
    pd = str(p["pdNo"])
    fam = family_key(clean_name(p["pdNm"]))
    seen_ids = {str(i.get("pd_no")) for i in reg["items"]}
    seen_families = {i.get("family") or family_key(i.get("name_kr")) for i in reg["items"]}
    seen_titles = {title_key(i.get("title")) for i in reg["items"]}
    return (pd in seen_ids or pd in ids or fam in seen_families or
            title_key(clean_name(p["pdNm"])) in names or
            (bool(title) and (title_key(title) in names | seen_titles or
                              "family:" + title_family_key(title) in names)))


def pick(cat, shop, names, ids, reg, rows=None, excluded=None):
    rows = s_ranked(cat) if rows is None else rows
    for row in rows:
        pd_no = row.get("pd_no")
        if not pd_no or str(pd_no) in (excluded or set()) or str(pd_no) in ids or any(str(i.get("pd_no")) == str(pd_no) for i in reg["items"]):
            continue
        p = daiso_lookup(pd_no)
        fallback = row.get("selection_source") == body_fallback.SELECTION_SOURCE
        if fallback and (cat[0] != "body" or str(pd_no) == "1049275" or
                         not p or p.get("_current_detail_available") is not True or
                         str(p.get("pdNo")) != str(pd_no)):
            continue
        if p and sellable(p) and not already_registered(p, reg, names, ids):
            if fallback:
                p["_grade"], p["_source"], p["_score"] = "-", body_fallback.SELECTION_SOURCE, None
            else:
                p["_grade"], p["_source"], p["_score"] = row.get("grade") or "S", "jarvis_s_list", row.get("shopify_score")
            p["_priority"] = row.get("_priority")
            return p
    return None


# ---------------------------------------------------------------------------
# 메이크업 실시간 랭킹 대체 (2026-10-16 사용자 지시)
#   "카테고리 메이크업 제품 등록에 S급 없으면 실시간 랭킹 메이크업 하나씩 등록되게"
#   - 정본 S 등급은 바꾸지 않는다(grade_policy S 전용 그대로). 별도 출처의 '비공개 초안' 이다.
#   - 메이크업에 등록 가능한 S 가 없을 때만, 랭킹 순서대로 하루 1개.
#   - 품절·재고·중복·미국 판매 제약(선케어·미백 등)·가격 근거·고시·라벨 검사는 S 와 똑같다.
#   - 비비·쿠션·팩트·파운데이션은 이름에 SPF 가 없어도 자외선차단인 경우가 많다(1068733 이 그랬다).
#     이 형태는 고시 전성분이 확인되고 자외선 차단 성분이 없을 때만 올린다.
#   - 공개(ACTIVE)하지 않는다. 사람이 S 파이프라인(고시·라벨·법률)으로 확인해야 공개된다.
RANKING_SOURCE = "daiso_realtime_ranking"
RANKING = STRATEGY.get("makeup_ranking_fallback") or {}


def ranking_enabled(cat) -> bool:
    return bool(RANKING.get("enabled")) and cat[0] == RANKING.get("category") == "makeup"


def fetch_makeup_ranking():
    """다이소몰 '실시간 랭킹 메이크업' 목록(현재 순위 순). 실패하면 예외 (빈 목록으로 지어내지 않는다)."""
    query = urllib.parse.urlencode({"pageNum": 1, "cntPerPage": 30, "largeExhCtgrNo": RANKING["large_ctgr"],
                                    "middleExhCtgrNo": RANKING["middle_ctgr"]})
    req = urllib.request.Request(RANKING["api_url"] + "?" + query,
                                 headers={"User-Agent": UA, "Accept": "application/json",
                                          "Referer": RANKING["page_url"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    rows = (json.loads(raw.decode("utf-8", "replace")).get("resultSet") or {}).get("result") or []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict) and "resultDocuments" in rows[0]:
        rows = rows[0]["resultDocuments"]
    rows = [x for x in rows if isinstance(x, dict) and x.get("pdNo")]
    if not rows:
        raise RuntimeError("ranking response has no products")
    # 화면의 '현재 순위 1, 2, 3…' 은 응답 순서다. NOW_RANK(144, 296, 274…)는 화면 순위가 아니라서 정렬에 쓰지 않는다.
    for i, x in enumerate(rows, 1):
        x["_display_rank"] = i
    receipt = {"url": RANKING["page_url"], "api": RANKING["api_url"], "fetched_at": datetime.now(timezone.utc).isoformat(),
               "sha256": hashlib.sha256(raw).hexdigest(), "count": len(rows)}
    for x in rows:
        x["_receipt"] = receipt
    return rows


def _ranking_regulated(name, pd_no, g):
    """선케어·미백 등 미국 판매 제약이면 사유, 아니면 None. 근거를 못 보면 막는 쪽이다."""
    from daiso.score_shopify_demand import us_blockers  # noqa: PLC0415  정본 판정과 같은 함수
    kind, why = us_blockers(name, pd_no)
    if kind:
        return f"us_blocker:{kind}:{why}"
    if REGULATED_RE.search(name or "") or REGULATED_RE.search(g.get("functional", "") or ""):
        return "regulated_functional_or_name"
    ingredients = (g.get("ingredients") or "").lower()
    hit = next((u for u in RANKING["uv_filter_ingredients"] if u.lower() in ingredients), None)
    if hit:
        return f"uv_filter_in_ingredients:{hit}"
    low = (name or "").lower()
    if any(f in low for f in RANKING["spf_risk_forms"]) and not ingredients:
        return "spf_unverified_base_makeup"
    return None


def pick_ranking(cat, shop, names, ids, reg, rows, excluded, skipped):
    """랭킹 순서대로 첫 번째 적격 상품. 고시까지 확인해 p['_gosi'] 에 담아 둔다."""
    from daiso.score_shopify_demand import is_non_core  # noqa: PLC0415
    seen = {str(i.get("pd_no")) for i in reg["items"]}
    # 상위 몇 개만 본다. 후보마다 가격 비교(shop.com 브라우저)가 1분 넘게 걸려 30개를 다 보면 작업 시간이 넘친다.
    for row in rows[:RANKING["max_candidates_checked"]]:
        pd_no = str(row.get("pdNo"))
        if pd_no in (excluded or set()) or pd_no in ids or pd_no in seen:
            continue
        excluded.add(pd_no)
        name = clean_name(row.get("pdNm") or "")
        if row.get("soldOutYn") == "Y":
            skipped.append({"pd_no": pd_no, "rank": row.get("_display_rank"), "reason": "sold_out"})
            continue
        if is_non_core(name):
            skipped.append({"pd_no": pd_no, "rank": row.get("_display_rank"), "reason": "non_core"})
            continue
        p = daiso_lookup(pd_no)
        if not p or not sellable(p) or already_registered(p, reg, names, ids):
            skipped.append({"pd_no": pd_no, "rank": row.get("_display_rank"), "reason": "not_sellable_or_registered"})
            continue
        # 바디 카테고리 대체와 같은 원칙: 대체 경로는 유료·미상 비용 호출(Gemini 비전)을 하지 않는다.
        g = collect_gosi(pd_no, allow_ai=False)
        why = _ranking_regulated(name, pd_no, g)
        if why:
            log(f"  ranking skip {pd_no} {name}: {why}")
            skipped.append({"pd_no": pd_no, "rank": row.get("_display_rank"), "reason": why})
            continue
        p["_grade"], p["_source"], p["_score"] = "RANK", RANKING_SOURCE, None
        p["_priority"] = None
        p["_gosi"] = g
        p["_ranking"] = {"display_rank": row.get("_display_rank"), "now_rank_field": row.get("NOW_RANK"),
                         "rating": row.get("avgStscVal"), "reviews": row.get("revwCnt"), "receipt": row.get("_receipt")}
        return p
    return None


def draft_allowed(p) -> bool:
    """비공개 초안 허용: 상품별 사업주 승인, 또는 사업주가 정한 메이크업 랭킹 대체 정책."""
    if owner_approved_draft(p["pdNo"]):
        return True
    return p.get("_source") == RANKING_SOURCE and bool(RANKING.get("enabled")) and RANKING.get("status") == "DRAFT_ONLY"


SAFETY_MISSING = manufacturer_safety.SAFETY_MISSING


def owner_approved_draft(pd_no):
    return owner_draft_approval.approved(pd_no, ROOT)


BODY_RESEARCH_DRAFT_OPT_IN = "body_category_research_draft_fallback"


def body_research_draft_policy_enabled():
    """Separate default-off policy exception, re-read at every authorization boundary."""
    try:
        policy = pricing_model.load_commerce_strategy().get("grade_policy")
        return isinstance(policy, dict) and policy.get(BODY_RESEARCH_DRAFT_OPT_IN) is True
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return False


def body_category_draft_approved():
    """Both policy and revocable category scope are required; never safety clearance."""
    if not body_research_draft_policy_enabled():
        return False
    try:
        return owner_draft_approval.category_approved(
            body_fallback.CATEGORY_CODE, body_fallback.SOURCE_URL, ROOT) is True
    except (AttributeError, OSError, ValueError, TypeError):
        return False


def body_fallback_rows(reg):
    """Validate fresh source on a private copy; dry runs/skips never advance history."""
    if not body_research_draft_policy_enabled():
        return [], "body_category_research_draft_policy_not_enabled", None
    if not body_category_draft_approved():
        return [], "owner_category_fallback_approval_missing_or_revoked", None
    # Explicit workflow output is authoritative: never silently use tracked data
    # if an override is missing/invalid. Absolute, escaping and symlink-escaping
    # paths cannot authorize a source outside this repository.
    raw_path = os.environ.get("BODY_FALLBACK_CATALOG_PATH", "data/daiso_real/desk_catalog.json")
    try:
        relative = Path(raw_path.replace("\\", "/"))
        root = ROOT.resolve()
        if (not raw_path.strip() or ":" in raw_path or relative.is_absolute() or relative.drive or relative.root
                or ".." in relative.parts):
            return [], "body_category_catalog_path_invalid", None
        source_path = (root / relative).resolve()
        if not source_path.is_relative_to(root):
            return [], "body_category_catalog_path_invalid", None
        raw = source_path.read_bytes()
        catalog = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return [], "body_category_source_missing_or_unreadable", None
    staged = copy.deepcopy(reg)
    rows, reason = body_fallback.prepare_queue(catalog, staged)
    for row in rows:
        row["_priority"]["catalog_path"] = source_path.relative_to(root).as_posix()
        row["_priority"]["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    return rows, reason, staged.get(body_fallback.QUEUE_KEY) if reason is None else None


def manufacturer_safety_record(pd_no):
    """제품별 제조사 안전성 입증 자료(MoCRA) 확인. 안전 게이트이며 마진과 무관하다.

    판정은 scripts/manufacturer_safety.py 한 곳에 있고, listing gate(build_listing_gate.py)도 같은 함수를 pdNo 마다 부른다.
    그래서 여기서 '덮임' 인 상품이 게이트에서 막히는 일(또는 반대)이 없다. 비공개 값은 반환하지 않고, 읽을 수 없으면 덮이지 않은 것으로 본다.
    라벨의 product_safety_evidence 나 계획/메모는 자료 보유로 세지 않는다. 승인이나 보유 사실을 지어내지 않는다."""
    return manufacturer_safety.manufacturer_safety_record(pd_no, ROOT)


def canonical_public_gate(pd_no):
    """Published listing gate is authoritative for public sale, not for draft creation.

    Check the established semantic input signature every time (including immediately
    before publication). Missing, stale, incomplete and contradictory rows fail closed.
    Human/legal fields are never generated or inferred here.
    """
    path = ROOT / "data/listing_gate.json"
    try:
        gate = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"public_ready": False, "reasons": ["listing_gate_missing_or_unreadable"]}
    if not isinstance(gate, dict):
        return {"public_ready": False, "reasons": ["listing_gate_invalid"]}
    try:
        gate_signature.require_current(gate)
    except RuntimeError as exc:
        return {"public_ready": False, "reasons": ["listing_gate_stale:" + str(exc)]}
    if not isinstance(gate.get("items"), list):
        return {"public_ready": False, "reasons": ["listing_gate_items_missing_or_invalid"]}
    rows = [r for r in gate["items"] if isinstance(r, dict) and str(r.get("pd_no")) == str(pd_no)]
    if len(rows) != 1:
        return {"public_ready": False, "reasons": ["listing_gate_product_missing_or_ambiguous"]}
    row = rows[0]
    reasons = []
    legal = row.get("legal")
    if not isinstance(legal, dict) or legal.get("hard_block") is not False:
        reasons.append("listing_gate_legal_hard_block" if isinstance(legal, dict) and legal.get("hard_block") is True
                       else "listing_gate_legal_hard_block_unknown")
    if row.get("public_ready") is not True:
        reasons.append("listing_gate_public_not_ready")
    if row.get("ready") is not True:
        reasons.append("listing_gate_draft_not_ready")
    if row.get("legal_full_complete") is not True:
        reasons.append("listing_gate_legal_full_incomplete")
    blockers = row.get("public_blocked_by")
    if not isinstance(blockers, list):
        reasons.append("listing_gate_public_blockers_unknown")
    elif blockers:
        reasons.append("listing_gate_public_blocked_by:" + ",".join(str(x) for x in blockers))
    return {"public_ready": not reasons, "reasons": reasons,
            "legal_hard_block": legal.get("hard_block") if isinstance(legal, dict) else None,
            "legal_hard_block_reason": legal.get("hard_block_reason") if isinstance(legal, dict) else None,
            "public_blocked_by": blockers, "gate_generated_at": gate.get("generated_at")}


def linked_pd_ids(product, registry):
    """Only exact registered Shopify ID, Daiso ID tag, or source item marker count."""
    ids = {str(i["pd_no"]) for i in registry["items"]
           if i.get("shopify_id") == product.get("id") and i.get("pd_no")}
    for tag in product.get("tags") or []:
        match = re.fullmatch(r"daiso-pd-(\d+)", str(tag), re.I)
        if match:
            ids.add(match[1])
    for match in re.finditer(r"Daiso Mall item\s+(\d+)", product.get("descriptionHtml") or "", re.I):
        ids.add(match[1])
    return ids


def linked_pd_no(product, registry):
    ids = linked_pd_ids(product, registry)
    return next(iter(ids)) if len(ids) == 1 else None


def record_quarantine_identity(registry, product_id, pd_no, status, reasons):
    entry = next((i for i in registry["items"] if i.get("shopify_id") == product_id and
                  str(i.get("pd_no")) == pd_no), None)
    if entry is None:
        entry = {"pd_no": pd_no, "shopify_id": product_id, "source": "exact_shopify_identity"}
        registry["items"].append(entry)
    entry["status"] = status
    entry["quarantine_reasons"] = reasons
    save_registry(registry)


def quarantine_blocked_public(shop, products, registry, publication_id, results):
    """Explicit opt-in: DRAFT only for an exact ID with a current explicit legal block."""
    if not publication_id:
        raise RuntimeError("Cannot verify publication state for quarantine")
    for row in products:
        # Read all candidates fresh; do not infer Daiso identity from titles/families.
        identity_ids = linked_pd_ids(row, registry)
        if len(identity_ids) > 1:
            results.append({"shopify_id": row["id"], "status": "skipped_identity_ambiguous"})
            continue
        if not identity_ids:
            continue
        before = shop.read_product(row["id"], publication_id)
        if not before or before.get("id") != row["id"]:
            raise RuntimeError(f"Quarantine source read-back missing: {row['id']}")
        if (before.get("variants") or {}).get("pageInfo", {}).get("hasNextPage"):
            raise RuntimeError(f"Quarantine variants truncated: {row['id']}")
        pd_no = linked_pd_no(before, registry)
        if not pd_no:
            results.append({"shopify_id": row["id"], "status": "skipped_identity_changed_or_ambiguous"})
            continue
        gate = canonical_public_gate(pd_no)
        if gate.get("legal_hard_block") is not True:
            results.append({"shopify_id": row["id"], "pd_no": pd_no,
                            "status": "skipped_no_explicit_current_legal_block",
                            "gate_reasons": gate["reasons"]})
            continue
        if before.get("status") != "ACTIVE" and before.get("publishedOnPublication") is False:
            if before.get("status") == "DRAFT":
                record_quarantine_identity(registry, row["id"], pd_no, "DRAFT",
                                           ["canonical_legal_hard_block"] + gate["reasons"])
            results.append({"shopify_id": row["id"], "pd_no": pd_no,
                            "status": "already_not_public", "verified_status": before.get("status"),
                            "registry_recorded": before.get("status") == "DRAFT"})
            continue
        record_quarantine_identity(registry, row["id"], pd_no, "quarantine_requested",
                                   ["canonical_legal_hard_block"] + gate["reasons"])
        try:
            shop.set_status(row["id"], "DRAFT")
        except Exception:
            results.append({"shopify_id": row["id"], "pd_no": pd_no,
                            "status": "quarantine_mutation_uncertain",
                            "manual_reconciliation_required": True, "registry_recorded": True})
            raise
        try:
            after = shop.read_product(row["id"], publication_id)
        except Exception:
            results.append({"shopify_id": row["id"], "pd_no": pd_no,
                            "status": "quarantine_readback_unavailable",
                            "manual_reconciliation_required": True, "registry_recorded": True})
            raise
        if (not after or (after.get("variants") or {}).get("pageInfo", {}).get("hasNextPage") or
                after.get("status") != "DRAFT" or after.get("publishedOnPublication") is not False or
                any(after.get(k) != before.get(k) for k in
                    ("id", "handle", "title", "tags", "descriptionHtml", "variants"))):
            record_quarantine_identity(registry, row["id"], pd_no, "quarantine_unverified",
                                       ["readback_or_publication_mismatch"] + gate["reasons"])
            results.append({"shopify_id": row["id"], "pd_no": pd_no,
                            "status": "quarantine_readback_failed", "manual_reconciliation_required": True,
                            "registry_recorded": True})
            raise RuntimeError(f"Quarantine read-back/publication mismatch: {row['id']}")
        record_quarantine_identity(registry, row["id"], pd_no, "DRAFT",
                                   ["canonical_legal_hard_block"] + gate["reasons"])
        results.append({"shopify_id": row["id"], "pd_no": pd_no, "title": before["title"],
                        "status": "quarantined_draft", "verified_not_public": True,
                        "gate_reasons": gate["reasons"], "registry_recorded": True})
    return results


def backfill_banner(shop, products, registry, publication_id):
    """Compatibility no-op: existing human descriptions are never auto-prefixed.

    Old workflow/input values may still request BACKFILL_BANNER=1. Preserve
    every existing DRAFT/ACTIVE description, with no read or mutation calls.
    Removing historical claims is a separately reviewed owner action.
    """
    registered = {str(i.get("shopify_id")) for i in registry["items"] if i.get("shopify_id")}
    return [{"shopify_id": row["id"], "status": "skipped_automatic_banner_disabled"}
            for row in products if row.get("id") and
            (str(row["id"]) in registered or
             any(str(tag).casefold() == "daiso-daily" or
                 re.fullmatch(r"daiso-pd-\d+", str(tag), re.I)
                 for tag in row.get("tags") or []))]


def verify_product(shop, product_id, item, pub_id, published=False):
    p = shop.read_product(product_id, pub_id)
    if not p or p["id"] != product_id or title_key(p["title"]) != title_key(item["title"]):
        raise RuntimeError("Product read-back missing or title mismatch")
    if p["status"] != ("ACTIVE" if published else "DRAFT") or bool(p["publishedOnPublication"]) != published:
        raise RuntimeError("Product status/publication mismatch")
    actual = {(v.get("sku"), round(float(v["price"]), 2)) for v in p["variants"]["nodes"]}
    expected = {(v["sku"], round(v["price"], 2)) for v in item["variants"]}
    if actual != expected:
        raise RuntimeError("Variant SKU/price read-back mismatch")
    media = p["media"]["nodes"]
    if len(media) != len(item["images"]) or any(m["mediaContentType"] != "IMAGE" or m["status"] != "READY" for m in media):
        raise RuntimeError("Product image read-back not ready")
    return p


BACKFILL_DRAFT_IMAGES = os.environ.get("BACKFILL_DRAFT_IMAGES", "0").strip().lower() in {"1", "true", "yes"}
BACKFILL_DRAFT_IMAGES_LIMIT = int(os.environ.get("BACKFILL_DRAFT_IMAGES_LIMIT", "3"))


def gallery_append_reserved(entry):
    return (isinstance(entry, dict) and isinstance(entry.get("image_backfill"), dict)
            and entry["image_backfill"].get("state") == "append_reserved")


def gallery_recheck_candidates(registry):
    """Reconcile every uncertain write first, irrespective of cached status/count."""
    items = [it for it in registry.get("items") or [] if isinstance(it, dict)]
    pending = [it for it in items if gallery_append_reserved(it)]
    drafts = [it for it in items if not gallery_append_reserved(it)
              and str(it.get("status") or "").upper() == "DRAFT"
              and re.fullmatch(r"gid://shopify/Product/[0-9]+", str(it.get("shopify_id") or ""))]
    cursor = registry.get("gallery_review_cursor")
    for index, entry in enumerate(drafts):
        if entry["shopify_id"] == cursor:
            drafts = drafts[index + 1:] + drafts[:index + 1]
            break
    return pending + drafts


def gallery_media_hash(url):
    """Hash actual Shopify CDN bytes without trusting alt/filename or redirects."""
    if not isinstance(url, str):
        return None
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "cdn.shopify.com"
            or not parsed.path.startswith("/s/files/")):
        return None

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            data = response.read(gallery_review.MAX_BYTES + 1)
        if not data or len(data) > gallery_review.MAX_BYTES:
            return None
        return hashlib.sha256(data).hexdigest()
    except (OSError, ValueError):
        return None


def gallery_append_matches(entry, observation):
    """Reconcile reserved writes from actual bytes; a saved success flag is insufficient."""
    receipt = entry.get("image_backfill") or {}
    if gallery_review.observation_error(entry, observation):
        return False
    old = receipt.get("preserve_media_hashes")
    expected = receipt.get("expected_new_hashes")
    if (not isinstance(old, dict) or not isinstance(expected, list) or not expected
            or any(not isinstance(h, str) or not gallery_review.HASH.fullmatch(h) for h in expected)):
        return False
    actual = {m["id"]: m["content_sha256"] for m in observation["media"]}
    return (all(actual.get(mid) == digest for mid, digest in old.items())
            and len(actual) == len(old) + len(expected)
            and sorted(digest for mid, digest in actual.items() if mid not in old) == sorted(expected))


def record_verified_gallery_append(registry, entry, observation):
    entry["images"] = len(observation["media"])
    entry["gallery_complete"] = False
    entry["image_backfill"].update(state="verified", media_hashes={m["id"]: m["content_sha256"] for m in observation["media"]})
    entry["draft_reasons"] = [r for r in entry.get("draft_reasons") or [] if r != "no_usable_product_images"]
    save_registry(registry)


def append_gallery_media(shop, registry, entry, before, urls, alts, *, expected_hashes, expected_evidence_digest=None):
    """Append-only with immediate pre/post checks and a durable uncertain-write hold.

    This Shopify path has no atomic expected-status condition. A concurrent owner
    edit can still race the final read. Any mismatch stops further writes; never
    issue corrective status, deletion, reorder or replacement mutations.
    """
    fresh = shop.read_gallery(entry["shopify_id"])
    if (not urls or len(urls) != len(expected_hashes or [])
            or not gallery_review.same_inventory(entry, before, fresh)):
        return {"status": "review_required", "reasons": ["gallery_changed_before_append"], "stop_further_writes": True}
    def current_evidence_matches():
        if expected_evidence_digest is None:  # Existing zero-image QA path has separate completion semantics.
            return True
        latest = gallery_review.plan_additions(entry, gallery_review.load_manifest(ROOT, str(entry["pd_no"])), ROOT, fresh)
        return (latest["status"] == "additions_prepared" and latest["add_asset_sha256s"] == expected_hashes
                and latest["assessment"]["evidence_digest"] == expected_evidence_digest)

    if not current_evidence_matches():
        return {"status": "review_required", "reasons": ["gallery_evidence_changed_before_append"], "stop_further_writes": True}
    old = {m["id"]: m["content_sha256"] for m in before["media"]}
    entry["image_backfill"] = {"state": "append_reserved", "at": datetime.now(timezone.utc).isoformat(),
                               "preserve_media_hashes": old, "expected_new_hashes": expected_hashes, "evidence_digest": expected_evidence_digest}
    save_registry(registry)  # An uncertain outcome is never automatically appended again.
    if not current_evidence_matches():
        entry["image_backfill"]["state"] = "cancelled_before_append"
        save_registry(registry)
        return {"status": "review_required", "reasons": ["gallery_evidence_changed_before_append"], "stop_further_writes": True}
    result = shop.gql("""mutation($id:ID!,$media:[CreateMediaInput!]){
      productUpdate(product:{id:$id},media:$media){product{id status} userErrors{field message}}}""",
      {"id": entry["shopify_id"], "media": [
          {"originalSource": url, "mediaContentType": "IMAGE", "alt": (alts[i:i + 1] or [entry.get("title") or ""])[0]}
          for i, url in enumerate(urls)]})["productUpdate"]
    if (result.get("userErrors") or (result.get("product") or {}).get("id") != entry["shopify_id"]
            or result["product"].get("status") != "DRAFT"):
        return {"status": "verification_pending", "reasons": ["gallery_append_outcome_unverified"], "stop_further_writes": True}
    after = shop.read_gallery(entry["shopify_id"])
    if not gallery_append_matches(entry, after):
        # Normal asynchronous processing can be reconciled read-only on a later run.
        return {"status": "verification_pending", "reasons": ["gallery_post_state_or_media_unverified"], "stop_further_writes": True}
    record_verified_gallery_append(registry, entry, after)
    return {"status": "attached", "count": len(urls), "preserve_media_ids": sorted(old), "observation": after}


def backfill_draft_images(shop, registry):
    """Preserve safe zero-image repair; partial galleries require full evidence.

    Counts never prove completion. Existing media/body/status are never replaced.
    Current evidence and media are checked again immediately before attachment.
    """
    out, stopped = [], False
    last_attempted = registry.get("gallery_review_cursor")
    for index, entry in enumerate(gallery_recheck_candidates(registry)):
        pd = str(entry.get("pd_no") or "")
        manifest = gallery_review.load_manifest(ROOT, pd)
        observation = {}
        try:
            pending = gallery_append_reserved(entry)
            if ((pending or not stopped) and index < max(0, BACKFILL_DRAFT_IMAGES_LIMIT)
                    and re.fullmatch(r"gid://shopify/Product/[0-9]+", str(entry.get("shopify_id") or ""))):
                if not pending:
                    last_attempted = entry["shopify_id"]
                observation = shop.read_gallery(entry["shopify_id"])
            plan = gallery_review.plan_additions(entry, manifest, ROOT, observation)
            if pending:
                if gallery_append_matches(entry, observation):
                    record_verified_gallery_append(registry, entry, observation)
                    plan["status"] = "reconciled"
                    entry["gallery_complete"] = plan["gallery_complete"]
                    if (entry["image_backfill"].get("evidence_digest") is not None and
                            (not plan["gallery_complete"] or plan["assessment"].get("evidence_digest") != entry["image_backfill"]["evidence_digest"])):
                        plan.update(status="attached_review_required", gallery_complete=False,
                                    reasons=["gallery_evidence_changed_after_append"], stop_further_writes=True)
                        entry["gallery_complete"] = False
                    save_registry(registry)
                else:
                    plan.update(status="verification_pending", gallery_complete=False,
                                add_asset_sha256s=[], reasons=["prior_gallery_append_requires_reconciliation"], stop_further_writes=True)
            elif stopped:
                plan.update(status="review_required", add_asset_sha256s=[], reasons=["prior_gallery_write_requires_reconciliation"], stop_further_writes=True)
            elif index >= max(0, BACKFILL_DRAFT_IMAGES_LIMIT):
                plan["reasons"] = ["current_inventory_read_deferred"]
            elif not gallery_review.observation_error(entry, observation):
                title = str(entry.get("title") or "")
                urls, alts, expected = [], [], []
                legacy_empty = not observation["media"]
                if not observation["media"]:
                    # Retain the established verified-image path without calling it a full gallery.
                    if title and not re.search(r"[가-힣]", title):
                        product = daiso_lookup(pd)
                        if product and str(product.get("pdNo")) == pd:
                            images = prepare_images(product, shop, title=title)
                            urls, alts = images["resource_urls"], images.get("alts") or []
                            expected = images.get("output_sha256s") or []
                            plan.update(gallery_complete=False, add_asset_sha256s=[], reasons=["gallery_completion_not_verified"])
                elif plan["status"] == "additions_prepared":
                    payloads = gallery_review.prepared_payloads(pd, manifest, ROOT, plan["add_asset_sha256s"])
                    # Recheck the full snapshot before staged upload as well as product attachment.
                    if not gallery_review.same_inventory(entry, observation, shop.read_gallery(entry["shopify_id"])):
                        plan.update(status="review_required", add_asset_sha256s=[], reasons=["gallery_changed_before_upload"], stop_further_writes=True)
                        stopped = True
                        out.append(plan)
                        continue
                    expected = plan["add_asset_sha256s"]
                    for digest, data in payloads:
                        if data.startswith(b"\xff\xd8\xff"):
                            extension, mime = "jpg", "image/jpeg"
                        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
                            extension, mime = "png", "image/png"
                        else:
                            raise ValueError("reviewed_asset_format_unsupported")
                        urls.append(shop.upload_product_image(data, "gallery-" + digest + "." + extension, mime))
                        alts.append(title)
                    # Revocation during uploads must prevent attachment of the staged assets.
                    manifest = gallery_review.load_manifest(ROOT, pd)
                    refreshed = gallery_review.plan_additions(entry, manifest, ROOT, shop.read_gallery(entry["shopify_id"]))
                    if (refreshed["status"] != "additions_prepared" or refreshed["add_asset_sha256s"] != expected
                            or refreshed["assessment"]["evidence_digest"] != plan["assessment"]["evidence_digest"]):
                        plan.update(status="review_required", add_asset_sha256s=[], reasons=["gallery_evidence_changed_before_append"], stop_further_writes=True)
                        stopped = True
                        out.append(plan)
                        continue
                if urls:
                    update = append_gallery_media(shop, registry, entry, observation, urls, alts, expected_hashes=expected,
                        expected_evidence_digest=None if legacy_empty else plan["assessment"]["evidence_digest"])
                    after = update.pop("observation", None)
                    plan.update(update)
                    if after is not None and not legacy_empty:
                        verified = gallery_review.plan_additions(entry, gallery_review.load_manifest(ROOT, pd), ROOT, after)
                        plan["gallery_complete"] = verified["gallery_complete"]
                        plan["assessment"] = verified["assessment"]
                        entry["gallery_complete"] = plan["gallery_complete"]
                        if not plan["gallery_complete"]:
                            plan.update(status="attached_review_required", reasons=["gallery_evidence_changed_after_append"], stop_further_writes=True)
                        save_registry(registry)
        except Exception:  # Raw errors can contain private URLs/paths. Never retry an uncertain write.
            plan = gallery_review.plan_additions(entry, manifest, ROOT, observation)
            plan.update(status="review_required", gallery_complete=False, add_asset_sha256s=[],
                        reasons=["gallery_repair_failed_or_unverified"], stop_further_writes=True)
        stopped = stopped or plan.get("stop_further_writes") is True
        out.append(plan)
    if last_attempted != registry.get("gallery_review_cursor"):
        registry["gallery_review_cursor"] = last_attempted
        try:
            save_registry(registry)
        except Exception:
            out.append({"status": "review_required", "gallery_complete": False,
                        "reasons": ["gallery_review_cursor_not_persisted"], "stop_further_writes": True})
    return out


def main():
    enrich_only = '--enrich-only' in sys.argv or os.environ.get('ENRICH_ONLY') == '1'
    shop = None
    names, ids = set(), set()
    pub = None
    have_creds = bool(os.environ.get("SHOPIFY_STORE")) and (
        os.environ.get("SHOPIFY_ADMIN_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET")
    )
    if have_creds:
        shop = Shopify()
        products = shop.existing_products()
        names, ids = shop_keys(products)
        pub = shop.online_store_publication()
        log(f"Shopify OK. online store publication: {pub}")
    elif not DRY_RUN:
        log("ERROR: Shopify credentials are missing (SHOPIFY_STORE + token/client secret).")
        return 2
    else:
        log("DRY_RUN without Shopify credentials: duplicate check skipped.")

    try:
        reg = load_registry()
    except (OSError, ValueError, TypeError) as exc:
        log(f"ERROR: registry unavailable: {exc}")
        return 2
    today = kst_today()
    results, failures = [], 0
    backfill = []
    quarantined = []
    pending_notice = any((entry.get('notice_enrichment') or {}).get('state') == 'reserved'
                         for entry in reg.get('items') or [])
    pending_gallery = any(gallery_append_reserved(entry) for entry in reg.get("items") or []) or pending_notice
    if shop is not None and not DRY_RUN and QUARANTINE_BLOCKED_PUBLIC and not pending_gallery and not enrich_only:
        try:
            quarantine_blocked_public(shop, products, reg, pub, quarantined)
        except Exception as exc:
            log(f"ERROR: quarantine failed; not creating daily products: {exc}")
            out = {"run_at": datetime.now(timezone.utc).isoformat(), "dry_run": False,
                   "quarantine_blocked_public": quarantined,
                   "quarantine_error": str(exc)[:500], "banner_backfill": [], "results": [],
                   "daily_creation_blocked": "quarantine_failed"}
            os.makedirs("out", exist_ok=True)
            with open("out/daiso_daily_beauty_result.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            return 2
    if shop is not None and not DRY_RUN and BACKFILL_BANNER and not pending_notice and not enrich_only:
        try:
            backfill = backfill_banner(shop, products, reg, pub)
        except Exception as exc:
            log(f"ERROR: banner backfill failed; not creating daily products: {exc}")
            out = {"run_at": datetime.now(timezone.utc).isoformat(), "dry_run": False,
                   "quarantine_blocked_public": quarantined,
                   "banner_backfill": [{"status": "failed", "error": str(exc)[:500],
                                        "partial_updates_possible": True}],
                   "results": [], "daily_creation_blocked": "banner_backfill_failed"}
            os.makedirs("out", exist_ok=True)
            with open("out/daiso_daily_beauty_result.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            return 2
    image_backfill = []
    if shop is not None and not DRY_RUN and BACKFILL_DRAFT_IMAGES and not pending_notice and not enrich_only:
        image_backfill = backfill_draft_images(shop, reg)
        log(f"draft image backfill: {image_backfill}")
    write_blocked = (any(gallery_append_reserved(entry) for entry in reg.get("items") or [])
                     or any(r.get("stop_further_writes") is True for r in image_backfill))
    notice_enrichment = []
    if (shop is not None and not DRY_RUN and not write_blocked
            and (pending_notice or enrich_only or os.environ.get('BACKFILL_DRAFT_NOTICE') == '1')):
        from draft_notice_enrichment import enrich, source_titles
        from types import SimpleNamespace
        notice_shop = SimpleNamespace(read_product=shop.read_notice_product,
            update_description=shop.update_description, update_draft_content=shop.update_draft_content)
        notice_enrichment = enrich(notice_shop, reg, collect_gosi, build_us_label, save_registry,
            pd_nos={p.strip() for p in os.environ.get('ENRICH_PD_NOS', '').split(',') if p.strip()},
            title_overrides=source_titles(ROOT, reg))
        write_blocked = any(r.get('stop_further_writes') for r in notice_enrichment)
    for cat in ([] if enrich_only else CATEGORIES):
        if ONLY and cat[0] not in ONLY:
            continue
        if write_blocked:
            results.append({"category": cat[0], "status": "skipped_prior_write_uncertain",
                            "grade_required": grade_label(cat)})
            continue
        log(f"== {cat[1]} ({cat[0]})")
        current_p, current_entry = None, None
        if any(i.get("date") == today and i.get("category") == cat[0] for i in reg["items"]):
            log("  already registered today for this category -> skip (하루 카테고리별 1개)")
            results.append({"category": cat[0], "status": "skipped_already_today", "grade_required": grade_label(cat),
                            "s_candidates": len(s_ranked(cat))})
            continue
        try:
            rows = s_ranked(cat)
            s_candidate_count = len(rows)
            fallback_mode = False
            # 2026-10-16: 메이크업은 S 가 없으면 실시간 랭킹 대체(비공개 초안)로 넘어간다. 바디는 main 의 카테고리 대체.
            use_ranking = ranking_enabled(cat)
            if not rows and cat[0] != "body" and not use_ranking:
                log("  no canonical S-grade candidate in category")
                results.append({"category": cat[0], "status": "skipped_no_s_grade",
                                "grade_required": grade_label(cat), "s_candidates": 0})
                continue
            excluded = set()
            price_excluded = []
            safety_excluded = []
            ranking_skipped = []
            ranking_rows = None
            ranking_mode = bool(use_ranking and not rows)
            if ranking_mode:
                log("  no canonical S-grade candidate -> makeup realtime ranking fallback (draft only)")
            while True:
                if ranking_mode:
                    if ranking_rows is None:
                        try:
                            ranking_rows = fetch_makeup_ranking()
                            log(f"  ranking: {len(ranking_rows)} products from {RANKING['page_url']}")
                        except Exception as exc:  # noqa: BLE001  랭킹을 못 읽으면 지어내지 않고 사유를 남긴다
                            log(f"  ranking fetch failed: {exc}")
                            ranking_rows = []
                            ranking_skipped.append({"reason": f"ranking_fetch_failed:{str(exc)[:200]}"})
                    p = pick_ranking(cat, shop, names, ids, reg, ranking_rows, excluded, ranking_skipped)
                else:
                    p = pick(cat, shop, names, ids, reg, rows, excluded)
                if not p and cat[0] == "body" and not fallback_mode:
                    fallback_mode = True
                    rows, fallback_reason, _ = body_fallback_rows(reg)
                    if rows:
                        continue
                if not p and use_ranking and not ranking_mode:
                    log("  no eligible S-grade -> makeup realtime ranking fallback (draft only)")
                    ranking_mode = True
                    continue
                if not p:
                    log("  no available, sellable, unregistered candidate")
                    skipped = {"category": cat[0],
                               "status": ("skipped_no_eligible_s_or_ranking" if use_ranking else
                                          "skipped_no_eligible_s_grade" if s_candidate_count else "skipped_no_s_grade"),
                               "grade_required": grade_label(cat), "s_candidates": s_candidate_count,
                               "price_excluded": price_excluded, "safety_excluded": safety_excluded}
                    if fallback_mode:
                        skipped["fallback_reason"] = fallback_reason or "no_eligible_body_category_fallback"
                    if use_ranking:
                        skipped["ranking_skipped"] = ranking_skipped
                    results.append(skipped)
                    break
                # The owner may approve a non-public draft, never safety coverage or publication.
                safety = manufacturer_safety_record(p["pdNo"])
                draft_permission = body_category_draft_approved() if fallback_mode else draft_allowed(p)
                if (fallback_mode and not draft_permission) or (not safety["covered"] and not draft_permission):
                    log(f"  excluded (safety): {p['pdNo']} {clean_name(p['pdNm'])} -> {safety['reason']}")
                    excluded.add(str(p["pdNo"]))
                    safety_excluded.append({"pd_no": str(p["pdNo"]), "reason": safety["reason"]})
                    continue
                # Category fallback adds no metered/unknown-cost copy request.
                ranking_pick = p.get("_source") == RANKING_SOURCE
                copy = fallback_copy(p, cat) if (fallback_mode or ranking_pick) else (gemini_copy(p, cat) or fallback_copy(p, cat))
                title, html = copy
                neutral_title, neutral_html = fallback_copy(p, cat)
                selected_copy, accuracy = product_accuracy.select_copy(
                    {**p, "brand_english": BRAND_EN.get((p.get("brndNm") or "").strip(), "")},
                    {"title": title, "description_html": html},
                    {"title": neutral_title, "description_html": neutral_html}, ROOT)
                title, html = selected_copy["title"], selected_copy["description_html"]
                if already_registered(p, reg, names, ids, title):
                    excluded.add(str(p["pdNo"]))
                    continue
                # 가격을 쓸 수 없는 상품(원가 없음, 가격 근거 없음/낡음/용량 불일치, 무효 가격)만 건너뛰고 다음 후보로 넘어간다.
                # 마진·손익분기 미달은 건너뛰거나 초안으로 돌리지 않는다. 경고로 공개한다 (2026-10-11 사용자 승인).
                krw = int(p["pdPrc"])
                base = jarvis_price(p["pdNo"], clean_name(p["pdNm"]), krw)
                pr = final_prices(p["pdNo"], clean_name(p["pdNm"]), krw, title, base["price_usd"], base.get("evidence"))
                why = price_unfit_reason(krw, pr)
                if why:
                    log(f"  excluded (price evidence/validity): {p['pdNo']} {clean_name(p['pdNm'])} -> {why}")
                    excluded.add(str(p["pdNo"]))
                    price_excluded.append({"pd_no": str(p["pdNo"]), "reason": why})
                    continue
                current_p = p
                break
            if not p:
                continue
            g = p.get("_gosi") or (collect_gosi(p["pdNo"], allow_ai=False) if fallback_mode else collect_gosi(p["pdNo"]))
            label = build_us_label(p["pdNo"], clean_name(p["pdNm"]), g)
            claims_filtered = has_claims(title, html)
            if claims_filtered:  # 효능·의료 표현이 섞이면 사실만 쓴 규칙 기반 문구로 교체
                title, html = fallback_copy(p, cat)
            # The first pass protects pricing inputs. Bind the final base copy
            # again after claim filtering and once actual label quantity exists.
            input_accuracy = accuracy
            selected_copy, accuracy = product_accuracy.select_copy(
                {**p, "brand_english": BRAND_EN.get((p.get("brndNm") or "").strip(), ""),
                 "net_contents": label["label"].get("net_contents") or g.get("volume") or ""},
                {"title": title, "description_html": html},
                {"title": neutral_title, "description_html": neutral_html}, ROOT)
            title, html = selected_copy["title"], selected_copy["description_html"]
            accuracy["input_copy_review"] = input_accuracy
            accuracy["fallback_used"] = bool(accuracy["fallback_used"] or input_accuracy["fallback_used"] or claims_filtered)
            accuracy["scope"] = "recorded_source_consistency_and_exact_base_copy_support_only"
            accuracy["excluded_sections"] = ["us_label", "retailer_source_marker"]
            claims_left = has_claims(title, html)
            html = html + label["html"]
            html += f'<p><small>Source: Daiso Mall item {escape(str(p["pdNo"]))}.</small></p>'
            # Exact source support never grants publication. The owner's
            # current workflow is prepare DRAFT, then owner activates.
            reasons = list(label["reasons"]) + [product_accuracy.HOLD_REASON]
            if pr.get("draft_only"):
                reasons.append("market_price_unverified_cost_based_draft_only")
            if fallback_mode:
                reasons.append("owner_category_fallback_draft_only")
            if p.get("_source") == RANKING_SOURCE:
                # 랭킹 대체는 언제나 비공개 초안이다 (사업주 결정 2026-10-16, config makeup_ranking_fallback).
                reasons.append("ranking_fallback_draft_only")
            if not safety["covered"]:
                reasons.append("safety_evidence_unverified_owner_draft_only")
            public_gate = canonical_public_gate(p["pdNo"])
            reasons.extend(public_gate["reasons"])
            # 용량 교차 검증: 다이소 상품명 / 고시 / 영문 제목 이 서로 맞아야 한다
            sz_name, sz_title = parse_size(clean_name(p["pdNm"])), parse_size(title)
            sz_gosi = parse_size(g.get("volume", ""))
            if sz_name and sz_title and not same_total(sz_name, sz_title, 0.02):
                reasons.append(f"title_volume_mismatch:name={sz_name['total']}{sz_name['base']},title={sz_title['total']}{sz_title['base']}")
            if sz_name and sz_gosi and not (same_total(sz_name, sz_gosi, 0.02)
                                           or (sz_name["base"] == sz_gosi["base"] and abs(sz_name["unit"] - sz_gosi["unit"]) <= 0.02 * sz_name["unit"])):
                reasons.append(f"volume_mismatch:name={sz_name['unit']}x{sz_name['count']},gosi={sz_gosi['total']}")
            if (p.get("brndNm") or "").strip() not in BRAND_EN:
                # 브랜드 영문 표기는 추측하지 않는다. 검증된 표(BRAND_EN)에 없으면 사람이 확인할 때까지 초안.
                reasons.append(f"brand_english_unverified:{(p.get('brndNm') or '').strip()}")
            if claims_left:
                reasons.append("claim_language_review")
            if re.search(r"[가-힣]", title):
                reasons.append("english_title_missing")
            if not g["gosi_ok"]:
                reasons.append("gosi_missing:" + ",".join(g["missing"]))
            imgs = prepare_images(p, shop, title=title)
            if not imgs["source_urls"] or (shop is not None and not DRY_RUN and not imgs["resource_urls"]):
                reasons.append("no_usable_product_images")
            if shop is not None and not DRY_RUN and not pub:
                reasons.append("online_store_publication_unavailable")
            images = imgs["resource_urls"] if (shop is not None and not DRY_RUN) else imgs["source_urls"]
            bo = pr["pack"]
            variants = [{"name": "Single (1 pc)", "price": pr["single"]["price_usd"], "sku": f"DS-{p['pdNo']}-1"}]
            if bo["ok"]:
                variants.append(
                    {
                        "name": bundle_variant_name(pr["single"]["price_usd"], bo["price_usd"]),
                        "price": bo["price_usd"],
                        "compare_at": bo["compare_at_usd"],
                        "sku": f"DS-{p['pdNo']}-2",
                    }
                )
            else:
                reasons.append("bundle_price_invalid")
            profit_warnings = list(pr.get("profit_warnings") or [])
            if profit_warnings:
                log(f"  PROFITABILITY WARNING (registered anyway, price evidence ok): {profit_warnings}")
            item = {
                "title": title,
                "description_html": html,
                "vendor": BRAND_EN.get((p.get("brndNm") or "").strip(), p.get("brndNm") or "Daiso"),
                "product_type": cat[3],
                "tags": [cat[0], "daiso-daily", f"daiso-pd-{p['pdNo']}", "k-beauty"]
                + (["owner-body-shower-category-fallback", "draft-only-category-fallback"] if fallback_mode else [])
                + (["makeup-realtime-ranking-fallback", "draft-only-ranking-fallback"] if p.get("_source") == RANKING_SOURCE else [])
                + ([f"jarvis-grade-{p['_grade'].lower()}"] if p.get("_grade") not in (None, "-") else []),
                "images": images,
                # 이미지마다 대체텍스트를 따로 둔다. 1084687 수작업 초안은 11장 alt 가 모두 비어 있었다.
                "image_alts": list(imgs.get("alts") or [])[: len(images)],
                "category": TAXONOMY[cat[0]],
                "variants": variants,
                "price_usd": pr["single"]["price_usd"],
                # 영문 제목·고시 4항목·신규 이미지 중 하나라도 없으면 공개하지 않고 초안으로 둔다.
                "status": "DRAFT" if reasons else "ACTIVE",
            }
            log(f"  pick: {p['pdNo']} {clean_name(p['pdNm'])} | {krw} KRW -> ${item['price_usd']:.2f} | {title}")
            rec = {
                "category": cat[0],
                "grade_required": grade_label(cat), "grade": p["_grade"], "s_candidates": s_candidate_count,
                "selection_source": p.get("_source"),
                "selection_provenance": p.get("_priority") if fallback_mode else None,
                "priority": p.get("_priority"),
                "source": p.get("_source"),
                **({"ranking": p["_ranking"]} if p.get("_ranking") else {}),
                "daiso_pdNo": p["pdNo"],
                "daiso_name": clean_name(p["pdNm"]),
                "daiso_url": DAISO_ITEM + p["pdNo"],
                "krw": krw,
                "usd": item["price_usd"],
                "pricing": pr,
                "price_evidence": pr.get("evidence"),
                "profitability_warnings": profit_warnings,
                "bundle": bo,
                "images_skipped": imgs["skipped"],
                "image_localization": imgs.get("localization"),
                "gallery_complete": False, "gallery_status": "review_required",
                "gosi": {k: v for k, v in g.items() if k != "ingredients"} | {"ingredients_chars": len(g.get("ingredients", ""))},
                "us_label": label["label"],
                "draft_reasons": reasons,
                "product_accuracy": accuracy,
                "canonical_public_gate": public_gate,
                "title": title,
                "images": images,
                "description_html": html,
            }
            if DRY_RUN or shop is None:
                rec["status"] = "dry_run"
            else:
                # Re-read the entire catalogue just before writing; the daily cap and duplicate checks are unconditional.
                safety = manufacturer_safety_record(p["pdNo"])
                draft_approved = body_category_draft_approved() if fallback_mode else draft_allowed(p)
                if fallback_mode and not draft_approved:
                    rec["status"] = "skipped_body_category_fallback_invalidated"
                    rec["fallback_reason"] = "owner_category_fallback_approval_missing_or_revoked"
                    results.append(rec)
                    continue
                if not safety["covered"] and not draft_approved:
                    rec["status"] = "blocked_manufacturer_safety_record_missing"
                    rec["safety_record"] = safety
                    results.append(rec)
                    continue
                if not safety["covered"]:
                    if "safety_evidence_unverified_owner_draft_only" not in reasons:
                        reasons.append("safety_evidence_unverified_owner_draft_only")
                    item["status"] = "DRAFT"
                    rec["owner_approved_nonpublic_draft"] = True
                    rec["safety_record"] = safety
                names, ids = shop_keys(shop.existing_products())
                if already_registered(p, reg, names, ids, title) or shop.exists(p["pdNo"]):
                    rec["status"] = "skipped_duplicate_at_create"
                    results.append(rec)
                    continue
                fallback_queue = None
                if fallback_mode:
                    fresh_rows, invalid_reason, fallback_queue = body_fallback_rows(reg)
                    fresh_row = next((r for r in fresh_rows if str(r["pd_no"]) == str(p["pdNo"])), None)
                    if invalid_reason or not fresh_row:
                        rec["status"] = "skipped_body_category_fallback_invalidated"
                        rec["fallback_reason"] = invalid_reason or "body_category_source_membership_missing"
                        results.append(rec)
                        continue
                    p["_priority"] = fresh_row["_priority"]
                    rec["selection_provenance"] = p["_priority"]
                    rec["priority"] = p["_priority"]
                    item["status"] = "DRAFT"
                    if "owner_category_fallback_draft_only" not in reasons:
                        reasons.append("owner_category_fallback_draft_only")
                cmpd = pr.get("shop_compare") or {}
                entry = {"pd_no": str(p["pdNo"]), "family": family_key(clean_name(p["pdNm"])),
                         "name_kr": clean_name(p["pdNm"]), "title": title, "category": cat[0],
                         "date": today, "status": "create_reserved", "krw": krw,
                         "single_usd": pr["single"]["price_usd"],
                         "single_margin_pct": pr["single"]["margin_pct"],
                         "pack_usd": pr["pack"]["price_usd"] if pr["pack"]["ok"] else None,
                         "pack_margin_pct": pr["pack"]["margin_pct"] if pr["pack"]["ok"] else None,
                         "size": parse_size(clean_name(p["pdNm"])), "images": len(images),
                         "price_basis": pr["basis"], "shop_com_lowest_usd": (cmpd.get("lowest_usd") if (pr.get("evidence") or {}).get("source") == "shop_com_live_comparable" else None),
                         "profitability_warnings": profit_warnings,
                         "priority": p.get("_priority"),
                         "price_evidence_source": (pr.get("evidence") or {}).get("source"),
                         "price_claim": ((pr.get("evidence") or {}).get("detail") or {}).get("price_claim"),
                         "draft_reasons": reasons, "grade": p["_grade"], "source": p.get("_source"),
                         "s_candidates": s_candidate_count, "selection_source": p.get("_source"),
                         "selection_provenance": p.get("_priority") if fallback_mode else None,
                         **({"ranking_display_rank": p["_ranking"]["display_rank"]} if p.get("_ranking") else {})}
                pos = price_position(entry.get("single_usd"), entry.get("shop_com_lowest_usd"), entry.get("single_margin_pct"))
                entry["price_position"], entry["strategy_hints"] = pos["position"], pos["hints"]
                try:
                    log_price_position(entry, pos)
                except OSError as exc:
                    log(f"  price log skipped: {exc}")
                if fallback_mode:
                    reg[body_fallback.QUEUE_KEY] = fallback_queue
                reg["items"].append(entry)
                current_entry = entry
                save_registry(reg)  # unknown network outcome must remain a durable duplicate block

                def on_created(prod):
                    entry["shopify_id"], entry["handle"] = prod["id"], prod["handle"]
                    entry["status"] = "created_unverified"
                    save_registry(reg)

                prod = shop.create(item, on_created)
                rec["shopify_id"] = prod["id"]
                rec["handle"] = prod["handle"]
                rec["url"] = f"https://{shop.store}/products/{prod['handle']}"
                # A create is always DRAFT. Only verified media, variants, and legal gates can go live.
                try:
                    verified = verify_product(shop, prod["id"], item, pub)
                    rec["verified_variants"] = len(verified["variants"]["nodes"])
                    rec["verified_images"] = len(verified["media"]["nodes"])
                    rec["verified_status"] = verified["status"]
                    rec["published_on_online_store"] = bool(verified["publishedOnPublication"])
                except RuntimeError as exc:
                    reasons.append(f"readback_not_ready:{exc}")
                    rec["verification_error"] = str(exc)
                # Source files can change during image/variant writes; revalidate at
                # the actual public-sale boundary rather than trusting an earlier snapshot.
                public_gate = canonical_public_gate(p["pdNo"])
                rec["canonical_public_gate"] = public_gate
                safety = manufacturer_safety_record(p["pdNo"])
                rec["safety_record"] = safety
                if not safety["covered"] and safety["reason"] not in reasons:
                    reasons.append(safety["reason"])
                for gate_reason in public_gate["reasons"]:
                    if gate_reason not in reasons:
                        reasons.append(gate_reason)
                if fallback_mode:
                    item["status"] = "DRAFT"
                    if "owner_category_fallback_draft_only" not in reasons:
                        reasons.append("owner_category_fallback_draft_only")
                if not reasons and not fallback_mode:
                    try:
                        shop.set_status(prod["id"], "ACTIVE")
                        shop.publish(prod["id"], pub)
                        live = verify_product(shop, prod["id"], item, pub, published=True)
                        rec["verified_status"] = live["status"]
                        rec["published_on_online_store"] = bool(live["publishedOnPublication"])
                        rec["channel_publish"] = shop.publish_channels(prod["id"], pub)
                        log(f"  channels: {rec['channel_publish']}")
                    except Exception:
                        # Fail closed even if publish/read-back fails after status activation.
                        shop.set_status(prod["id"], "DRAFT")
                        raise
                entry["status"] = "ACTIVE" if not reasons else "DRAFT"
                entry["draft_reasons"] = reasons
                save_registry(reg)
                rec["registry_recorded"] = True
                rec["status"] = "created" if not reasons else "created_draft"
                names.add(title_key(title))
                ids.add(str(p["pdNo"]))
            results.append(rec)
        except Exception as exc:  # keep going so one category failure doesn't block the others
            failures += 1
            log(f"  FAILED: {exc}")
            failed = {"category": cat[0], "status": "failed", "grade_required": grade_label(cat), "error": str(exc)[:500]}
            if current_p is not None:
                failed["daiso_pdNo"] = current_p["pdNo"]
            if current_entry is not None:
                failed["registry_status"] = current_entry["status"]
                if current_entry.get("shopify_id"):
                    failed["shopify_id"] = current_entry["shopify_id"]
            results.append(failed)
            # Once a reservation or mutation was attempted, its remote outcome can
            # be unknown. Do not create any more categories in this run.
            if current_entry is not None:
                write_blocked = True

    out = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": DRY_RUN,
        "banner_backfill": backfill,
        "draft_image_backfill": image_backfill,
        "draft_notice_enrichment": notice_enrichment,
        "quarantine_blocked_public": quarantined,
        "results": results,
    }
    os.makedirs("out", exist_ok=True)
    with open("out/daiso_daily_beauty_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## 다이소 오늘의 뷰티 추천 -> Shopify 등록\n\n")
            if notice_enrichment:
                f.write('### 기존 초안 고시 보완 (비공개 유지)\n\n')
                for item in notice_enrichment:
                    f.write(f"- {item['pd_no']}: {item['status']} | {item['shopify_id']}\n")
                f.write('\n')
            f.write("| 카테고리 | 상태 | 상품 | 가격 | 링크 | 수익성 경고 |\n|---|---|---|---|---|---|\n")
            for r in results:
                f.write(
                    f"| {r['category']} | {r['status']} | {r.get('title', r.get('error', ''))} | "
                    f"{('$%.2f' % r['usd']) if 'usd' in r else ''} | {r.get('url', r.get('daiso_url', ''))} | "
                    f"{'; '.join(r.get('profitability_warnings') or []) or '-'} |\n"
                )
    log(json.dumps(out, ensure_ascii=False, indent=2))
    notice_failed = any(r.get('stop_further_writes') for r in notice_enrichment)
    return 1 if failures or notice_failed else 0


if __name__ == "__main__":
    sys.exit(main())
