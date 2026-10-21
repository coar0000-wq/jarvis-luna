#!/usr/bin/env python3
"""Shopify AEO inspection and local review notes; never a deployment tool.

APPLY=0 creates non-deployable *.review.md documents and a review hub. With
existing configured authentication it can inspect a theme and the first product
page using GET only. Local files, API fields, or HTML markers do not establish
listing approval, regulatory compliance, public URLs, indexing, or performance.
APPLY=1 is blocked before local generation, authentication, or network activity.
Existing generated Liquid files and product bodies are not rewritten.

Authentication environment names and the report path are retained for callers.
The legacy deploy_to_shopify_live name is retained for inspection callers only.
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
    "mode": "inspection_only",
    "local_review_assets": [],
    "theme_inspection": {},
    "products_review": [],
    "product_scope": "first_page_only_limit_50",
    "publication_verified": False,
}


def require_inspection_only() -> None:
    """Live content is unreviewed: no remote writes until evidence/rollback gates exist."""
    if APPLY:
        raise RuntimeError(
            "AEO live apply is disabled: product-specific claims, listing approval, "
            "fail-closed uploads, readback and rollback must be reviewed first."
        )


def resolve_token() -> str:
    """Use the existing repository authentication flow; never broaden its scope."""
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


# Legacy constant names remain import-compatible. Their contents are review
# documents, not runnable Liquid, feeds, protocol endpoints, or schema snippets.
LLMS_TXT_LIQUID = """# llms.txt review draft — DO NOT UPLOAD

Status: local_review_only; not approved for publication.
Shopify documents platform-provided discovery files. Check the existing public
output before considering any override; even a blank Liquid override can hide
that output. This document must not be installed as a theme template.

Review only:
- Compare current store information with the actual catalog and published policies.
- Use only supported product facts; omit unverified benefits and legal assertions.
- Do not invent policy URLs, delivery estimates, return terms, reviews, or endpoints.
- A local file does not establish a working URL, feed, indexing, or recommendations.

Source: https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/products
"""

AGENTS_MD_LIQUID = """# agents.md review draft — DO NOT UPLOAD

Status: local_review_only; not approved for publication.
Review Shopify's existing agent discovery output and Catalog eligibility first.
Discovery files are separate from the Catalog product feed. Do not replace the
platform output or claim checkout/protocol support from this local document.

Review only:
- Preserve actual product identity, variant identifiers, pricing, and availability.
- Verify identifiers independently; a SKU does not establish an MPN or GTIN.
- Directions, suitability, warnings, and claims need product-specific evidence.
- Confirm actual store policies and capabilities before describing them.
- Store eligibility, channel activation, and recommendation results remain unverified.

Source: https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/products
Source: https://help.shopify.com/en/manual/shopify-catalog/requirements
"""

AI_AGENT_SCHEMA_LIQUID = """# Product structured-data review draft — DO NOT UPLOAD

Status: local_review_only; no executable schema supplied.
Inspect rendered product pages and existing theme/app structured data first.
Consider Shopify's native Product structured data only after checking for
existing coverage, duplicates, visible content agreement, and actual values.
This script does not insert a snippet or modify layout/theme.liquid.

Review only:
- Missing identifiers, ratings, rating counts, price validity, shipping, and returns
  must remain omitted until their actual source and applicability are verified.
- Do not infer an identifier, rating count, deadline, condition, or policy default.
- Product type is not evidence of ingredients, benefits, suitability, or directions.
- Google AI search has no special AI schema or AI text-file requirement.
- Presence of schema is not evidence of eligibility, indexing, ranking, or sales.

Source: https://developers.google.com/search/docs/appearance/ai-features
"""

REVIEW_ASSETS = {
    "review/llms.txt.review.md": LLMS_TXT_LIQUID,
    "review/agents.md.review.md": AGENTS_MD_LIQUID,
    "review/product-schema.review.md": AI_AGENT_SCHEMA_LIQUID,
}


def write_local_assets() -> None:
    """Write non-deployable review documents; leave all existing Liquid untouched."""
    require_inspection_only()
    for key, content in REVIEW_ASSETS.items():
        path = SHOPIFY_EXPORT_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    REPORT["local_review_assets"] = [
        {"key": key, "status": "local_review_only", "deployable": False}
        for key in REVIEW_ASSETS
    ]
    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    master_obsidian_note = f"""---
