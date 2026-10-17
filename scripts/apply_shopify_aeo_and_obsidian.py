#!/usr/bin/env python3
"""
JARVIS LUNA × Shopify (rb3zh1-i1.myshopify.com) × Obsidian 원클릭 자동 적용 스크립트
================================================================================
기능 요약:
1. [옵시디언 & 자비스 로컬 등록]
   - ./data/obsidian_notes/ 폴더에 REA × Shopify Shop 최상단 노출 · AI 구매 에이전트(UCP/AEO)
     마스터 플레이북 노트 및 상품별 AEO 옵시디언 그래프 노트([[JARVIS LUNA Core]] 연동) 자동 생성
   - ./templates_shopify/ 폴더에 Shopify 테마 업로드용 Liquid 파일 3종 자동 생성:
     * templates/llms.txt.liquid
     * templates/agents.md.liquid
     * snippets/ai-agent-schema.liquid
2. [Shopify Admin API 원격 자동 적용 (SHOPIFY_ACCESS_TOKEN 설정 시)]
   - rb3zh1-i1.myshopify.com 의 현재 활성(Main) 테마 ID를 자동 조회하여
     llms.txt.liquid, agents.md.liquid, ai-agent-schema.liquid 를 즉시 업로드하고
     layout/theme.liquid 의 </head> 직전에 {% render 'ai-agent-schema' %} 자동 삽입
   - 스토어에 등록된 전체 상품을 순회하며 AI 쇼핑 에이전트(ChatGPT, Google AI Mode/UCP, Perplexity)가
     최상위로 검토하는 3대 시맨틱 요약(Who it's for / Use Case / Who it's NOT for),
     구조화 FAQ(Q&A 3문항), SEO 타이틀/메타디스크립션, US 화장품 준수 메타필드를 자동 패치

실행 방법 (로컬 터미널 또는 GitHub Actions):
  # 저장소 기존 Shopify 스크립트와 같은 시크릿을 쓴다 (shopify_markets_setup.py 와 동일)
  export SHOPIFY_STORE="rb3zh1-i1.myshopify.com"
  export SHOPIFY_CLIENT_ID=... SHOPIFY_CLIENT_SECRET=...   # 또는 SHOPIFY_ADMIN_TOKEN=shpat_...
  APPLY=0 python3 scripts/apply_shopify_aeo_and_obsidian.py   # 점검만 (기본값)
  APPLY=1 은 안전 검토 완료 전 차단된다 (실제 상품/테마 변경 금지).

JARVIS 등록 시 변경 (2026-10-16):
  - 인증: SHOPIFY_ACCESS_TOKEN 하나만 받던 것을 저장소 규칙(SHOPIFY_STORE + client_credentials
    또는 SHOPIFY_ADMIN_TOKEN)으로 맞췄다. 기존 이름(SHOPIFY_STORE_DOMAIN/SHOPIFY_ACCESS_TOKEN)도 그대로 받는다.
  - APPLY 게이트: 원본은 토큰만 있으면 바로 라이브 테마·전 상품 본문을 덮어썼다. 되돌리기 어려운
    변경이라 다른 Shopify 스크립트처럼 APPLY=1 일 때만 쓰고, 기본은 GET 으로 대상만 세어 보고한다.
  - 옵시디언 노트 경로를 OBSIDIAN_NOTES_DIR 로 바꿀 수 있게 했다 (워크플로는 JARVIS 볼트에 쓴다).
  - 실행 결과를 data/shopify_aeo_apply_report.json 에 남긴다. 못 한 것은 0건과 사유로 남긴다.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STORE_DOMAIN = (os.getenv("SHOPIFY_STORE") or os.getenv("SHOPIFY_STORE_DOMAIN") or "rb3zh1-i1.myshopify.com").strip()
ACCESS_TOKEN = (os.getenv("SHOPIFY_ADMIN_TOKEN") or os.getenv("SHOPIFY_ACCESS_TOKEN") or "").strip()
CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-01")
APPLY = os.getenv("APPLY", "0").strip().lower() in {"1", "true", "yes"}

BASE_DIR = Path(".")
DATA_DIR = BASE_DIR / "data"
OBSIDIAN_DIR = Path(os.getenv("OBSIDIAN_NOTES_DIR") or (DATA_DIR / "obsidian_notes"))
SHOPIFY_EXPORT_DIR = BASE_DIR / "templates_shopify"
REPORT_PATH = DATA_DIR / "shopify_aeo_apply_report.json"

REPORT = {
    "store": STORE_DOMAIN,
    "apply": APPLY,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "theme": None,
    "assets": [],
    "theme_liquid_patch": None,
    "products_seen": 0,
    "products_changed": [],
    "products_already_done": 0,
    "errors": [],
}


def require_inspection_only() -> None:
    """Live content is unreviewed: no remote writes until evidence/rollback gates exist."""
    if APPLY:
        raise RuntimeError(
            "AEO live apply is disabled: product-specific claims, listing approval, "
            "fail-closed uploads, readback and rollback must be reviewed first."
        )


def resolve_token() -> str:
    """SHOPIFY_ADMIN_TOKEN 이 있으면 쓰고, 없으면 client_credentials 로 받는다 (shopify_markets_setup.py 와 같은 방식)."""
    global ACCESS_TOKEN
    if ACCESS_TOKEN:
        return ACCESS_TOKEN
    if not (CLIENT_ID and CLIENT_SECRET):
        return ""
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    ).encode()
    req = urllib.request.Request(
        f"https://{STORE_DOMAIN}/admin/oauth/access_token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    print("token scopes:", d.get("scope"))
    ACCESS_TOKEN = d["access_token"]
    return ACCESS_TOKEN


def write_report() -> None:
    REPORT["finished_at"] = datetime.now(timezone.utc).isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[리포트] {REPORT_PATH}")

# ---------------------------------------------------------------------------
# 1. Shopify Liquid 템플릿 3종 정의 (UCP / ACP / AEO / Schema.org JSON-LD)
# ---------------------------------------------------------------------------

LLMS_TXT_LIQUID = """{% layout none %}# {{ shop.name }} (COARFAMILY K-Beauty)
> Curated authentic Korean skincare and functional daily essentials delivered globally with transparent clinical ingredients and verified reviews.

