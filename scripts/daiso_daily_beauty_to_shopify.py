#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS LUNA - 정본 S등급 다이소 뷰티 후보 -> Shopify 일일 등록
==========================================================================

매일 오전 10시(KST)에 GitHub Actions 가 실행한다.

흐름
----
1. 정본 채점표에서 S등급만 읽고 스킨케어 / 메이크업 / 바디케어 각 최대 1개를 고른다.
   해당 카테고리에 S등급이 없으면 이유와 후보 수를 남기고 건너뛴다.
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
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import base64
import tempfile
import gate_signature
from datetime import datetime, timezone
from pathlib import Path

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

    def update_description(self, product_id, description_html):
        d = self.gql("""mutation($p:ProductUpdateInput!){productUpdate(product:$p){
          product{id} userErrors{field message}}}""",
          {"p": {"id": product_id, "descriptionHtml": description_html}})["productUpdate"]
        if d["userErrors"] or not d.get("product") or d["product"]["id"] != product_id:
            raise RuntimeError(f"description update: {d.get('userErrors')}")

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

    def online_store_publication(self):
        d = self.gql("{publications(first:20){nodes{id name}}}")
        for n in d["publications"]["nodes"]:
            if n["name"].lower().startswith("online store") or "온라인" in n["name"]:
                return n["id"]
        return None

    def upload_jpeg(self, data, filename):
        """Shopify staged upload (PRODUCT_IMAGE). 업로드 후 productCreate 의 originalSource 로 쓸 resourceUrl 을 돌려준다."""
        d = self.gql(
            """
mutation($i:[StagedUploadInput!]!){
  stagedUploadsCreate(input:$i){stagedTargets{url resourceUrl parameters{name value}} userErrors{field message}}
}""",
            {"i": [{"resource": "PRODUCT_IMAGE", "filename": filename, "mimeType": "image/jpeg", "httpMethod": "POST"}]},
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
            f"Content-Type: image/jpeg\r\n\r\n".encode()
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
                    {"originalSource": u, "alt": item["title"], "mediaContentType": "IMAGE"}
                    for u in item["images"]
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
        "not in the facts. Never use words like treat, cure, repair, anti-aging, wrinkle, whitening, acne, FDA, clinical, dermatologist, safe. Return JSON: {\"title\":\"...\",\"description\":\"...\"}.\n"
        f"FACTS: {json.dumps(facts, ensure_ascii=False)}"
    )
    models = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-lite-latest", "gemini-flash-latest") if m]
    status, body = 0, {}
    for attempt in range(4):  # 무료 키는 429/503 이 잦다. 모델을 바꿔가며 최대 4번, 간격을 늘려 재시도한다.
        model = models[attempt % len(models)]
        status, body = http_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
            },
        )
        if status == 200:
            break
        log(f"  gemini attempt {attempt + 1} ({model}): HTTP {status}")
        time.sleep(15 * (attempt + 1))
    if status != 200:
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
TARGET_MARGIN = float(os.environ.get("TARGET_MARGIN", "0.40"))  # pricing_model.py 가 지키는 마진 40%
DUTY_MODE = os.environ.get("DUTY_MODE", "ddu")


