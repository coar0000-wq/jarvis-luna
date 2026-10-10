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
import base64
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
                    "category": item["category"],
                    "tags": item["tags"],
                    "status": item.get("status", "ACTIVE"),
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
FORCE = os.environ.get("FORCE", "0").strip().lower() in {"1", "true", "yes"}


def kst_today():
    from datetime import timedelta  # noqa: PLC0415

    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def family_key(name_kr):
    """같은 상품의 색상·호수·괄호 표기만 다른 변형을 한 묶음으로 본다: 대괄호/괄호 안 글자와 공백을 지운 이름."""
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", name_kr or "")
    return re.sub(r"[\s\-_/·.,]+", "", s).lower()


def load_registry():
    try:
        d = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {}
    d.setdefault("items", [])
    return d


def save_registry(d):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- Main


def pick(cat, shop, titles, reg):
    seen_pd = {str(i.get("pd_no")) for i in reg["items"]}
    seen_fam = {i.get("family") for i in reg["items"]}
    items = [p for p in fetch_daiso(cat[1], cat[2]) if sellable(p)]
    items.sort(key=score, reverse=True)
    for p in items:
        if str(p["pdNo"]) in seen_pd or family_key(clean_name(p["pdNm"])) in seen_fam:
            continue  # 이미 올렸던 상품(삭제했어도) 또는 같은 상품의 색상·호수 변형
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

    reg = load_registry()
    today = kst_today()
    results, failures = [], 0
    for cat in CATEGORIES:
        if ONLY and cat[0] not in ONLY:
            continue
        log(f"== {cat[1]} ({cat[0]})")
        if not FORCE and any(i.get("date") == today and i.get("category") == cat[0] for i in reg["items"]):
            log("  already registered today for this category -> skip (하루 카테고리별 1개)")
            results.append({"category": cat[0], "status": "skipped_already_today"})
            continue
        try:
            p = pick(cat, shop, titles, reg)
            if not p:
                log("  no eligible product")
                results.append({"category": cat[0], "status": "skipped_no_candidate"})
                continue
            krw = int(p["pdPrc"])
            copy = gemini_copy(p, cat) or fallback_copy(p, cat)
            title, html = copy
            base = jarvis_price(p["pdNo"], clean_name(p["pdNm"]), krw)
            pr = final_prices(p["pdNo"], clean_name(p["pdNm"]), krw, title, base["price_usd"])
            g = collect_gosi(p["pdNo"])
            label = build_us_label(p["pdNo"], clean_name(p["pdNm"]), g)
            if has_claims(title, html):  # 효능·의료 표현이 섞이면 사실만 쓴 규칙 기반 문구로 교체
                title, html = fallback_copy(p, cat)
            claims_left = has_claims(title, html)
            html += label["html"]
            html += f'<p><small>Source: Daiso Mall item {p["pdNo"]}.</small></p>'
            reasons = list(label["reasons"])
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
            if not imgs["source_urls"]:
                reasons.append("no_usable_product_images")
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
                "tags": [cat[0], "daiso-daily", f"daiso-pd-{p['pdNo']}", "k-beauty"],
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
                "title": title,
                "images": images,
                "description_html": html,
            }
            if DRY_RUN or shop is None:
                rec["status"] = "dry_run"
            else:
                prod = shop.create(item, pub)
                rec["status"] = "created" if item["status"] == "ACTIVE" else "created_draft"
                rec["shopify_id"] = prod["id"]
                rec["handle"] = prod["handle"]
                rec["url"] = f"https://{shop.store}/products/{prod['handle']}"
                titles.add(title.lower())
                cmpd = pr.get("shop_compare") or {}
                reg["items"].append({"pd_no": str(p["pdNo"]), "family": family_key(clean_name(p["pdNm"])), "name_kr": clean_name(p["pdNm"]),
                                     "title": title, "category": cat[0], "date": today, "shopify_id": prod["id"],
                                     "status": item["status"], "handle": prod["handle"], "krw": krw,
                                     "single_usd": pr["single"]["price_usd"], "single_margin_pct": pr["single"]["margin_pct"],
                                     "pack_usd": pr["pack"]["price_usd"] if pr["pack"]["ok"] else None,
                                     "pack_margin_pct": pr["pack"]["margin_pct"] if pr["pack"]["ok"] else None,
                                     "size": parse_size(clean_name(p["pdNm"])), "images": len(images),
                                     "price_basis": pr["basis"], "shop_com_lowest_usd": cmpd.get("lowest_usd"),
                                     "draft_reasons": reasons})
                save_registry(reg)
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