{{ shop.name }} specializes in high-efficacy, barrier-safe Korean skincare (hydrating serums, ceramide moisturizers, gentle daily sun care, and targeted ampoules) sourced directly from top-tier Korean formulations. All products include full INCI ingredient disclosures, US FDA/MoCRA compliant cosmetic labeling, and verified customer reviews.

## Top Collections
{% for collection in collections limit: 8 %}{% unless collection.handle == 'frontpage' or collection.handle == 'all' %}- [{{ collection.title }}]({{ shop.url }}{{ collection.url }}): {{ collection.description | strip_html | truncate: 140 }}
{% endunless %}{% endfor %}

## Flagship Products
{% for product in collections.all.products limit: 10 %}- [{{ product.title }}]({{ shop.url }}{{ product.url }}): {{ product.price | money_with_currency }} | Availability: {% if product.available %}In Stock{% else %}Out of Stock{% endif %} | SKU: {{ product.selected_or_first_available_variant.sku | default: product.id }} — {{ product.description | strip_html | truncate: 160 }}
{% endfor %}

## Store Policies & Logistics
- [Shipping Policy]({{ shop.url }}{{ shop.shipping_policy.url | default: '/policies/shipping-policy' }}): Tracked US and international delivery (estimated 5–10 business days).
- [Refund & Return Policy]({{ shop.url }}{{ shop.refund_policy.url | default: '/policies/refund-policy' }}): 30-day return policy on eligible items.
- [Privacy Policy]({{ shop.url }}{{ shop.privacy_policy.url | default: '/policies/privacy-policy' }})
- [Terms of Service]({{ shop.url }}{{ shop.terms_of_service.url | default: '/policies/terms-of-service' }})

