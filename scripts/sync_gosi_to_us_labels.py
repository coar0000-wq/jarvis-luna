#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한국 고시를 미국 영문 라벨로 끝까지 옮긴다.

읽는 곳  data/gosi.json
        data/inci_dictionary.json
쓰는 곳  data/daiso_real/daiso_us_labels.json

왜 다시 썼나 (2026-09-13)

  게이트가 등록 가능 0/7 이었다. 파고 보니 세 군데가 물려 있었다.

  1. 안내문을 값으로 봤다

     라벨 파일 7건이 전부 이랬다.

       "ingredients_inci": "실제 제품 포장에 기재된 전체 INCI 성분",
       "manufacturer": "실제 포장에 기재된 제조사",

     사람이 나중에 채우라고 넣어 둔 안내문이다. 그런데 옛 코드가
     "빈 칸만 채운다" 는 규칙이라 이걸 값이 있는 것으로 봤다.
     그래서 영원히 안 채웠다.

  2. gosi_ok 가 안내문에 속았다

       target["gosi_ok"] = all(text(target.get(f)) for f in REQUIRED)

     안내문도 글자라서 True 가 됐다. 그 플래그를 보고 다음 단계가
     "라벨 준비됨" 이라고 믿었다. 거짓 안심이다.

  3. 전성분을 옮길 길이 아예 없었다

     옛 코드는 소스에 ingredients_inci 가 이미 영문으로 있고
     ingredients_language 가 en 일 때만 채웠다. 고시는 한국어라
     그 조건이 참이 될 수 없다. 구조적 교착이었다.

     한국어를 영문 INCI 로 바꾸는 사전은 inci_converter.py 안에
     113개나 있었다. 그런데 그 파일은 data/daiso_real/daiso_gosi.json
     을 읽는데 그 파일이 존재하지 않는다. 사전이 한 번도 쓰인 적이 없다.

  그래서 이 스크립트 하나가 고시에서 영문 라벨까지 끝까지 책임진다.
  중간에 다른 파일로 넘기지 않는다. 넘기는 자리마다 끊겼다.

지어내지 않는다

  사전에 없는 성분은 비워 두고 못_옮긴_성분 에 남긴다.
  INCI 는 국제 표준 표기라 지어내면 미국에서 라벨 위반이다.
  전성분은 하나라도 빠지면 못 쓰므로, 한 성분이라도 못 옮기면
  그 상품의 ingredients_inci 는 채우지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inci_resolver import InciResolver, load_manual_overrides  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

GOSI = DATA / "gosi.json"
DICT = DATA / "inci_dictionary.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"

REQUIRED_LABEL_FIELDS = (
    "net_contents",
    "ingredients_inci",
    "manufacturer",
    "country_of_origin",
)

# 이 스크립트가 고시에서 옮겨 쓰는 칸이다. 사람이 넣는 칸은 여기 없다.
MACHINE_FIELDS = (
    "product_name_kr",
    "net_contents",
    "manufacturer",
    "country_of_origin",
    "ingredients_inci",
)

# 사람이 나중에 채우라고 넣어 둔 안내문. 값이 아니라 빈 칸으로 본다.
# build_listing_gate.py 의 _PLACEHOLDER_RE 와 같은 규칙을 쓴다.
# 두 곳이 다르면 한쪽은 통과시키고 한쪽은 막아서 원인을 못 찾는다.
PLACEHOLDER_RE = re.compile(
    r"(실제\s*확인|실제\s*포장|실제\s*제품|실제\s*상품|placeholder|TODO|TBD"
    r"|미입력|확인\s*필요|작성\s*필요|상세페이지\s*참조)",
    re.I,
)

ORIGIN_EN = {
    "대한민국": "Korea",
    "한국": "Korea",
    "korea": "Korea",
    "republic of korea": "Korea",
    "중국": "China",
    "일본": "Japan",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"JSON 읽기 실패: {path}: {exc}") from exc


def text(value: Any) -> str:
    return str(value or "").strip()


def real(value: Any) -> bool:
    """값이 실제 값인가. 안내문이면 빈 칸으로 본다."""
    s = text(value)
    if not s:
        return False
    return not PLACEHOLDER_RE.search(s)


