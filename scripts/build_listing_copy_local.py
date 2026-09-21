#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 상품의 누락 영문 카피를 무료·로컬 템플릿으로 보완한다.

기존 검증 카피는 그대로 보존한다. 현재 listing gate의 agent_ready 상품 중
카피가 없거나 예전 선행 게이트 때문에 건너뛴 상품만 처리한다. 제품명, 용량,
원산지처럼 정본에 있는 사실만 쓰며 효능·인증·임상 결과를 생성하지 않는다.
외부 API와 유료 모델은 호출하지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SRC = DATA / "daiso_real" / "shopify_s_recommendations.json"
GATE = DATA / "listing_gate.json"
OUT = DATA / "shopify_listing_copy.json"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def clean(value) -> str:
    return " ".join(str(value or "").split()).strip()


def brand_of(name: str) -> str:
    pairs = (
        ("VT", "VT"),
        ("본셉", "VONSEP"),
        ("셀더마데일리", "CELDERMA Daily"),
        ("메디필", "MEDI-PEEL"),
    )
    upper = name.upper()
    for token, brand in pairs:
        if token.upper() in upper:
            return brand
    return "K-Beauty"


def type_of(name: str) -> str:
    pairs = (
        ("바디괄사 세럼", "Body Serum"),
        ("슬리핑 마스크", "Sleeping Mask"),
        ("랩핑 마스크", "Wrapping Mask"),
        ("겔 마스크", "Gel Sheet Mask"),
        ("마스크", "Sheet Mask"),
        ("토너", "Face Toner"),
        ("앰플", "Face Ampoule"),
        ("세럼", "Face Serum"),
        ("크림", "Face Cream"),
        ("미스트", "Face Mist"),
    )
    for token, value in pairs:
        if token in name:
            return value
    return "Cosmetic"


def focus_of(name: str) -> str:
    values = []
    upper = name.upper()
    for token, label in (
        ("PDRN", "PDRN"),
        ("레티놀", "Retinol"),
        ("콜라겐", "Collagen"),
        ("히알론", "Hyaluron"),
        ("리들샷 300", "Reedle Shot 300"),
        ("리들샷 100", "Reedle Shot 100"),
    ):
        if token.upper() in upper and label not in values:
            values.append(label)
    return " ".join(values[:2])


def volume_of(gate_row: dict, name: str) -> str:
    gosi = gate_row.get("gosi") or {}
    label = gate_row.get("us_label") or {}
    volume = clean(label.get("net_contents") or gosi.get("volume"))
    if volume:
        return volume
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|g|매)(?:\s*[*x×]\s*\d+개입)?", name, re.I)
    return clean(match.group(0)) if match else ""


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:48]


def local_copy(name: str, gate_row: dict) -> dict:
    brand = brand_of(name)
    product_type = type_of(name)
    focus = focus_of(name)
    volume = volume_of(gate_row, name)
    title = " ".join(x for x in (brand, focus, product_type, volume) if x)
    title = title[:70].rstrip()
    size_text = f" in a {volume} size" if volume else ""
    description = (
        f"<p>{title} is a Korean beauty {product_type.lower()}{size_text}. "
        "This draft uses only the verified product identity and package information.</p>"
        "<p>Review the ingredient list, directions, and final US label before publication.</p>"
    )
    tags = [slug(x) for x in (brand, focus, product_type, "k-beauty", "korean-beauty") if slug(x)]
    tags = list(dict.fromkeys(tags))
    seo_description = (
        f"View {title}. Product identity and size are based on the source product notice. "
        "Review ingredients, directions, and the final label before purchase."
    )[:320]
    return {
        "title": title,
        "description_html": description,
        "seo_title": title,
        "seo_description": seo_description,
        "tags": tags,
        "product_type": product_type,
    }


def main() -> int:
    source = load(SRC, {})
    gate = load(GATE, {})
    previous = load(OUT, {})
    products = source.get("recommendations") or []
    gate_by = {str(x.get("pd_no") or x.get("product_id")): x
               for x in (gate.get("items") or []) if isinstance(x, dict)}
    old_by = {str(x.get("pd_no")): x
              for x in (previous.get("items") or []) if isinstance(x, dict)}

    items = []
    carried = generated = skipped = 0
    for product in products:
        pd_no = str(product.get("pd_no") or "")
        gate_row = gate_by.get(pd_no) or {}
        old = old_by.get(pd_no) or {}
        common = {
            "canonical_product_id": gate_row.get("canonical_product_id"),
            "pd_no": product.get("pd_no"),
            "name_ko": product.get("name"),
            "bucket": product.get("bucket"),
            "price_krw": product.get("price_krw"),
            "rating": product.get("rating"),
            "review_count": product.get("review_count"),
            "shopify_score": product.get("shopify_score"),
            "source_url": product.get("url"),
            "image_url": product.get("image_url"),
        }
        if not gate_row.get("agent_ready"):
            blocked = list(gate_row.get("agent_blocked_by") or ["ontology_gate_missing"])
            items.append({
                **common,
                "copy": None,
                "copy_status": "skipped_prerequisite",
                "generation_mode": "none",
                "agent_blocked_by": blocked,
                "error": "ontology 선행 게이트 미통과: " + ", ".join(blocked),
            })
            skipped += 1
            continue

        if old.get("copy_status") == "ok" and isinstance(old.get("copy"), dict):
            items.append({
                **common,
                "copy": old["copy"],
                "copy_status": "ok",
                "generation_mode": old.get("generation_mode") or "carried_verified_copy",
                "agent_blocked_by": [],
                "error": "",
            })
            carried += 1
            continue

        items.append({
            **common,
            "copy": local_copy(clean(product.get("name")), gate_row),
            "copy_status": "ok",
            "generation_mode": "deterministic_local_template_v1",
            "agent_blocked_by": [],
            "error": "",
        })
        generated += 1

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": now,
        "generator": "scripts/build_listing_copy_local.py",
        "model": "none_local_deterministic",
        "paid_api_called": False,
        "source": "data/daiso_real/shopify_s_recommendations.json",
        "note": (
            "기존 검증 카피를 보존하고 누락분만 제품명·용량·원산지 기반의 "
            "보수적 영문 초안으로 생성한다. 효능·인증·임상 결과는 생성하지 않는다."
        ),
        "total": len(items),
        "eligible": carried + generated,
        "ok": carried + generated,
        "failed": 0,
        "skipped_prerequisite": skipped,
        "carried_forward": carried,
        "generated_local": generated,
        "items": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"LOCAL_COPY_OK carried={carried} generated={generated} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