title: "Shopify 상품 정보 및 AI 검색 검토 초안"
date: "{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
tags: [JARVIS-LUNA, Shopify, Review-Required]
store: {json.dumps(STORE_DOMAIN, ensure_ascii=False)}
status: local_review_only
publication_verified: false
---

# Shopify 상품 정보 및 AI 검색 검토 초안

- 연결: [[JARVIS LUNA Core]] | [[Shopify Dropshipping]]
- 이 노트는 검토 계획이며 REA 실행, 상품 승인, 배포, 색인 또는 노출 성과의 증거가 아니다.
- APPLY=1은 차단되며 API 점검은 GET 전용이다. 상품·테마·채널·결제 설정을 변경하지 않는다.
- 검토 문서는 `templates_shopify/review/*.review.md`에만 생성한다. 테마 업로드 대상으로 사용하지 않는다.
- 기존 생성 Liquid와 기존 상품 본문은 보존한다. 그 존재나 옛 마커는 검증·완료를 뜻하지 않는다.

## 먼저 확인할 정보
1. 실제 상품명·유형·변형·이미지·가격·재고와 Shopify Catalog 매핑 및 자격을 확인한다.
2. 상품별 라벨 또는 제조사 근거 없이 성분·효능·피부적합성·사용법·주의사항·규제준수를 추정하지 않는다.
3. 배송비·기간·반품조건은 현재 정책과 적용 지역/상품 근거가 필요하다. 리뷰 출처·수·연동 상태도 별도 확인한다.
4. 기존 테마와 앱의 Product 구조화 데이터를 실제 출력에서 확인한 뒤 중복과 값의 일치를 검토한다.
5. 사람 검토와 별도 변경 승인이 필요하다. API 필드의 존재만으로 상품 정보가 검증되거나 공개 승인된 것은 아니다.
6. Admin 상품명·유형은 미검증 관찰값으로만 기록한다. 승인된 상품 식별/유형 근거가 없는 이 점검 경로에서는 새 FAQ나 추천 문구를 생성하지 않는다.

## 플랫폼 문서와 이 스토어의 상태 구분
- Shopify는 기본 agent discovery 파일을 제공하며 Catalog와는 별개다. 기본 출력을 먼저 확인하고 덮어쓰지 않는다.
- OpenAI는 Shopify 상품 데이터가 Catalog로 통합됨을 설명한다. 별도 피드 파일 생성이 이 스토어의 등록 증거는 아니다.
- Google AI 검색에 특별 AI schema 또는 llms.txt 파일은 필수가 아니다. 기본 검색 요건 충족도 색인·노출을 보장하지 않는다.
- 이 스크립트는 이 스토어의 Catalog 자격, 채널 활성화, 공개 discovery URL, AI 추천·순위·매출을 검증하지 않는다.
- 수치 개선, 상위 노출, 자동 리뷰 연동은 측정·설정 근거가 없으면 성과로 기록하지 않는다.