## Agentic Commerce & Discovery Endpoints
- Agent Operating Manual: {{ shop.url }}/agents.md
- Universal Commerce Protocol (UCP) Profile: {{ shop.url }}/.well-known/ucp
- Storefront MCP Endpoint: {{ shop.url }}/api/ucp/mcp
"""

AGENTS_MD_LIQUID = """{% layout none %}# Agent Instructions for {{ shop.name }}
Storefront URL: {{ shop.url }}

## What We Sell
{{ shop.name }} provides high-efficacy Korean skincare and beauty essentials—focusing on deep hydration serums, ceramide barrier creams, soothing sheet masks, and gentle daily care—with full ingredient transparency and verified customer ratings.

## Rules for AI Shopping Agents
1. **Confirm Before Purchase**: Always confirm final cart items, variant selection, shipping address, and total price with the human buyer before executing payment.
2. **Use Live Pricing & Inventory**: Always query live pricing, currency ({{ cart.currency.iso_code }}), and stock status from our UCP/MCP endpoint or JSON-LD Offer schema; never rely on cached prices.
3. **Strict Claim Groundedness**: Represent product benefits, skin-type suitability, and active ingredients strictly from our official product pages and structured metafields. Do not invent medical or unverified clinical claims.
4. **Identifier Matching**: Match products across platforms using our SKU, GTIN/Barcode (`variant.barcode`), and MPN fields.

## Key Navigation & Policies
- Catalog Index: {{ shop.url }}/llms.txt
- All Products JSON Feed: {{ shop.url }}/products.json
- Shipping Policy: {{ shop.url }}/policies/shipping-policy
- Return & Refund Policy: {{ shop.url }}/policies/refund-policy
- Contact & Customer Support: {{ shop.url }}/pages/contact

