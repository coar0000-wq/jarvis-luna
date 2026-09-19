#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MoCRA 준수 준비 상태를 상품이 아니라 '사업' 단위로 판정한다.

왜 만들었나 (2026-09-19)

  법률팀 산출물은 상품별 판정만 있었다. legal_products.json 은 금지 성분·
  OTC 선크림·기능성 문구·영문 라벨 4가지를 상품마다 본다. 좋은 검사지만
  MoCRA 가 요구하는 것은 그게 전부가 아니다.

  MoCRA 는 사업자에게 이런 것을 요구한다.

    ① 책임자(Responsible Person) 지정        라벨에 이름·주소가 들어간다
    ② 시설 등록(Facility Registration)       제조시설이 2년마다 갱신
    ③ 제품 리스팅(Product Listing)           연 1회 FDA 에 제품·성분 제출
    ④ 안전성 입증(Safety Substantiation)     제품별 과학적 근거 보유
    ⑤ 유해사례 보고 + 라벨의 미국 내 연락처   중대 사례는 15일 이내
    ⑥ GMP · 강제회수 대응 체계

  소규모 면제(미국 내 화장품 매출 직전 3년 평균 100만 달러 미만)는 다음 셋을 면제한다.
    ② 시설 등록   ③ 제품 리스팅   ⑥ GMP
  반대로 면제되지 않는 것은 ① 책임자·라벨 연락처, ④ 안전성 입증,
  ⑤ 유해사례 기록과 15영업일 보고다. (FDA MoCRA 안내 · 21 U.S.C. 364e)

  눈 점막 접촉·주사·체내 삽입·24시간 이상 지속 제품을 다루면 소규모여도
  면제가 없어진다.

  라벨 연락처는 미국 주소만 가능한 것이 아니다. 21 U.S.C. 364e 는
  "domestic address, domestic phone number, or electronic contact information,
  which may include a website" 라고 적어 있다. 즉 유해사례를 받을 수 있는
  웹사이트로도 된다. 해외 주소·해외 전화만 적은 것은 안 된다.
  책임자 자체는 미국 밖에 있어도 된다. US Agent 는 시설 등록을 하는
  해외 시설에 붙는 의무라, 등록이 면제되면 사야 할 이유가 없다.

  이 판정을 사람 기억에만 두면 "준비됐나?" 라는 질문에 매번 다르게 답하게
  된다. 입력 파일과 실제 산출물을 보고 기계가 같은 답을 내도록 한다.

입력
  data/manual/mocra_profile.json            사업 프로필 (없으면 미설정으로 본다)
  data/manual/legal_responsible_person.json 책임자 실값 (공개 저장소에서 제외됨)
  data/legal_full.json                      상품별 라벨 필드
  data/product_master.json                  S등급 상품 분류
  data/listing_gate.json                    판매 후보 범위

출력
  data/mocra_readiness.json

원칙
  준비됐다고 스스로 선언하지 않는다. 근거가 있는 항목만 ready 로 둔다.
  이 파일은 법률 자문이 아니다. 무엇이 남았는지 보여주는 점검표다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "mocra_readiness.json"
PROFILE = D / "manual" / "mocra_profile.json"
RP_FILE = D / "manual" / "legal_responsible_person.json"

# 소규모 면제에서 빠지는 제품군. 한국어 분류·상품명에서 찾는다.
EXCLUDED_KEYWORDS = {
    "eye_mucous": ("아이라이너", "마스카라", "아이섀도", "eye liner", "mascara",
                   "eyeshadow", "아이메이크업", "속눈썹"),
    "injected": ("주사", "인젝션", "inject"),
    "internal": ("체내", "삽입", "insert"),
    "long_wear": ("24시간", "롱웨어", "long wear", "long-wear", "문신", "타투"),
}


def load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def filled(value: Any) -> bool:
    return bool(str(value or "").strip())


def check(check_id: str, label: str, ready: bool, detail: str,
          exempt: bool = False, evidence: str = "") -> dict:
    return {
        "id": check_id,
        "label": label,
        "status": "exempt" if exempt else ("ready" if ready else "not_ready"),
        "detail": detail,
        "evidence": evidence,
    }