## 공식 참고 문서 (검토 기준일 2026-10-21; 스토어 실행 증거 아님)
- https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/products
- https://help.shopify.com/en/manual/shopify-catalog/requirements
- https://help.openai.com/en/articles/11128490-shopping-with-chatgpt-search
- https://developers.google.com/search/docs/appearance/ai-features
"""
    master_note_path = OBSIDIAN_DIR / "00_REA_Shopify_AEO_Master_Hub.md"
    master_note_path.write_text(master_obsidian_note, encoding="utf-8")
    print(f"[로컬 검토 문서] {SHOPIFY_EXPORT_DIR / 'review'} (업로드 불가)")
    print(f"[로컬 검토 노트] {master_note_path} (설치·노출 미검증)")


def build_aeo_semantic_block(title: str, existing_html: str, product_type: str = "") -> str:
    """Compatibility no-op: raw identity/type do not authorize new product copy.

    This interface carries no product-bound accepted English display identity or
    canonical type from the existing copy-review pipeline. Do not promote Admin
    fields into a new FAQ or shopping preference, even if they look benign.
    Preserve all existing HTML, including legacy blocks, without endorsement.
    The shared shopping-copy helper remains for its evidence-bound callers;
    this inspection path deliberately does not invoke it or invent approval.
    """
    return existing_html or ""


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
    """Compatibility entry point: read-only observations, never upload candidates."""
    require_inspection_only()
    # Preserve original report keys, but do not label inspection as changes/done.
    REPORT.update(theme=None, assets=[], theme_liquid_patch="not_attempted_review_only",
                  products_seen=0, products_changed=[], products_already_done=0,
                  theme_inspection={}, products_review=[], publication_verified=False)
    try:
        token = resolve_token()
    except Exception as e:
        REPORT["errors"].append(f"token: {e}")
        print(f"[토큰 오류] {e}")
        return
    if not token:
        msg = "SHOPIFY_ADMIN_TOKEN 또는 SHOPIFY_CLIENT_ID/SECRET 없음 - 원격 API 호출 0건"
        REPORT["errors"].append(msg)
        print(f"[안내] {msg}. 로컬 검토 문서만 생성했습니다.")
        return

    print(f"[Shopify 점검] {STORE_DOMAIN} / GET 전용, 검토만")
    themes_resp = shopify_request("GET", "themes.json")
    main_theme = next((t for t in themes_resp.get("themes", []) if t.get("role") == "main"), None)
    if not main_theme:
        REPORT["errors"].append("활성(main) 테마 없음")
        return
    theme_id = main_theme["id"]
    REPORT["theme"] = {"id": theme_id, "name": main_theme.get("name")}
    try:
        response = shopify_request("GET", f"themes/{theme_id}/assets.json?asset[key]=layout/theme.liquid")
        value = response.get("asset", {}).get("value", "")
        REPORT["theme_inspection"] = {
            "source": "admin_api_layout_theme_liquid",
            "layout_nonempty": bool(value),
            "legacy_snippet_reference_observed": "ai-agent-schema" in value,
            "rendered_schema_verified": False,
            "public_output_verified": False,
            "status": "review_required",
        }
    except urllib.error.HTTPError as e:
        REPORT["errors"].append(f"theme inspection: HTTP {e.code}")
        REPORT["theme_inspection"] = {"status": "read_failed", "http_status": e.code}

    try:
        products = shopify_request("GET", "products.json?limit=50").get("products", [])
        REPORT["products_seen"] = len(products)
        for product in products:
            html = product.get("body_html") or ""
            title = product.get("title") or ""
            product_type = product.get("product_type") or ""
            status = "source_review_required"
            omissions = {"product_copy": "Raw Admin text is not accepted identity or canonical type; no candidate generated."}
            if "ai-semantic-summary" in html:
                status = "legacy_content_review_required"
                omissions["legacy_content"] = "Preserved without endorsement; manual evidence review required."
            REPORT["products_review"].append({
                "id": product["id"], "title": title, "status": status,
                "source": "admin_api_product_fields_unverified",
                "source_fields": {"title": title, "product_type": product_type},
                "facts_verified": False, "candidate_generated": False,
                "omission_reasons": omissions, "publication_allowed": False,
            })
        print(f"[상품 검토] {len(products)}건 관찰 (첫 페이지, 최대 50건). 실제 변경 0건.")
    except urllib.error.HTTPError as e:
        REPORT["errors"].append(f"products: HTTP {e.code}")
        print(f"[상품 점검 오류] HTTP {e.code}")


if __name__ == "__main__":
    require_inspection_only()
    write_local_assets()
    try:
        deploy_to_shopify_live()
    finally:
        write_report()
    sys.exit(1 if REPORT["errors"] and APPLY else 0)