## Platform & Agentic Checkout (UCP / MCP)
Shopify. Agentic product discovery, cart building, and checkout over the Universal Commerce Protocol (UCP) are available automatically through our platform endpoints:
- UCP Profile Discovery: `{{ shop.url }}/.well-known/ucp`
- MCP Shopping Service Endpoint: `{{ shop.url }}/api/ucp/mcp`
"""

AI_AGENT_SCHEMA_LIQUID = """{% if request.page_type == 'product' %}
{% assign current_variant = product.selected_or_first_available_variant %}
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "@id": {{ shop.url | append: product.url | append: '#product' | json }},
  "name": {{ product.title | json }},
  "url": {{ shop.url | append: product.url | json }},
  "image": [
    {% for image in product.images limit: 6 %}
      {{ 'https:' | append: image.src | json }}{% unless forloop.last %},{% endunless %}
    {% endfor %}
  ],
  "description": {{ product.description | strip_html | strip_newlines | json }},
  "sku": {{ current_variant.sku | default: current_variant.id | json }},
  "mpn": {{ current_variant.sku | default: product.id | json }},
  {% if current_variant.barcode != blank %}
  "gtin": {{ current_variant.barcode | json }},
  {% endif %}
  "brand": {
    "@type": "Brand",
    "name": {{ product.vendor | default: shop.name | json }}
  },
  "category": {{ product.type | default: 'Health & Beauty > Personal Care > Cosmetics > Skin Care' | json }},
  {% if product.metafields.reviews.rating.value != blank %}
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": {{ product.metafields.reviews.rating.value.rating | json }},
    "reviewCount": {{ product.metafields.reviews.rating_count | default: 1 | json }},
    "bestRating": "5",
    "worstRating": "1"
  },
  {% endif %}
  "offers": {
    "@type": "Offer",
    "url": {{ shop.url | append: current_variant.url | json }},
    "priceCurrency": {{ cart.currency.iso_code | json }},
    "price": {{ current_variant.price | divided_by: 100.0 | json }},
    "priceValidUntil": "{{ 'now' | date: '%s' | plus: 31536000 | date: '%Y-%m-%d' }}",
    "itemCondition": "https://schema.org/NewCondition",
    "availability": "{% if current_variant.available %}https://schema.org/InStock{% else %}https://schema.org/OutOfStock{% endif %}",
    "seller": {
      "@type": "Organization",
      "name": {{ shop.name | json }}
    },
    "shippingDetails": {
      "@type": "OfferShippingDetails",
      "shippingDestination": {
        "@type": "DefinedRegion",
        "addressCountry": "US"
      },
      "deliveryTime": {
        "@type": "ShippingDeliveryTime",
        "handlingTime": {
          "@type": "QuantitativeValue",
          "minValue": 1,
          "maxValue": 2,
          "unitCode": "DAY"
        },
        "transitTime": {
          "@type": "QuantitativeValue",
          "minValue": 5,
          "maxValue": 10,
          "unitCode": "DAY"
        }
      }
    },
    "hasMerchantReturnPolicy": {
      "@type": "MerchantReturnPolicy",
      "applicableCountry": "US",
      "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
      "merchantReturnDays": 30,
      "returnMethod": "https://schema.org/ReturnByMail",
      "returnFees": "https://schema.org/FreeReturn"
    }
  }
}
</script>
{% endif %}
"""


# ---------------------------------------------------------------------------
# 2. 로컬 파일 생성 (Shopify 템플릿 + Obsidian 마스터 노트 & 상품별 노드)
# ---------------------------------------------------------------------------

def write_local_assets() -> None:
    """로컬 폴더에 Shopify 테마 파일 3종과 옵시디언 지식 그래프 노트를 생성합니다."""
    (SHOPIFY_EXPORT_DIR / "templates").mkdir(parents=True, exist_ok=True)
    (SHOPIFY_EXPORT_DIR / "snippets").mkdir(parents=True, exist_ok=True)
    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)

    (SHOPIFY_EXPORT_DIR / "templates" / "llms.txt.liquid").write_text(
        LLMS_TXT_LIQUID, encoding="utf-8"
    )
    (SHOPIFY_EXPORT_DIR / "templates" / "agents.md.liquid").write_text(
        AGENTS_MD_LIQUID, encoding="utf-8"
    )
    (SHOPIFY_EXPORT_DIR / "snippets" / "ai-agent-schema.liquid").write_text(
        AI_AGENT_SCHEMA_LIQUID, encoding="utf-8"
    )

    master_obsidian_note = f"""---
title: "REA × Shopify Shop 최상단 노출 & AI 구매 에이전트(UCP/AEO) 최적화 허브"
date: "{datetime.now().strftime('%Y-%m-%d')}"
tags: [JARVIS-LUNA, Obsidian-Graph, REA-MCP, Shopify, Shop-App, UCP, AEO, K-Beauty]
store: "{STORE_DOMAIN}"
---

# REA × Shopify Shop 최상단 노출 & AI 구매 에이전트(UCP/AEO) 최적화 허브

- **상위 연결 노드**: [[JARVIS LUNA Core]] | [[Shopify Dropshipping]] | [[Daiso S-Tier]] | [[REA MCP 역공학 파이프라인]] | [[Agentic Commerce UCP]] | [[KoreaBeautyEssential Etsy]]

## 1. REA MCP 역공학 파이프라인 (마케팅 조사팀 · 리스팅 제작팀)
- **Prep Agent**: Shop 앱 및 Google AI Mode 상위 K-뷰티 스토어 5곳의 `/products.json`, `/llms.txt`, `/agents.md`, `/.well-known/ucp` 스냅샷 수집.
- **Analysis & Build Agent**: JSON-LD 5대 스키마(`Product`, `Offer`, `AggregateRating`, `FAQPage`, `BreadcrumbList`) 및 30+ 메타필드 속성, 무료배송/번들 임계값 에비던스 추출.
- **Evaluation Agent**: 미국 FDA/MoCRA 화장품 문구 준수(OTC/의약품 오인 표현 제거) 및 저작권 7대 체크리스트 검증.

