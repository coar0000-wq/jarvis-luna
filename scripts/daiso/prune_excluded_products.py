#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이미 쌓인 상품 목록에서 제외 규칙에 걸리는 것을 걷어낸다.

왜 필요한가 (2026-09-13)

  오늘 category_map.json 의 exclude 에 FDA 의약품 네 갈래를 넣었다.
  불소치약·구강, 항균세정, 비듬·탈모, 땀억제데오 다.

  큐는 그 규칙으로 걸렀다. 그런데 이미 수집된 products.json 222건은
  그대로 뒀다. 규칙을 바꾸면서 과거 자료를 안 맞춘 것이다.

  그래서 audit_team_reports.py 가 푸시 직전에 막았다.

    FAIL 제외 대상이 상품 목록에 10건 남아 있다:
         불소치약·구강/2080 닥터크리닉 잇몸 치약 120 g, ...
    Error: 팀 보고 숫자 감사 실패.
    Error: 원격 main에는 아직 푸시하지 않는다.

  감사가 제 일을 한 것이다. 워크플로 네 개가 전부 이 관문에서 멈췄다.
  Deep Analysis, 핵심 자동화, 참모장 자동수정, 그리고 방금 만든 고시 alt 수집기.

왜 손으로 지우지 않나

  누가 만들어 준 정리본을 받아 덮으면 이번은 넘어간다.
  그런데 다음에 규칙을 또 바꾸면 같은 일이 또 난다.
  그때도 사람이 손으로 지워야 한다.

  그래서 사전을 읽어 같은 규칙으로 거른다.
  category_map.json 을 고치면 이 스크립트가 알아서 따라간다.
  지울 목록을 코드에 박지 않는다.

무엇을 지우고 무엇을 남기나

  products.json 에서 뺀다. 그 파일이 점수와 감사의 원천이다.
  뺀 것은 지우지 않고 excluded_products.json 에 사유와 함께 남긴다.
  규칙이 다시 바뀌어 되살려야 할 때 근거가 필요하다.

쓰는 법
  python scripts/daiso/prune_excluded_products.py          걸리는 것만 보여준다
  python scripts/daiso/prune_excluded_products.py --apply  실제로 뺀다
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PRODUCTS = DATA / "daiso_real" / "products.json"
PARKED = DATA / "daiso_real" / "excluded_products.json"
CATMAP = Path(__file__).with_name("category_map.json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def exclude_rules(catmap: dict) -> list[tuple[str, str]]:
    """(제외이름, 키워드) 목록. 밑줄로 시작하는 설명 칸은 건너뛴다."""
    out = []
    for label, spec in (catmap.get("exclude") or {}).items():
        if str(label).startswith("_") or not isinstance(spec, dict):
            continue
        for kw in spec.get("keywords") or []:
            kw = str(kw).strip()
            if kw:
                out.append((label, kw))
    return out


def hit(row: dict, rules: list[tuple[str, str]]) -> tuple[str, str] | None:
    hay = " ".join(str(row.get(k) or "") for k in
                   ("name", "site_category", "bucket")).lower()
    for label, kw in rules:
        if kw.lower() in hay:
            return label, kw
    return None


def main() -> int:
    apply = "--apply" in sys.argv

    catmap = load(CATMAP, {})
    rules = exclude_rules(catmap)
    if not rules:
        print("category_map.json 의 exclude 를 못 읽었다. 아무것도 안 한다.")
        return 1
    print(f"제외 규칙 {len(rules)}개 "
          f"({len({l for l, _ in rules})}갈래)")

    doc = load(PRODUCTS, {})
    rows = doc.get("products")
    if not isinstance(rows, list):
        print("products.json 의 products 가 배열이 아니다.")
        return 1
    print(f"상품 목록 {len(rows)}건")

    keep, drop = [], []
    for r in rows:
        if not isinstance(r, dict):
            keep.append(r)
            continue
        m = hit(r, rules)
        if m:
            drop.append((r, m[0], m[1]))
        else:
            keep.append(r)

    by_label: dict[str, int] = {}
    for _, label, _kw in drop:
        by_label[label] = by_label.get(label, 0) + 1

    print(f"\n걸린 것 {len(drop)}건")
    for label, n in sorted(by_label.items(), key=lambda x: -x[1]):
        print(f"  {n:>3}건  {label}")
    print()
    for r, label, kw in drop:
        print(f"  [{label}] '{kw}' — {str(r.get('pd_no')):<14} "
              f"{str(r.get('name'))[:40]}")

    if not drop:
        print("\n걸리는 것이 없다. 감사를 통과한다.")
        return 0

    if not apply:
        print(f"\n--apply 를 붙이면 {len(rows)} → {len(keep)} 로 줄인다. "
              "지금은 보기만 했다.")
        return 0

    parked = load(PARKED, {})
    if not isinstance(parked, dict):
        parked = {}
    items = parked.get("items")
    if not isinstance(items, dict):
        items = {}

    for r, label, kw in drop:
        pid = str(r.get("pd_no") or r.get("product_id") or "")
        if not pid:
            continue
        items[pid] = {
            "name": r.get("name"),
            "뺀_규칙": label,
            "걸린_낱말": kw,
            "왜": ((catmap.get("exclude") or {}).get(label) or {}).get("why", ""),
            "뺀_시각": now(),
            "row": r,
        }

    parked.update({
        "generated_at": now(),
        "generator": "scripts/daiso/prune_excluded_products.py",
        "왜_남기나": (
            "규칙이 다시 바뀌어 되살려야 할 때 근거가 필요하다. "
            "지우면 왜 뺐는지도 같이 사라진다."
        ),
        "규칙_출처": "scripts/daiso/category_map.json 의 exclude",
        "count": len(items),
        "items": items,
    })
    PARKED.write_text(json.dumps(parked, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")

    doc["products"] = keep
    doc["count"] = len(keep)
    doc["updated_at"] = now()
    doc["제외_정리"] = {
        "ran_at": now(),
        "전": len(rows), "후": len(keep), "뺀_건수": len(drop),
        "갈래별": by_label,
        "규칙": "scripts/daiso/category_map.json 의 exclude",
        "보관": "data/daiso_real/excluded_products.json",
        "왜": ("FDA 가 의약품으로 보는 갈래와 배송 제약 갈래는 못 판다. "
              "못 파는 것이 상품 목록에 남아 있으면 점수와 팀 보고가 "
              "그것을 세고, 푸시 직전 감사가 막는다."),
    }
    PRODUCTS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    print(f"\n{'=' * 56}")
    print(f"상품 목록 {len(rows)} → {len(keep)}건 ({len(drop)}건 뺌)")
    print(f"뺀 것은 {PARKED.relative_to(ROOT)} 에 사유와 함께 보관")
    print(f"{'=' * 56}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