def jarvis_price(pd_no, name, krw):
    """scripts/pricing_model.py 의 analyze() 로 착지원가를 구하고 마진 40% 가 되는 가격을 잡는다.

    착지원가 = 상품원가 + 우체국 소형포장물 미국행 배송비 + 관세 15% (ddu 기준)
    수수료   = Shopify 국제 7.4%
    판매가   = 착지원가 / (1 - 수수료율 - 목표마진), 0.99 로 올림.
    상품별 미국 실판매가가 data/serpapi_market.json 에 있으면 그 중앙값 95% 를 상한 기준으로 함께 본다.
    """
    import pricing_model as pm  # noqa: PLC0415

    # 이미 JARVIS 가 산출한 권장가가 있으면 그것이 우선이다 (상품별 미국 실판매가 기준).
    try:
        offers = json.loads((ROOT / "data/pricing_model.json").read_text(encoding="utf-8"))["offers_by_product"]["single"]
        hit = next((o for o in offers if str(o.get("pd_no")) == str(pd_no) and not o.get("register_blocked")), None)
    except (OSError, KeyError, json.JSONDecodeError):
        hit = None
    if hit:
        return {
            "price_usd": float(hit["price_usd"]),
            "landed_cost_usd": hit["landed_cost_total_usd"],
            "fee_usd": hit["fee_usd"],
            "net_profit_usd": hit["net_profit_usd"],
            "margin_pct": hit["margin_pct"],
            "basis": "data/pricing_model.json 권장가 (" + str(hit.get("market_price_source")) + ")",
        }

    st = json.loads((ROOT / "data/daiso_real/collection_status.json").read_text(encoding="utf-8"))
    rate = float((st.get("fx") or {}).get("usd_to_krw") or 0)
    if not rate:
        raise RuntimeError("환율이 없어 가격을 계산할 수 없다 (임의 환율 사용 금지)")
    market = pm.market_benchmark() or {"p25": 0, "median": 0}
    row = pm.analyze({"pd_no": pd_no, "name": name, "price_krw": krw}, rate, 1, market, DUTY_MODE)
    landed = row["landed_cost_usd"]
    raw = landed / (1 - pm.PAY_RATE - TARGET_MARGIN)
    price = pm.psych_price(raw)
    fee = price * pm.PAY_RATE
    net = price - landed - fee
    return {
        "price_usd": round(price, 2),
        "landed_cost_usd": landed,
        "shipping_usd": row["shipping_unit_usd"],
        "tariff_usd": row["tariff_usd"],
        "fee_usd": round(fee, 2),
        "net_profit_usd": round(net, 2),
        "margin_pct": round(net / price * 100, 1),
        "breakeven_usd": row["breakeven_usd"],
        "weight_g": row["weight_g_est"],
        "weight_source": row["weight_source"],
        "fx": rate,
        "duty_mode": DUTY_MODE,
    }


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


def collect_gosi(pd_no):
    try:
        return _collect_gosi(pd_no)
    except Exception as exc:  # noqa: BLE001  고시 수집이 어떻게 실패해도 작업은 계속한다 (초안으로 남는다)
        log(f"  gosi failed, continuing as draft: {exc}")
        return {"gosi_ok": False, "missing": list(NEED), "_source": "error"}


def _collect_gosi(pd_no):
    """고시 4항목(성분·용량·제조사·제조국)을 모은다. 못 채우면 빈 값으로 둔다. 지어내지 않는다."""
    g = {}
    # 0) 이미 수집된 JARVIS 정본 (data/gosi.json)
    try:
        items = json.loads((ROOT / "data/gosi.json").read_text(encoding="utf-8-sig")).get("items") or {}
        if isinstance(items, dict) and isinstance(items.get(str(pd_no)), dict):
            g.update({k: _clean(v) for k, v in items[str(pd_no)].items() if k in FIELD.values() and _clean(v)})
            g["_source"] = "jarvis data/gosi.json"
    except (OSError, json.JSONDecodeError):
        pass
    # 1) 다이소 API 텍스트
    for k, v in gosi_from_api(pd_no).items():
        g.setdefault(k, v)
    # 2) 상세 이미지 판독 (표는 상세 이미지 아래쪽에 있다)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key and any(not g.get(k) for k in NEED):
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
        inci, missing, fixed, review = sg.to_inci(g.get("ingredients", ""), resolver)
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
    mk = _clean(g.get("maker"))
    for ko, en in ROLE_EN:
        mk = mk.replace(ko, en)
    if re.search(r"[가-힣]{2,}", re.sub(r"\([^)]*\)|주식회사|\(주\)|㈜", "", mk)) or mk:
        label["maker"] = mk  # 회사명은 고유명사라 번역하지 않고 원문 그대로 둔다
    if not g.get("maker"):
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
    html = "<h4>Product information</h4><ul>" + "".join(f"<li><strong>{k}:</strong> {v}</li>" for k, v in li) + "</ul>"
    return {"html": html, "reasons": reasons, "label": {k: v for k, v in label.items() if k != "ingredients_inci"}}