def split_ingredients(raw: str) -> list[str]:
    """한국어 전성분을 성분 단위로 나눈다.

    1,2-헥산다이올 처럼 이름 안에 쉼표가 든 성분이 있다.
    그래서 그냥 쉼표로 자르면 두 조각이 난다. 먼저 보호한다.
    """
    s = text(raw)
    if not s:
        return []

    # 고시 원문에는 성분이 아닌 것이 섞여 들어온다 (2026-09-13).
    # 이런 것들을 성분 이름으로 알고 사전을 뒤지다 못 찾아서 상품이 막혔다.
    #   "베타-글루칸\n\n구) 정제수"
    #   "향료\n* 제품 리뉴얼로 전성분이 일부 변경되었습니다"
    # 사전에 없는 성분이 아니라 내 파서가 덜 다듬은 것이었다.
    s = "\n".join(l for l in s.split("\n")
                  if not l.strip().startswith(("*", "※")))

    # 숫자,숫자 형태의 쉼표는 성분 이름 안의 것이다
    s = re.sub(r"(\d),(\d)", r"\1\2", s)
    parts = []
    # 줄바꿈도 성분 구분이다. 쉼표만 보면 두 성분이 한 덩이로 붙는다.
    for chunk in re.split(r"[,·\n]", s):
        c = chunk.replace("", ",").strip()
        # 괄호 안 비율 표기는 INCI 에 넣지 않는다
        c = re.sub(r"\([^)]*\)", "", c).strip()
        # 구) 신) 같은 개정 표기가 앞에 붙는다
        c = re.sub(r"^[구신]\s*\)\s*", "", c).strip()
        c = c.strip(" .;·")
        if c:
            parts.append(c)
    return parts


def _nospace(s: str) -> str:
    return re.sub(r"\s+", "", s)


_NOSPACE_CACHE: dict[int, dict] = {}


def nospace_index(table: dict) -> dict:
    """공백을 둔 색인을 한 번만 만든다.

    정본은 학명을 속과 종 사이에 공백을 두고 적는다.
      정본   '클로렉라 불가리스추출물'
      라벨   '클로렉라불가리스추출물'
    제조사가 공백을 빼고 인쇄하는 일이 흔하다. 그것 하나 때문에
    상품 하나가 통째로 막혔다. 같은 성분을 못 찾은 것이지 사전에
    없던 것이 아니다.

    공백만 무시한다. 다른 글자는 건드리지 않는다. 임의로 닮은 것을
    찾아 이으면 다른 성분을 적게 된다.
    """
    key = id(table)
    idx = _NOSPACE_CACHE.get(key)
    if idx is None:
        idx = {}
        for k, v in table.items():
            idx.setdefault(_nospace(k), v)
        _NOSPACE_CACHE[key] = idx
    return idx


def to_inci(raw: str, resolver: InciResolver) -> tuple[str, list[str], list[dict], list[dict]]:
    """한국어 전성분을 영문 INCI 로 바꾼다.

    하나라도 정본으로 못 이으면 빈 문자열을 돌려준다.
    일부만 영문인 성분표는 쓸 수 없다. 미국에서 라벨 위반이다.

    그대로 못 찾으면 공백, 표기 규칙, 한두 글자 차이, 앞뒤 순서까지
    본다. 판단은 inci_resolver 가 하고 여기서는 결과만 모은다.
    지어내는 것이 아니라 같은 이름을 알아보는 것이다. 되돌린 자리는
    전부 남겨 사람이 뒤집을 수 있게 한다.
    """
    parts = split_ingredients(raw)
    if not parts:
        return "", [], [], []

    out: list[str] = []
    missing: list[str] = []
    fixed: list[dict] = []
    review: list[dict] = []

    for p in parts:
        r = resolver.resolve(p)
        if r.ok:
            out.append(r.value)
            if r.method not in ("exact", "nospace"):
                fixed.append(r.as_record())
            continue
        missing.append(p)
        review.append(r.as_record())

    if missing:
        return "", missing, fixed, review
    return ", ".join(out), [], fixed, review