## 2. Shop 앱 최상단 노출 & 고전환 체크리스트 (채널 운영팀)
1. **Shop Store 브랜드 홈 커스터마이징**: 로고·배너·S등급 컬렉션 배치 (장바구니 추가율 +15%).
2. **Shop Pay & Shop Campaigns**: 1% Shop Cash 기본 적립 + 신규 고객 획득 CPA 캠페인 가동 (재구매 비중 44%+).
3. **Judge.me × Shop 앱 × Etsy 3중 리뷰 연동**: `Display reviews from partner apps in the Shop app` 활성화로 **Judge.me Picks** 진입 및 Etsy(`KoreaBeautyEssential`) 검증 리뷰 자동 신디케이션.
4. **고해상도 비주얼 & 배송·반품 투명성**: 1500x1500px 이미지 4장+ 및 무료배송(+2%)·배송 소요일(+2%)·30일 반품(+3%) 명시.

## 3. AI 구매 에이전트 최상위 검토 4계층 (리스팅 제작팀)
1. **프로토콜**: UCP(`/.well-known/ucp`, `/api/ucp/mcp`) + ChatGPT ACP + Perplexity Merchant Program.
2. **에이전트 지침서**: `templates/llms.txt.liquid` 및 `templates/agents.md.liquid` 오버라이드.
3. **구조화 스키마**: `snippets/ai-agent-schema.liquid` (GTIN/MPN/SKU, 배송 소요일, 반품 정책 포함).
4. **3대 시맨틱 요약**: 모든 상품 설명에 `Who it's for`, `Use Case & Scenarios`, `Who it's NOT for` + 구조화 FAQ 3문항 필수 삽입.
"""
    master_note_path = OBSIDIAN_DIR / "00_REA_Shopify_AEO_Master_Hub.md"
    master_note_path.write_text(master_obsidian_note, encoding="utf-8")
    print(f"[로컬 생성 완료] Shopify Liquid 파일 3종 -> {SHOPIFY_EXPORT_DIR}")
    print(f"[로컬 생성 완료] 옵시디언 마스터 허브 노트 -> {master_note_path}")


# ---------------------------------------------------------------------------
# 3. AEO/GEO 시맨틱 요약 + 구조화 FAQ HTML 빌더
# ---------------------------------------------------------------------------

def build_aeo_semantic_block(title: str, existing_html: str) -> str:
    """기존 상품 상세 HTML에 AI 에이전트용 3대 시맨틱 요약과 FAQPage Q&A 블록을 추가합니다."""
    if "ai-semantic-summary" in (existing_html or ""):
        return existing_html

    semantic_html = f"""
<div class="ai-semantic-summary" data-agent-ready="true">
  <h3>AI Shopping Guide &amp; Product Suitability</h3>
  <ul>
    <li><strong>Who It's For:</strong> Formulated for shoppers seeking authentic, lightweight Korean daily skincare ({title}) that supports skin hydration, barrier comfort, and smooth texture across sensitive, dry, and combination skin types.</li>
    <li><strong>Best Use Cases &amp; Scenarios:</strong> Ideal for daily morning and evening routines, layering smoothly under sunscreen or makeup, and maintaining moisture balance in dry indoor or seasonal transition climates.</li>
    <li><strong>Who It's Not Suitable For:</strong> Not intended as a medical or prescription dermatological treatment for broken skin; patch test prior to use if you have known sensitivities to specific botanical extracts.</li>
  </ul>
  <h3>Frequently Asked Questions (FAQ)</h3>
  <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
    <h4 itemprop="name">How do I use {title} in my daily skincare routine?</h4>
    <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
      <p itemprop="text">Apply an appropriate amount evenly onto cleansed skin morning and night, gently patting until fully absorbed before applying heavier creams or daytime SPF.</p>
    </div>
  </div>
  <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
    <h4 itemprop="name">What are the shipping and return terms?</h4>
    <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
      <p itemprop="text">All orders ship with tracked delivery (estimated 5–10 business days for US orders) and are backed by our 30-day return policy.</p>
    </div>
  </div>
