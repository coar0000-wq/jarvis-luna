#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수출 서류를 사람이 채우기 전에 자동으로 채운다.

왜
  법률팀 카드가 "검토 0건 · 5항목 전부 대기" 였다. 그런데 대기하던 다섯
  항목 중 넷은 이미 저장소에 있는 값으로 채울 수 있다. 사람에게 물을 게
  아니라 먼저 채워놓고, 사람은 확인만 하면 된다.

    상품명    다이소 실수집분에 있다
    용도      버킷(스킨케어·마스크팩 등)으로 정해진다
    성분·재질  고시 전성분에 있다
    제조국    고시 제조국에 있다
    HS 코드   버킷과 이름으로 정해진다. 미국 공식 HTS 에서 받아온다
    라벨 시안  FDA 21 CFR 701 항목을 채워 만든다

  남는 건 사람이 최종 확인하는 일뿐이다.

HS 코드 출처
  hts.usitc.gov/reststop/search (미국 국제무역위원회 공식 검색)
  2026-09-06 에 실제로 호출해 아래를 확인했다.
    3304          기초화장품·메이크업
    3304.10.00.00 립 메이크업
    3304.20.00.00 눈 메이크업
    3304.30.00.00 매니큐어·페디큐어
    3305          두발용
    3305.10.00.00 샴푸
    3305.20.00.00 퍼머넌트
    3305.30.00.00 헤어 래커
    3303.00       향수·화장수
    3307          면도·데오드란트·목욕용
  세부 통계부호는 통관사가 최종 확인해야 한다. 여기서 정하는 건 후보다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEGAL = DATA / "legal_products.json"
GOSI = DATA / "gosi.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"
COPY = DATA / "shopify_listing_copy.json"
OUT = DATA / "legal_export_prep.json"
HTS = "https://hts.usitc.gov/reststop/search?keyword="
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

# 버킷 -> (HTS 후보, 검색어). 검색어로 공식 API 를 쳐서 설명을 받아온다.
BUCKET_HTS = {
    "스킨케어": ("3304.99", "beauty or make-up preparations"),
    "마스크팩": ("3304.99", "beauty or make-up preparations"),
    "클렌징": ("3304.99", "beauty or make-up preparations"),
    "선케어": ("3304.99", "beauty or make-up preparations"),
    "메이크업": ("3304.99", "beauty or make-up preparations"),
    "맨즈케어": ("3304.99", "beauty or make-up preparations"),
    "헤어케어": ("3305", "preparations for use on the hair"),
    "향수": ("3303.00", "perfumes and toilet waters"),
    "바디케어": ("3307", "personal deodorants and bath preparations"),
    "구강용품": ("3306", "preparations for oral or dental hygiene"),
}
# 이름에 이게 있으면 버킷보다 우선한다. 더 좁은 호가 있기 때문이다.
NAME_HTS = [
    (("립", "틴트", "립밤", "lip"), "3304.10.00.00", "립 메이크업"),
    (("아이섀도", "아이라이너", "마스카라", "eye"), "3304.20.00.00", "눈 메이크업"),
    (("샴푸", "shampoo"), "3305.10.00.00", "샴푸"),
    (("데오드란트", "deodorant"), "3307.20", "데오드란트"),
]

# FDA 화장품 라벨 필수 항목 (21 CFR 701 Subpart A / FPLA)
LABEL_FIELDS = [
    ("product_identity", "제품 정체 표시", "주표시면. 무엇인지 알 수 있는 이름이나 설명"),
    ("net_quantity", "내용량", "주표시면 하단 30% 안. 미터법과 야드파운드법 병기"),
    ("ingredients", "전성분", "정보표시면. INCI 명칭, 함량 내림차순, 1% 미만은 순서 무관"),
    ("responsible_party", "책임자 이름·주소", "제조자·포장자·유통자 중 하나. 도시·주·우편번호 포함"),
    ("country_of_origin", "원산지", "수입품은 Made in Korea 등 표기"),
    ("warnings", "경고 문구", "해당 시. 사용 중 이상 발생 시 사용 중단 등"),
]

# 미국에서 화장품에 흔히 붙는 경고. 실제로 붙일지는 성분에 달렸다.
STANDARD_WARNINGS = {
    "일반": ("If irritation occurs, discontinue use. Keep out of reach of children. "
           "For external use only."),
    "눈가": "Avoid direct contact with eyes. If contact occurs, rinse thoroughly with water.",
    "각질제거": ("Sunburn Alert: This product contains an alpha hydroxy acid (AHA) that "
              "may increase your skin's sensitivity to the sun and particularly the "
              "possibility of sunburn. Use a sunscreen and limit sun exposure."),
}
AHA_HINT = ("aha", "글라이콜릭", "글리콜산", "락틱", "젖산", "살리실", "bha", "pha")


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def hts_lookup(keyword: str, cache: dict) -> list[dict]:
    """공식 HTS 검색. 같은 검색어는 한 번만 부른다."""
    if keyword in cache:
        return cache[keyword]
    try:
        req = urllib.request.Request(HTS + urllib.parse.quote(keyword),
                                     headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError):
        cache[keyword] = []
        return []
    keep = [{"htsno": x.get("htsno"), "description": (x.get("description") or "")[:120]}
            for x in rows
            if str(x.get("htsno", "")).startswith(("3303", "3304", "3305", "3306",
                                                   "3307", "3401"))]
    cache[keyword] = keep
    time.sleep(1.5)
    return keep