def main() -> int:
    gosi_doc = load_json(GOSI, {})
    labels = load_json(LABELS, {})
    dict_doc = load_json(DICT, {})

    table = dict_doc.get("kr_to_inci") or {}
    if not table:
        print("INCI 사전이 비어 있다. data/inci_dictionary.json 을 확인한다.")
    overrides = load_manual_overrides(ROOT)
    resolver = InciResolver(table, overrides)
    if overrides:
        print(f"사람이 확인한 표기 {len(overrides)}건을 먼저 볼 것이다.")

    items = gosi_doc.get("items") or {}
    if isinstance(items, list):
        items = {str(r.get("product_id")): r for r in items
                 if isinstance(r, dict) and r.get("product_id")}
    if not isinstance(items, dict):
        raise RuntimeError("data/gosi.json 의 items 형태가 잘못됐다")
    if not isinstance(labels, dict):
        raise RuntimeError("daiso_us_labels.json 은 object 여야 한다")

    if "items" in labels and isinstance(labels.get("items"), dict):
        registry = labels["items"]
        wrapped = True
    else:
        registry = labels
        wrapped = False

    now = datetime.now(timezone.utc).isoformat()
    filled, replaced, complete = 0, 0, 0
    missing_all: dict[str, list[str]] = {}
    fixed_all: dict[str, list[dict]] = {}
    review_all: dict[str, list[dict]] = {}
    report = []

    for raw_id, source in items.items():
        if not isinstance(source, dict):
            continue
        pd_no = str(source.get("product_id") or raw_id)
        target = registry.setdefault(pd_no, {})

        # 이 스크립트가 채운 칸을 적어 둔다.
        #
        # 예전에는 "값이 있으면 안 덮는다" 만 있었다. 그러면 사람이 확인한
        # 값은 지켜지지만, 기계가 예전 고시로 채운 값도 같이 남는다. 고시가
        # 다시 수집돼 더 정확해져도 라벨은 옛말을 하고 있었다.
        # 이제 기계가 채운 칸은 적어 두고, 원문이 바뀜 때만 다시 쓴다.
        # 사람이 넣은 칸은 이 목록에 없으므로 여전히 건드리지 않는다.
        derived = target.get("_자동으로_채운_칸")
        if not isinstance(derived, list):
            # 목록이 생기기 전에 만든 기록을 한 번 메운다.
            # source_type 이 고시이고 사람이 넣는 칸(책임자·사용법 등)이
            # 하나도 없으면 이 스크립트가 쓴 기록이다.
            derived = []
            if target.get("source_type") == "daiso_product_notice":
                derived = [f for f in MACHINE_FIELDS if text(target.get(f))]

        def put(key: str, value: str) -> None:
            """실제 값이 있고 지금 칸이 비었거나 안내문이면 채운다."""
            nonlocal filled, replaced
            if not text(value):
                return
            cur = target.get(key)
            if real(cur) and key not in derived:
                return                      # 사람이 확인한 값은 안 건드린다
            if text(cur) == text(value):
                if key not in derived:
                    derived.append(key)
                return
            was_placeholder = bool(text(cur)) and not real(cur)
            target[key] = text(value)
            if key not in derived:
                derived.append(key)
            if was_placeholder:
                replaced += 1
            else:
                filled += 1

        put("product_name_kr", source.get("name"))
        put("net_contents", source.get("volume"))
        put("manufacturer", source.get("maker"))

        origin = text(source.get("origin"))
        put("country_of_origin", ORIGIN_EN.get(origin.lower(), origin))

        # 원문이 바뀜으면 사전으로 옮겨 놓은 값은 버린다.
        #
        # 2026-09-21 에 앞에서 고친 전성분으로 만든 영문 표기가 그대로
        # 남아 있었다. put() 은 값이 들어 있으면 덮지 않기 때문이다.
        # 그 규칙은 사람이 확인한 값을 지키려는 것이지, 기계가 만든 값을
        # 영원히 지키려는 것이 아니다. 원문과 짝이 안 맞으면 다시 계산한다.
        new_source = text(source.get("ingredients"))
        if (new_source
                and target.get("ingredients_inci_source") == "kr_notice_via_dictionary"
                and text(target.get("ingredients_source")) != new_source):
            target.pop("ingredients_inci", None)
            target.pop("ingredients_inci_source", None)

        # 한국어 원문은 근거로 늘 남긴다
        if real(source.get("ingredients")):
            target["ingredients_source"] = text(source["ingredients"])
            target["ingredients_source_type"] = "daiso_product_notice"
        if real(source.get("warnings")):
            target["warnings_source"] = text(source["warnings"])

        inci, missing, fixed, review = to_inci(
            text(source.get("ingredients")), resolver)
        if missing:
            missing_all[pd_no] = missing
        if fixed:
            fixed_all[pd_no] = fixed
        if review:
            review_all[pd_no] = review
        if inci:
            put("ingredients_inci", inci)
            target["ingredients_inci_source"] = "kr_notice_via_dictionary"

        # 안내문에 속지 않는다. real() 로 본다.
        ok = all(real(target.get(f)) for f in REQUIRED_LABEL_FIELDS)
        target["gosi_ok"] = ok
        if derived:
            target["_자동으로_채운_칸"] = derived
        target["last_gosi_sync_at"] = now
        target.setdefault("source_type", "daiso_product_notice")

        if ok:
            complete += 1
        report.append({
            "pd_no": pd_no,
            "gosi_ok": ok,
            "빠진_칸": [f for f in REQUIRED_LABEL_FIELDS
                      if not real(target.get(f))],
            "못_옮긴_성분": missing[:12],
            "표기_되돌림": fixed[:12],
        })

    if wrapped:
        labels["items"] = registry
        labels["updated_at"] = now
        labels["못_옮긴_성분"] = missing_all
        payload = labels
    else:
        payload = registry

    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    side = LABELS.parent / "us_label_sync_report.json"
    side.write_text(json.dumps({
        "generated_at": now,
        "generator": "scripts/sync_gosi_to_us_labels.py",
        "고시_건수": len(items),
        "라벨_완성": complete,
        "새로_채운_칸": filled,
        "안내문을_덮은_칸": replaced,
        "사전_크기": len(table),
        "성격": ("한국 고시를 사전으로 옮긴 값이다. 사람이 포장 실물로 "
               "확인한 값이 아니다. 확인하면 그 값이 우선이고 "
               "이 스크립트는 덮지 않는다."),
        "못_옮긴_성분": missing_all,
        "표기_되돌림": fixed_all,
        "사람확인_필요": review_all,
        "되돌림_규칙": (
            "scripts/inci_resolver.py 가 정본에 있는 표준명으로만 잇는다. "
            "후보의 영문 표기가 갈리면 잇지 않고 사람확인_필요 에 남긴다."
        ),
        "상품별": report,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"고시 {len(items)}건 → 영문 라벨")
    print(f"  새로 채운 칸 {filled} · 안내문을 덮은 칸 {replaced}")
    print(f"  4항목 완성 {complete}/{len(items)}")
    if fixed_all:
        total_fixed = sum(len(v) for v in fixed_all.values())
        print(f"  표기 되돌림 {total_fixed}건 (정본 표준명으로 연결)")
        seen = set()
        for records in fixed_all.values():
            for rec in records:
                pair = (rec.get("원문"), rec.get("표준명"))
                if pair in seen:
                    continue
                seen.add(pair)
                print(f"    {rec.get('원문')} → {rec.get('표준명')}"
                      f" [{rec.get('방법')}] {rec.get('영문')}")
    if missing_all:
        total = sum(len(v) for v in missing_all.values())
        uniq = sorted({x for v in missing_all.values() for x in v})
        print(f"  사전에 없는 성분 {len(uniq)}종 (연 {total}회)")
        for x in uniq[:12]:
            print(f"    {x}")
        print("  → data/inci_dictionary.json 에 넣으면 그 상품이 풀린다")
    for r in report:
        if not r["gosi_ok"]:
            print(f"  미완성 {r['pd_no']} 빠진 칸 {r['빠진_칸']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