def main() -> int:
    profile = load(PROFILE, {}) or {}
    rp_manual = load(RP_FILE, {}) or {}
    legal_full = load(D / "legal_full.json", {}) or {}
    gate = load(D / "listing_gate.json", {}) or {}
    master = load(D / "product_master.json", {}) or {}

    items = legal_full.get("items") or {}
    gate_items = [x for x in (gate.get("items") or []) if isinstance(x, dict)]
    scope_ids = {str(x.get("pd_no")) for x in gate_items}
    products = [p for p in (master.get("products") or [])
                if str(p.get("pd_no")) in scope_ids]

    # 소규모 면제 제외 품목이 판매 범위에 있는지 먼저 본다.
    excluded_hits: list[dict] = []
    for p in products:
        text = " ".join(str(p.get(k) or "") for k in ("name_ko", "category", "brand")).lower()
        for reason, words in EXCLUDED_KEYWORDS.items():
            if any(w.lower() in text for w in words):
                excluded_hits.append({"pd_no": str(p.get("pd_no")),
                                      "name": p.get("name_ko"), "reason": reason})
                break

    revenue = profile.get("annual_revenue_usd")
    revenue_known = isinstance(revenue, (int, float))
    small_business = bool(revenue_known and revenue < 1_000_000 and not excluded_hits)

    checks: list[dict] = []

    # ① 책임자 지정 -------------------------------------------------------
    rp_fields = ("name", "address", "email", "phone")
    rp_source = rp_manual if any(filled(rp_manual.get(f)) for f in rp_fields) else \
        (legal_full.get("responsible_person") or {})
    rp_missing = [f for f in rp_fields if not filled(rp_source.get(f))]
    checks.append(check(
        "responsible_person",
        "책임자(Responsible Person) 지정과 라벨 표기",
        not rp_missing,
        "모든 항목 확보" if not rp_missing else f"미입력: {', '.join(rp_missing)}",
        evidence="data/manual/legal_responsible_person.json",
    ))

    # ② 시설 등록 ---------------------------------------------------------
    facility = profile.get("facility_registration") or {}
    fac_role = str(profile.get("role") or "").strip()
    fac_ready = bool(facility.get("registered") is True and filled(facility.get("verified_at")))
    if small_business:
        fac_detail = "연매출 100만 달러 미만 소규모로 등록 의무 면제 범위"
    elif fac_ready:
        fac_detail = f"등록 확인 {facility.get('verified_at')}"
    elif fac_role == "reseller":
        fac_detail = ("재판매자는 직접 제조하지 않는다. 다만 수입 제품의 제조시설이 "
                      "등록돼 있는지 확인한 기록이 필요하다")
    else:
        fac_detail = "제조시설 등록 여부 미확인"
    checks.append(check(
        "facility_registration", "제조시설 등록(2년 주기 갱신)",
        fac_ready, fac_detail, exempt=small_business,
        evidence="data/manual/mocra_profile.json",
    ))

    # ③ 제품 리스팅 -------------------------------------------------------
    listing = profile.get("product_listing") or {}
    listing_ready = bool(listing.get("submitted") is True and filled(listing.get("last_submitted_at")))
    if small_business:
        listing_detail = ("소규모 면제 범위 · 자발 리스팅은 가능하다")
    elif listing_ready:
        listing_detail = f"최종 제출 {listing.get('last_submitted_at')}"
    else:
        listing_detail = "제출 기록 없음"
    checks.append(check(
        "product_listing", "FDA 제품 리스팅(연 1회 갱신)",
        listing_ready, listing_detail, exempt=small_business,
        evidence="data/manual/mocra_profile.json",
    ))

    # ④ 안전성 입증 -------------------------------------------------------
    substantiation = profile.get("safety_substantiation") or {}
    covered = {str(x) for x in (substantiation.get("covered_pd_nos") or [])}
    missing_sub = sorted(scope_ids - covered)
    checks.append(check(
        "safety_substantiation", "제품별 안전성 입증 자료 보유",
        bool(scope_ids) and not missing_sub,
        "판매 후보 전부 확보" if scope_ids and not missing_sub
        else f"미확보 {len(missing_sub)}건: {', '.join(missing_sub[:5])}"
             + (" 외" if len(missing_sub) > 5 else ""),
        evidence="data/manual/mocra_profile.json",
    ))

    # ⑤ 유해사례 접수 체계 -------------------------------------------------
    adverse = profile.get("adverse_event") or {}
    us_contact = adverse.get("us_contact") or {}
    contact_type = str(us_contact.get("type") or "").strip().lower()
    # 미국 주소·미국 전화·전자 연락처(웹사이트) 셋 중 하나면 된다.
    # 한국 주소나 한국 번호만 적은 것은 요건을 채우지 못한다.
    ALLOWED_CONTACT = {"domestic_address", "domestic_phone", "website", "url",
                       "electronic", "email"}
    contact_ok = filled(us_contact.get("value")) and contact_type in ALLOWED_CONTACT
    process_ok = bool(adverse.get("process_documented") is True)
    label_products = [k for k, row in items.items()
                      if filled((row.get("responsible_person") or {}).get("address")
                                if isinstance(row.get("responsible_person"), dict) else "")]
    checks.append(check(
        "adverse_event", "유해사례 접수용 미국 내 연락처와 15일 보고 절차",
        contact_ok and process_ok,
        ("연락처·절차 확보" if contact_ok and process_ok else
         f"연락처 {'있음' if contact_ok else '없음(미국 주소·미국 전화·웹사이트 중 택 1)'}"
         f" · 절차 문서 {'있음' if process_ok else '없음'}"),
        evidence=f"라벨에 주소가 들어간 상품 {len(label_products)}/{len(items)}건",
    ))

    # ⑥ GMP·회수 대응 -----------------------------------------------------
    gmp = profile.get("gmp") or {}
    gmp_ready = bool(gmp.get("supplier_gmp_confirmed") is True
                     and filled(gmp.get("recall_contact")))
    checks.append(check(
        "gmp_recall", "GMP 확인과 강제 회수 대응 창구",
        gmp_ready,
        "공급자 GMP 확인·회수 창구 지정" if gmp_ready
        else "공급자 GMP 확인 또는 회수 담당 연락처 미지정",
        exempt=small_business and not excluded_hits,
        evidence="data/manual/mocra_profile.json",
    ))

    # ⑦ 라벨 필수 항목 (상품 산출물에서 직접 계산) -------------------------
    label_blockers = {}
    for pid, row in items.items():
        for b in row.get("blockers") or []:
            label_blockers[b] = label_blockers.get(b, 0) + 1
    complete = sum(1 for row in items.values() if row.get("complete"))
    checks.append(check(
        "label_fields", "영문 라벨 필수 항목(성분·용량·책임자·사용법·주의사항)",
        bool(items) and complete == len(items),
        f"완비 {complete}/{len(items)}건 · 부족 항목 "
        + (", ".join(f"{k} {v}건" for k, v in sorted(label_blockers.items())) or "없음"),
        evidence="data/legal_full.json",
    ))

    ready_count = sum(1 for c in checks if c["status"] == "ready")
    exempt_count = sum(1 for c in checks if c["status"] == "exempt")
    blocking = [c["label"] for c in checks if c["status"] == "not_ready"]

    output = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "면책": "법률 자문이 아니다. 무엇이 남았는지 보여주는 점검표다.",
        "기준": "MoCRA (Modernization of Cosmetics Regulation Act of 2022)",
        "profile_present": PROFILE.exists(),
        "profile_hint": "data/manual/mocra_profile.example.json 을 복사해 채우세요",
        "business": {
            "role": profile.get("role") or "",
            "annual_revenue_usd": revenue if revenue_known else None,
            "revenue_known": revenue_known,
            "small_business_exemption": small_business,
            "small_business_note": (
                "미국 내 화장품 매출 직전 3년 평균 100만 달러 미만이면 "
                "시설 등록·제품 리스팅·GMP 가 면제된다. "
                "책임자 라벨 연락처·안전성 입증·유해사례 기록과 15영업일 보고는 "
                "면제되지 않는다."),
            "근거": [
                "FDA MoCRA 안내 · Exemptions (시설 등록·제품 리스팅·GMP 면제)",
                "21 U.S.C. 364e · 라벨은 미국 주소·미국 전화 또는 웹사이트를 포함한 "
                "전자 연락처 중 하나를 실어야 한다",
            ],
            "exemption_excluded_products": excluded_hits,
        },
        "scope": {
            "판매_후보": len(scope_ids),
            "법률_점검_대상": len(items),
            "라벨_완비": complete,
        },
        "ready_count": ready_count,
        "exempt_count": exempt_count,
        "total_checks": len(checks),
        "sales_allowed": not blocking,
        "blocking": blocking,
        "checks": checks,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"MoCRA 준비 {ready_count}/{len(checks)} (면제 {exempt_count}) · "
          f"남은 항목 {len(blocking)}건 · 판매 가능 {output['sales_allowed']}")
    for c in checks:
        mark = {"ready": "OK  ", "exempt": "면제", "not_ready": "남음"}[c["status"]]
        print(f"  {mark} {c['label']} — {c['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