# ---------------------------------------------------------------- Shopify 표준 카테고리 (택소노미)

# 설명란 맨 위에 항상 넣는 문구 (사용자 지시 2026-10-10: "한국 여성들이 즐겨찾는 제품")
TAGLINE_HTML = "<p><strong>한국여성들이 즐겨찾는 제품</strong></p>"

TAXONOMY = {
    "skincare": "gid://shopify/TaxonomyCategory/hb-3-2-9",  # Health & Beauty > Personal Care > Cosmetics > Skin Care
    "makeup": "gid://shopify/TaxonomyCategory/hb-3-2-6",  # ... > Makeup
    "body": "gid://shopify/TaxonomyCategory/hb-3-2-1",  # ... > Bath & Body
}

# ---------------------------------------------------------------- 1개 / 1+1(2개 세트) - JARVIS 판매 구성 (pricing_model.py)

BUNDLE_QTY = 2
BUNDLE_DISCOUNT = 0.15  # pricing_model.BUNDLE_DISCOUNT 와 같은 값. 무료배송은 스토어 배송 설정에서 따로 건다.


def bundle_offer(pd_no, name, krw, single_price):
    """JARVIS 권장 세트가(data/pricing_model.json bundle)가 있으면 그것을, 없으면 단품가 x2 x (1-15%) 로 잡고 마진을 검증한다."""
    import pricing_model as pm  # noqa: PLC0415

    price = None
    try:
        offers = json.loads((ROOT / "data/pricing_model.json").read_text(encoding="utf-8"))["offers_by_product"]["bundle"]
        hit = next((o for o in offers if str(o.get("pd_no")) == str(pd_no) and not o.get("register_blocked")), None)
        if hit:
            price = float(hit["price_usd"])
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    st = json.loads((ROOT / "data/daiso_real/collection_status.json").read_text(encoding="utf-8"))
    rate = float((st.get("fx") or {}).get("usd_to_krw") or 0)
    market = pm.market_benchmark() or {"p25": 0, "median": 0}
    row = pm.analyze({"pd_no": pd_no, "name": name, "price_krw": krw}, rate, BUNDLE_QTY, market, DUTY_MODE)
    if price is None:
        price = pm.psych_price(single_price * BUNDLE_QTY * (1 - BUNDLE_DISCOUNT))
    landed = row["landed_cost_usd"] * BUNDLE_QTY  # 2개를 한 상자로 보내 배송비를 나눈 착지원가
    fee = price * pm.PAY_RATE
    net = price - landed - fee
    return {
        "price_usd": round(price, 2),
        "compare_at_usd": round(single_price * BUNDLE_QTY, 2),
        "landed_cost_usd": round(landed, 2),
        "net_profit_usd": round(net, 2),
        "margin_pct": round(net / price * 100, 1),
        "ok": net > 0 and price > row["breakeven_usd"] * BUNDLE_QTY,
    }


# ---------------------------------------------------------------- 이미지: 다이소 이미지 전부 + 사람 얼굴 사진 제외 + 정사각 2048

def prepare_images(p, shop):
    """다이소 상품 이미지를 모두 받아 사람 얼굴이 있는 것만 뺀다(OpenCV YuNet). 대표컷은 깔끔한 제품 컷을 맨 앞으로.
    모두 2048x2048 정사각 JPEG 로 바꿔 Shopify 에 올린다. 판독 도구가 실패한 이미지는 쓰지 않는다."""
    import daiso_images as di  # noqa: PLC0415

    urls = [DAISO_CDN + u for u in (p.get("pdImgUrlList") or [p["pdImgUrl"]])]
    blobs = []
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                blobs.append((u, r.read()))
        except Exception as exc:  # noqa: BLE001
            log(f"  image download failed: {exc}")
    kept, dropped = di.select_images(blobs)
    resource_urls = []
    if shop is not None and not DRY_RUN:
        for n, (u, data) in enumerate(kept, 1):
            resource_urls.append(shop.upload_jpeg(di.to_square_jpeg(data), f"daiso-{p['pdNo']}-{n}.jpg"))
    log(f"  images: total {len(urls)}, kept {len(kept)}, dropped {len(dropped)} {[d['reason'] for d in dropped]}")
    return {"source_urls": [u for u, _ in kept], "resource_urls": resource_urls, "skipped": dropped,
            "total": len(urls)}



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