def pick_hts(name: str, bucket: str, cache: dict) -> dict:
    low = (name or "").lower()
    for kws, code, label in NAME_HTS:
        if any(k in low for k in kws):
            return {"code": code, "basis": f"이름의 '{next(k for k in kws if k in low)}'",
                    "label": label, "official": hts_lookup(code, cache)}
    code, kw = BUCKET_HTS.get(bucket, ("3304.99", "beauty or make-up preparations"))
    rows = hts_lookup(kw, cache)
    desc = next((r["description"] for r in rows
                 if str(r["htsno"]).rstrip(".0") == code.rstrip(".0")), "")
    return {"code": code, "basis": f"버킷 '{bucket}'", "label": desc, "official": rows[:6]}


def build_label(name_en: str, gosi: dict, hs: dict) -> dict:
    """FDA 라벨 시안. 채울 수 있는 건 채우고, 빈 칸은 무엇이 없어서인지 적는다."""
    draft, missing = {}, []
    vals = {
        "product_identity": name_en or "",
        "net_quantity": (gosi.get("volume") or "").strip(),
        "ingredients": (gosi.get("ingredients") or "").strip(),
        "responsible_party": "",          # MoCRA 책임자. 사람이 정한다.
        "country_of_origin": (gosi.get("origin") or "").strip(),
        "warnings": "",
    }
    ing_low = vals["ingredients"].lower()
    w = [STANDARD_WARNINGS["일반"]]
    if any(k in ing_low for k in AHA_HINT):
        w.append(STANDARD_WARNINGS["각질제거"])
    vals["warnings"] = " ".join(w)

    for key, ko, rule in LABEL_FIELDS:
        v = vals.get(key, "")
        draft[key] = {"label": ko, "value": v, "rule": rule}
        if not v:
            missing.append(ko)
    return {"draft": draft, "missing": missing,
            "note": ("전성분은 한글이다. 미국 라벨에는 INCI 영문명이 필요하다. "
                     "번역이 아니라 표준 명칭 대조라서 사람이 확인해야 한다."),
            "inci_status": "korean_only" if vals["ingredients"] else "no_ingredients"}


def main() -> int:
    legal = load(LEGAL) or {}
    gosi = (load(GOSI) or {}).get("items") or {}
    score = load(SCORE) or {}
    items = legal.get("items") or {}
    by_no = {str(r.get("pd_no")): r for r in (score.get("all_scored") or [])}
    # 라벨의 '제품 정체 표시' 는 영문 상품명이다. 리스팅팀이 이미 만들어
    # 놨는데 법률팀이 빈칸으로 두고 사람을 기다리고 있었다. 연결한다.
    copy_by_no = {str(i.get("pd_no")): (i.get("copy") or {})
                  for i in ((load(COPY) or {}).get("items") or [])}

    cache: dict = {}
    rows, filled = [], 0
    for pd_no, li in items.items():
        s = by_no.get(str(pd_no)) or {}
        g = gosi.get(str(pd_no)) or {}
        name = li.get("name") or s.get("name") or ""
        bucket = s.get("bucket") or ""
        hs = pick_hts(name, bucket, cache)
        cp = copy_by_no.get(str(pd_no)) or {}
        label = build_label(cp.get("title") or "", g, hs)

        # 사람이 이미 적은 HS 코드는 건드리지 않는다.
        if not (li.get("hs_code") or "").strip():
            li["hs_code"] = hs["code"]
            li["hs_basis"] = hs["basis"]
            li["hs_source"] = "hts.usitc.gov/reststop (미국 공식)"
            filled += 1

        rows.append({
            "pd_no": pd_no,
            "name": name,
            "bucket": bucket,
            "grade": s.get("grade"),
            "용도": bucket or "미상",
            "성분": (g.get("ingredients") or "")[:200],
            "제조국": g.get("origin") or "",
            "내용량": g.get("volume") or "",
            "제조업자": g.get("maker") or "",
            "name_en": cp.get("title") or "",
            "product_type_en": cp.get("product_type") or "",
            "hs": hs,
            "label": label,
            "hard_block": li.get("hard_block", False),
            "hard_block_reason": li.get("hard_block_reason", ""),
        })

    done = [r for r in rows if not r["label"]["missing"]]
    need_person = sorted({m for r in rows for m in r["label"]["missing"]})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/prepare_legal_export.py",
        "왜": ("법률팀이 '검토 0건, 5항목 대기' 였는데 그 다섯 중 넷은 이미 저장소에 "
              "있는 값으로 채울 수 있었다. 먼저 채우고 사람은 확인만 한다."),
        "hs_출처": "hts.usitc.gov/reststop/search (미국 국제무역위원회 공식)",
        "hs_주의": "여기서 정하는 건 후보다. 세부 통계부호는 통관사가 확정해야 한다.",
        "label_기준": "FDA 21 CFR 701 Subpart A / FPLA",
        "total": len(rows),
        "hs_filled_this_run": filled,
        "label_complete": len(done),
        "사람이_채워야_하는_칸": need_person,
        "items": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for target, body in ((OUT, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"),
                         (LEGAL, json.dumps(legal, ensure_ascii=False, indent=2) + "\n")):
        for _ in range(4):
            target.write_text(body, encoding="utf-8")
            try:
                json.loads(target.read_text(encoding="utf-8-sig"))
                break
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                time.sleep(0.5)
        else:
            print(f"기록 검증 실패 {target.name}", file=sys.stderr)
            return 1

    print(f"수출 준비 {len(rows)}건 · HS 코드 이번에 {filled}건 채움")
    print(f"라벨 6항목 모두 채워진 상품 {len(done)}/{len(rows)}")
    if need_person:
        print("사람이 채워야 하는 칸:", ", ".join(need_person))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