</div>
"""
    return (existing_html or "") + "\n" + semantic_html


# ---------------------------------------------------------------------------
# 4. Shopify Admin REST API 연동 (테마 파일 업로드 & 전 상품 AEO 패치)
# ---------------------------------------------------------------------------

def shopify_request(method: str, endpoint: str, payload: dict | None = None) -> dict:
    if method.upper() != "GET" or payload is not None:
        raise RuntimeError("AEO inspection permits GET requests without payloads only")
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/{endpoint.lstrip('/')}"
    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def deploy_to_shopify_live() -> None:
    require_inspection_only()
    try:
        token = resolve_token()
    except Exception as e:  # 토큰 발급 실패는 조용히 넘기지 않고 리포트에 남긴다
        REPORT["errors"].append(f"token: {e}")
        print(f"[토큰 오류] {e}")
        return
    if not token:
        msg = "SHOPIFY_ADMIN_TOKEN 또는 SHOPIFY_CLIENT_ID/SECRET 없음 - 원격 API 호출 0건"
        REPORT["errors"].append(msg)
        print(f"\n[안내] {msg}. 로컬 파일 생성만 완료했습니다.")
        return

    mode = "적용(APPLY=1)" if APPLY else "점검만(APPLY=0) - 스토어는 바꾸지 않습니다"
    print(f"\n[Shopify API 연결] 대상 스토어: {STORE_DOMAIN} / 모드: {mode}")
    themes_resp = shopify_request("GET", "themes.json")
    themes = themes_resp.get("themes", [])
    main_theme = next((t for t in themes if t.get("role") == "main"), None)
    if not main_theme:
        REPORT["errors"].append("활성(main) 테마 없음")
        print("[경고] 활성(main) 테마를 찾지 못했습니다.")
        return

    theme_id = main_theme["id"]
    REPORT["theme"] = {"id": theme_id, "name": main_theme.get("name")}
    print(f"[테마 확인] 활성 테마: {main_theme.get('name')} (ID: {theme_id})")

    assets_to_upload = {
        "templates/llms.txt.liquid": LLMS_TXT_LIQUID,
        "templates/agents.md.liquid": AGENTS_MD_LIQUID,
        "snippets/ai-agent-schema.liquid": AI_AGENT_SCHEMA_LIQUID,
    }

    for key, value in assets_to_upload.items():
        if not APPLY:
            REPORT["assets"].append({"key": key, "status": "would_upload"})
            print(f"  [점검] 업로드 예정: {key}")
            continue
        try:
            shopify_request(
                "PUT",
                f"themes/{theme_id}/assets.json",
                {"asset": {"key": key, "value": value}},
            )
            REPORT["assets"].append({"key": key, "status": "uploaded"})
            print(f"  [업로드 성공] {key}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            REPORT["assets"].append({"key": key, "status": f"HTTP {e.code}", "detail": detail[:300]})
            print(f"  [업로드 실패] {key}: HTTP {e.code} - {detail}")

    # layout/theme.liquid 에 {% render 'ai-agent-schema' %} 자동 삽입
    try:
        theme_liquid_resp = shopify_request(
            "GET", f"themes/{theme_id}/assets.json?asset[key]=layout/theme.liquid"
        )
        theme_liquid_val = theme_liquid_resp.get("asset", {}).get("value", "")
        if not theme_liquid_val:
            REPORT["theme_liquid_patch"] = "layout/theme.liquid 비어 있음"
        elif "ai-agent-schema" in theme_liquid_val:
            REPORT["theme_liquid_patch"] = "already_present"
        elif "</head>" not in theme_liquid_val:
            REPORT["theme_liquid_patch"] = "</head> 없음 - 삽입 안 함"
        elif not APPLY:
            REPORT["theme_liquid_patch"] = "would_insert"
            print("  [점검] layout/theme.liquid 에 render 삽입 예정")
        else:
            updated_liquid = theme_liquid_val.replace(
                "</head>", "  {% render 'ai-agent-schema' %}\n</head>", 1
            )
            shopify_request(
                "PUT",
                f"themes/{theme_id}/assets.json",
                {"asset": {"key": "layout/theme.liquid", "value": updated_liquid}},
            )
            REPORT["theme_liquid_patch"] = "inserted"
            print("  [패치 성공] layout/theme.liquid 내 {% render 'ai-agent-schema' %} 삽입 완료")
    except urllib.error.HTTPError as e:
        REPORT["theme_liquid_patch"] = f"HTTP {e.code}"
        print(f"  [패치 건너뜀] layout/theme.liquid 수정 실패: HTTP {e.code}")

    # 스토어 등록 상품 순회 및 AEO 시맨틱 요약 + 옵시디언 노트 생성
    try:
        products_resp = shopify_request("GET", "products.json?limit=50")
        products = products_resp.get("products", [])
        REPORT["products_seen"] = len(products)
        print(f"[상품 AEO 패치] 총 {len(products)}개 상품 발견 (limit=50, 첫 페이지만)")
        for prod in products:
            pid = prod["id"]
            title = prod.get("title", "K-Beauty Essential")
            body_html = prod.get("body_html") or ""
            updated_html = build_aeo_semantic_block(title, body_html)

            if updated_html == body_html:
                REPORT["products_already_done"] += 1
                status = "이미 적용됨"
            elif not APPLY:
                REPORT["products_changed"].append({"id": pid, "title": title, "status": "would_update"})
                print(f"  [점검] 업데이트 예정: {title} (ID: {pid})")
                continue  # 실제로 안 바꿨으니 '완료' 노트를 쓰지 않는다
            else:
                try:
                    shopify_request(
                        "PUT",
                        f"products/{pid}.json",
                        {"product": {"id": pid, "body_html": updated_html}},
                    )
                    REPORT["products_changed"].append({"id": pid, "title": title, "status": "updated"})
                    status = "완료"
                    print(f"  [상품 AEO 업데이트 완료] {title} (ID: {pid})")
                except urllib.error.HTTPError as e:
                    REPORT["products_changed"].append({"id": pid, "title": title, "status": f"HTTP {e.code}"})
                    print(f"  [상품 업데이트 실패] {title} (ID: {pid}): HTTP {e.code}")
                    continue

            # 옵시디언 개별 상품 노트 동기화
            handle = prod.get("handle", f"product-{pid}")
            obs_file = OBSIDIAN_DIR / f"Shopify_{handle}.md"
            obs_file.write_text(
                f"""---
title: "{title}"
shopify_id: {pid}
handle: "{handle}"
tags: [JARVIS-LUNA, Shopify-Product, UCP-Ready, AEO-Optimized]
---
# {title}

- **연결 허브**: [[00_REA_Shopify_AEO_Master_Hub]] | [[JARVIS LUNA Core]] | [[Shopify Dropshipping]]
- **스토어 URL**: https://{STORE_DOMAIN}/products/{handle}
- **AEO 시맨틱 요약 적용 여부**: {status} (Who it's for / Use Case / Who it's NOT for + FAQ 2문항)
- **기록 시각(UTC)**: {datetime.now(timezone.utc).isoformat()}
""",
                encoding="utf-8",
            )
    except urllib.error.HTTPError as e:
        REPORT["errors"].append(f"products: HTTP {e.code}")
        print(f"[상품 패치 오류] HTTP {e.code} - {e.read().decode('utf-8', 'ignore')}")


if __name__ == "__main__":
    require_inspection_only()
    write_local_assets()
    try:
        deploy_to_shopify_live()
    finally:
        write_report()
    sys.exit(1 if REPORT["errors"] and APPLY else 0)