MIN_MARGIN = float(os.environ.get("MIN_MARGIN", "0.30"))  # 이 마진 밑으로는 절대 팔지 않는다 (바닥)
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


def final_prices(pd_no, name_kr, krw, title_en, base_price):
    """판매가 결정.
    바닥(floor) = 착지원가(원가+우체국 배송+관세 15%) / (1 - 결제수수료 7.4% - 최소마진)  -> 이 밑으로는 절대 안 판다.
    shop.com 에 같은 상품이 있으면 그 최저가보다 약간 낮게 맞추되 바닥 아래로는 내리지 않는다. 없으면 JARVIS 권장가(base_price)."""
    import math  # noqa: PLC0415

    landed1, pm, row1 = _landed(pd_no, name_kr, krw, 1)
    landed2, _, row2 = _landed(pd_no, name_kr, krw, BUNDLE_QTY)
    fee = pm.PAY_RATE
    # 무게를 실측하지 못하고 추정한 상품은 우체국 요금 구간이 틀릴 수 있어 마진을 5%p 더 확보한다
    estimated = row1.get("weight_source") == "estimated"
    margin_floor = MIN_MARGIN + (0.05 if estimated else 0.0)

    def up(v):  # 바닥 이상의 .99
        return math.floor(v) + 0.99 if math.floor(v) + 0.99 >= v else math.floor(v) + 1.99

    def down(v):  # 값보다 낮은 .99
        return math.floor(v - 0.01) - 0.01 if v >= 2 else v

    floor1 = up(landed1 / (1 - fee - margin_floor))
    cmp_ = shop_compare(title_en)
    low = cmp_.get("lowest_usd")
    if low:
        target = max(down(low) if down(low) < low else low - 0.5, 0)
        single, basis = max(floor1, round(target, 2)), "shop.com 최저가보다 낮게 (바닥 마진 보장)"
        if low < floor1:
            basis = "shop.com 최저가가 바닥보다 낮아 바닥가로 설정"
    else:
        single, basis = max(floor1, base_price), "shop.com 비교 불가 -> JARVIS 권장가 (바닥 마진 보장)"
    single = round(single, 2)

    floor2 = up(landed2 / (1 - fee - margin_floor))
    pack = max(pm.psych_price(single * BUNDLE_QTY * (1 - BUNDLE_DISCOUNT)), floor2)
    pack = round(pack, 2)

    def margin(price, landed):
        net = price - landed - price * fee
        return round(net, 2), round(net / price * 100, 1)

    n1, m1 = margin(single, landed1)
    n2, m2 = margin(pack, landed2)
    return {
        "single": {"price_usd": single, "landed_cost_usd": round(landed1, 2), "net_profit_usd": n1, "margin_pct": m1, "floor_usd": floor1},
        "pack": {"price_usd": pack, "compare_at_usd": round(single * BUNDLE_QTY, 2), "landed_cost_usd": round(landed2, 2),
                 "net_profit_usd": n2, "margin_pct": m2, "floor_usd": floor2, "ok": pack < single * BUNDLE_QTY and n2 > 0},
        "basis": basis, "shop_compare": cmp_, "min_margin": margin_floor,
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
        os.replace(name, REGISTRY)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


# ---------------------------------------------------------------- Main


# JARVIS 채점(shopify_demand_score.json)의 버킷을 Shopify 3개 카테고리로 묶는다.
BUCKETS = {
    "skincare": {"스킨케어", "마스크팩", "클렌징", "선케어"},
    "makeup": {"메이크업"},
    "body": {"바디케어"},
}
<<<<<<< Updated upstream
GRADE_ORDER = {"S": 0}
=======
GRADE_ORDER = {"S": 0, "A": 1}  # B 이하는 쓰지 않는다
# 화장품이 아닌 생활·소품류는 점수가 높아도 뷰티 스토어에 올리지 않는다
NON_COSMETIC = re.compile(r"슬리퍼|양말|신발|전동|기기|제거기|브러[시쉬]|퍼프|파우치|케이스|가위|핀셋|거울|수건|타월|스펀지|면봉|도구|세트\s*케이스")
>>>>>>> Stashed changes


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
    p["brndNm"] = str(hit.get("brndNm") or info.get("brndNm") or "").split(">")[0].strip()
    p["onlStckQy"] = info.get("stckQy") or hit.get("ONL_STCK_QY") or 0
    p["pdPrc"] = str(info.get("pdPrc") or hit.get("pdPrc") or "0")
    p["exhYn"] = info.get("exhYn") or "Y"
    p["pdImgUrlList"] = hit.get("pdImgUrlList") or hit.get("PD_IMG_URL_LIST") or ([hit["pdImgUrl"]] if hit.get("pdImgUrl") else [])
    return p


def s_ranked(cat):
<<<<<<< Updated upstream
    """Canonical S-grade rows only; missing or invalid source is an error, not permission to improvise."""
    d = json.loads((ROOT / "data/daiso_real/shopify_demand_score.json").read_text(encoding="utf-8-sig"))
    if not isinstance(d.get("all_scored"), list):
        raise ValueError("Canonical grade list unavailable")
    rows = [r for r in d["all_scored"] if r.get("bucket") in BUCKETS[cat[0]] and r.get("grade") == "S"]
    rows.sort(key=lambda r: -float(r.get("shopify_score") or 0))
=======
    """JARVIS 점수표에서 이 카테고리 후보를 S -> A -> B, 점수 높은 순으로. C 등급은 쓰지 않는다."""
    try:
        d = json.loads((ROOT / "data/daiso_real/shopify_demand_score.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = [r for r in d.get("all_scored", []) if r.get("bucket") in BUCKETS[cat[0]] and r.get("grade") in GRADE_ORDER
            and not NON_COSMETIC.search(r.get("name") or "")]
    rows.sort(key=lambda r: (GRADE_ORDER[r["grade"]], -float(r.get("shopify_score") or 0)))
>>>>>>> Stashed changes
    return rows


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
<<<<<<< Updated upstream
        p = daiso_lookup(pd_no)
        if p and sellable(p) and not already_registered(p, reg, names, ids):
            p["_grade"], p["_source"], p["_score"] = "S", "jarvis_s_list", row.get("shopify_score")
=======
        p = daiso_lookup(row["pd_no"])
        if p and sellable(p) and fresh(p):
            p["_grade"], p["_source"], p["_score"] = row["grade"], "jarvis_s_list", row.get("shopify_score")
            log(f"  source: JARVIS {row['grade']}등급 (score {row.get('shopify_score')})")
            return p
    # 2) S/A 후보가 모두 소진되면 다이소 '오늘의 뷰티 추천'
    items = [p for p in fetch_daiso(cat[1], cat[2]) if sellable(p) and not NON_COSMETIC.search(p.get("pdNm") or "")]
    items.sort(key=score, reverse=True)
    for p in items:
        if fresh(p):
            p["_grade"], p["_source"], p["_score"] = "-", "daiso_today", None
            log("  source: 다이소 오늘의 뷰티 추천 (S/A/B 후보 없음)")
>>>>>>> Stashed changes
            return p
    return None


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
    """Backfill text only on known Daiso products; do not touch status or publication."""
    if not publication_id:
        raise RuntimeError("Cannot verify publication state for banner backfill")
    registered = {str(i.get("shopify_id")) for i in registry["items"] if i.get("shopify_id")}
    registered_pd = {str(i["shopify_id"]): str(i["pd_no"]) for i in registry["items"]
                     if i.get("shopify_id") and i.get("pd_no")}
    results = []

    def target(product):
        tags = product.get("tags") or []
        return (str(product.get("id")) in registered or
                any(str(tag).casefold() == "daiso-daily" or
                    re.fullmatch(r"daiso-pd-\d+", str(tag), re.I) for tag in tags))

    for row in products:
        if not target(row):
            continue
        before = shop.read_product(row["id"], publication_id)
        if not before or before["id"] != row["id"]:
            raise RuntimeError(f"Banner backfill source read-back missing: {row['id']}")
        if not target(before):
            results.append({"shopify_id": row["id"], "status": "skipped_no_longer_target"})
            continue
        html = before.get("descriptionHtml") or ""
        pd_no = registered_pd.get(str(row["id"]))
        if not pd_no:
            for tag in before.get("tags") or []:
                match = re.fullmatch(r"daiso-pd-(\d+)", str(tag), re.I)
                if match:
                    pd_no = match[1]
                    break
        warning = None
        if pd_no and (before.get("status") == "ACTIVE" or before.get("publishedOnPublication")):
            public_gate = canonical_public_gate(pd_no)
            if not public_gate["public_ready"]:
                warning = public_gate["reasons"]
        if html.startswith(TAGLINE_HTML):
            result = {"shopify_id": row["id"], "status": "already_prefixed"}
            if warning:
                result["existing_public_gate_warning"] = warning
            results.append(result)
            continue
        expected = TAGLINE_HTML + html
        shop.update_description(row["id"], expected)
        after = shop.read_product(row["id"], publication_id)
        if not after or after.get("descriptionHtml") != expected or any(
            after.get(k) != before.get(k) for k in
            ("id", "title", "tags", "status", "publishedOnPublication")):
            raise RuntimeError(f"Banner backfill read-back/state mismatch: {row['id']}")
        result = {"shopify_id": row["id"], "status": "prefixed",
                  "verified_status": after["status"],
                  "published_on_online_store": bool(after["publishedOnPublication"])}
        if warning:
            result["existing_public_gate_warning"] = warning
        results.append(result)
    return results


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


def main():
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
    if shop is not None and not DRY_RUN and QUARANTINE_BLOCKED_PUBLIC:
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
    if shop is not None and not DRY_RUN and BACKFILL_BANNER:
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
    write_blocked = False
    for cat in CATEGORIES:
        if ONLY and cat[0] not in ONLY:
            continue
        if write_blocked:
            results.append({"category": cat[0], "status": "skipped_prior_write_uncertain",
                            "grade_required": "S"})
            continue
        log(f"== {cat[1]} ({cat[0]})")
        current_p, current_entry = None, None
        if any(i.get("date") == today and i.get("category") == cat[0] for i in reg["items"]):
            log("  already registered today for this category -> skip (하루 카테고리별 1개)")
            results.append({"category": cat[0], "status": "skipped_already_today", "grade_required": "S",
                            "s_candidates": len(s_ranked(cat))})
            continue
        try:
            rows = s_ranked(cat)
            if not rows:
                log("  no canonical S-grade candidate in category")
                results.append({"category": cat[0], "status": "skipped_no_s_grade",
                                "grade_required": "S", "s_candidates": 0})
                continue
            excluded = set()
            while True:
                p = pick(cat, shop, names, ids, reg, rows, excluded)
                if not p:
                    log("  no available, sellable, unregistered S-grade candidate")
                    results.append({"category": cat[0], "status": "skipped_no_eligible_s_grade",
                                    "grade_required": "S", "s_candidates": len(rows)})
                    break
                copy = gemini_copy(p, cat) or fallback_copy(p, cat)
                title, html = copy
                if not already_registered(p, reg, names, ids, title):
                    current_p = p
                    break
                excluded.add(str(p["pdNo"]))
            if not p:
                continue
            krw = int(p["pdPrc"])
            base = jarvis_price(p["pdNo"], clean_name(p["pdNm"]), krw)
            pr = final_prices(p["pdNo"], clean_name(p["pdNm"]), krw, title, base["price_usd"])
            g = collect_gosi(p["pdNo"])
            label = build_us_label(p["pdNo"], clean_name(p["pdNm"]), g)
            if has_claims(title, html):  # 효능·의료 표현이 섞이면 사실만 쓴 규칙 기반 문구로 교체
                title, html = fallback_copy(p, cat)
            claims_left = has_claims(title, html)
            html = TAGLINE_HTML + html + label["html"]
            html += f'<p><small>Source: Daiso Mall item {p["pdNo"]}.</small></p>'
            reasons = list(label["reasons"])
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
            imgs = prepare_images(p, shop)
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
                        "name": "2-Pack (Save 15%)",
                        "price": bo["price_usd"],
                        "compare_at": bo["compare_at_usd"],
                        "sku": f"DS-{p['pdNo']}-2",
                    }
                )
            else:
                reasons.append("bundle_margin_not_ok")
            item = {
                "title": title,
                "description_html": html,
                "vendor": BRAND_EN.get((p.get("brndNm") or "").strip(), p.get("brndNm") or "Daiso"),
                "product_type": cat[3],
                "tags": [cat[0], "daiso-daily", f"daiso-pd-{p['pdNo']}", "k-beauty"]
                + ([f"jarvis-grade-{p['_grade'].lower()}"] if p.get("_grade") not in (None, "-") else []),
                "images": images,
                "category": TAXONOMY[cat[0]],
                "variants": variants,
                "price_usd": pr["single"]["price_usd"],
                # 영문 제목·고시 4항목·신규 이미지 중 하나라도 없으면 공개하지 않고 초안으로 둔다.
                "status": "DRAFT" if reasons else "ACTIVE",
            }
            log(f"  pick: {p['pdNo']} {clean_name(p['pdNm'])} | {krw} KRW -> ${item['price_usd']:.2f} | {title}")
            rec = {
                "category": cat[0],
                "grade_required": "S", "grade": p["_grade"], "s_candidates": len(rows),
                "daiso_pdNo": p["pdNo"],
                "daiso_name": clean_name(p["pdNm"]),
                "daiso_url": DAISO_ITEM + p["pdNo"],
                "krw": krw,
                "usd": item["price_usd"],
                "pricing": pr,
                "bundle": bo,
                "images_skipped": imgs["skipped"],
                "gosi": {k: v for k, v in g.items() if k != "ingredients"} | {"ingredients_chars": len(g.get("ingredients", ""))},
                "us_label": label["label"],
                "draft_reasons": reasons,
                "canonical_public_gate": public_gate,
                "title": title,
                "images": images,
                "description_html": html,
            }
            if DRY_RUN or shop is None:
                rec["status"] = "dry_run"
            else:
                # Re-read the entire catalogue just before writing; the daily cap and duplicate checks are unconditional.
                names, ids = shop_keys(shop.existing_products())
                if already_registered(p, reg, names, ids, title) or shop.exists(p["pdNo"]):
                    rec["status"] = "skipped_duplicate_at_create"
                    results.append(rec)
                    continue
                cmpd = pr.get("shop_compare") or {}
                entry = {"pd_no": str(p["pdNo"]), "family": family_key(clean_name(p["pdNm"])),
                         "name_kr": clean_name(p["pdNm"]), "title": title, "category": cat[0],
                         "date": today, "status": "create_reserved", "krw": krw,
                         "single_usd": pr["single"]["price_usd"],
                         "single_margin_pct": pr["single"]["margin_pct"],
                         "pack_usd": pr["pack"]["price_usd"] if pr["pack"]["ok"] else None,
                         "pack_margin_pct": pr["pack"]["margin_pct"] if pr["pack"]["ok"] else None,
                         "size": parse_size(clean_name(p["pdNm"])), "images": len(images),
                         "price_basis": pr["basis"], "shop_com_lowest_usd": cmpd.get("lowest_usd"),
                         "draft_reasons": reasons, "grade": "S", "source": p.get("_source")}
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
                for gate_reason in public_gate["reasons"]:
                    if gate_reason not in reasons:
                        reasons.append(gate_reason)
                if not reasons:
                    try:
                        shop.set_status(prod["id"], "ACTIVE")
                        shop.publish(prod["id"], pub)
                        live = verify_product(shop, prod["id"], item, pub, published=True)
                        rec["verified_status"] = live["status"]
                        rec["published_on_online_store"] = bool(live["publishedOnPublication"])
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
            failed = {"category": cat[0], "status": "failed", "grade_required": "S", "error": str(exc)[:500]}
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
