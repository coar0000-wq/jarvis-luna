#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""렌더링된 다이소 상품 페이지에서 고시 전문을 글자로 꺼낸다.

왜 만들었나 (2026-09-13)

  사용자가 말했다.
    "다이소제품은 고시가 없는게 없어 네가 못봤거나 실수한거야"
    "그럼 url 담을 수집기도 필요없겠지"

  둘 다 맞았다.

  고시는 모든 제품에 있다. 자리는 두 곳이다.

    ① 「상품정보 제공 고시」 표 (11항목)
       접힌 칸에 있고 모든 제품에 있다. 그런데 대부분 "상세페이지 참조" 다.
       제조국만 실값이다. 이건 selPdDtlNtfc API 로 이미 받고 있다.

    ② img 의 alt   ← 실제 내용은 여기
       div.cms > div.editor-area > div.editor-content 안.
       이미지 경로에 /description/ 이 들어간다.
       ①이 "상세페이지 참조" 라고 가리키는 그 상세페이지가 이것이다.
       1041749 식물원 병풀 앰플은 1,077자 · 줄바꿈 60개였다.

  그런데 HTTP 로 받은 원본 HTML 에는 그 alt 가 없다. 상품 3개로 쟀다.

    HTTP 200 · HTML 43,799자
    img alt 총 12개 · 200자 넘는 것 0개
    /description/ 이미지 URL 0개
    editor-content 영역이 HTML 에 없다

  editor-content 를 스크립트가 그린다. requests 로는 못 본다.
  그래서 브라우저가 필요하다.

  대신 이미지를 내려받아 비전 모델로 읽을 필요가 없어진다.
  alt 가 이미 글자다. GEMINI_API_KEY 도 필요 없다.

어떻게 여나

  페이지를 열고 "상품설명 더보기" 를 누른 뒤 아래로 내린다.
  상세 이미지가 lazy 라서 화면에 들어와야 로드된다.
  로드되면 alt 가 DOM 에 붙는다.

robots.txt (2026-09-13 확인)
  /pd/pdr/ 은 Allow 다. Crawl-delay 30 을 지킨다.
  우리 UA 로 신분을 밝힌다.

쓰는 법
  pip install playwright && playwright install chromium
  python scripts/daiso/collect_gosi_alt.py            고시 없는 S등급만
  python scripts/daiso/collect_gosi_alt.py 1041749    특정 상품
  DAISO_GOSI_MAX=5  한 번에 볼 최대 개수
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
GOSI = DATA / "gosi.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"

PAGE = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

DELAY = float(os.environ.get("DAISO_DELAY", "30"))
MAX_ITEMS = int(os.environ.get("DAISO_GOSI_MAX", "12"))
ALT_MIN = 200

# alt 안에서 찾을 이름들. 앞에 있는 것부터 본다.
# 다이소 상세 이미지는 "라벨: 값" 또는 "라벨\n값" 두 형태를 섞어 쓴다.
LABELS: list[tuple[str, tuple[str, ...]]] = [
    ("volume", ("내용물의 용량 또는 중량", "내용량", "용량", "중량")),
    ("ingredients", ("기재·표시하여야 하는 모든 성분", "전성분", "모든 성분")),
    ("maker", ("화장품제조업자", "화장품책임판매업자", "제조업자",
               "책임판매업자", "제조판매업자", "제조원")),
    ("origin", ("제조국", "원산지")),
    ("expiry", ("사용기한 또는 개봉 후 사용기간", "제조번호및사용기간",
                "사용기한", "개봉 후 사용기간")),
    ("usage", ("사용방법", "사용법")),
    ("warnings", ("사용할 때의 주의사항", "사용시 주의사항", "주의사항")),
    ("functional", ("기능성화장품", "기능성 화장품", "심사필")),
]

PLACEHOLDER = ("상세페이지 참조", "상세 페이지 참조", "-", "없음",
               "해당없음", "해당 없음", "별도표기", "별도 표기")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def real(v: str) -> bool:
    s = (v or "").strip()
    return bool(s) and s not in PLACEHOLDER


def parse_alt(alt: str) -> dict[str, str]:
    """alt 한 덩이에서 고시 항목을 뽑는다.

    같은 줄에 "라벨: 값" 으로 있으면 그걸 쓰고,
    없으면 라벨 다음 줄부터 다음 라벨 전까지를 값으로 본다.
    """
    lines = [l.strip() for l in (alt or "").split("\n")]
    out: dict[str, str] = {}

    all_names = [n for _, names in LABELS for n in names]

    for i, line in enumerate(lines):
        if not line:
            continue
        for field, names in LABELS:
            if field in out:
                continue
            for nm in names:
                if not line.startswith(nm):
                    continue
                rest = line[len(nm):].lstrip(" :：·-").strip()
                if rest:
                    out[field] = rest
                else:
                    # 다음 라벨이 나올 때까지 모은다
                    buf = []
                    for nxt in lines[i + 1:]:
                        if not nxt:
                            if buf:
                                break
                            continue
                        if any(nxt.startswith(x) for x in all_names):
                            break
                        buf.append(nxt)
                    if buf:
                        out[field] = " ".join(buf).strip()
                break

    return {k: v for k, v in out.items() if real(v)}


def targets() -> list[str]:
    """고시가 아직 비어 있는 S등급 상품."""
    if len(sys.argv) > 1:
        return [a for a in sys.argv[1:] if a.isdigit() or a[:1].isalnum()]

    try:
        gosi = json.loads(GOSI.read_text(encoding="utf-8-sig")).get("items") or {}
    except (OSError, ValueError):
        gosi = {}
    try:
        score = json.loads(SCORE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        score = {}

    need = []
    for p in score.get("all_scored") or []:
        if p.get("grade") != "S":
            continue
        pid = str(p.get("pd_no"))
        row = gosi.get(pid) or {}
        if not all(real(str(row.get(f) or ""))
                   for f in ("ingredients", "volume", "maker", "origin")):
            need.append(pid)
    return need[:MAX_ITEMS]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 없다.")
        print("  pip install playwright")
        print("  playwright install chromium")
        return 1

    todo = targets()
    if not todo:
        print("고시가 비어 있는 S등급 상품이 없다. 할 일 없음.")
        return 0
    print(f"대상 {len(todo)}건: {todo}")

    try:
        doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        doc = {}
    items = doc.get("items")
    if not isinstance(items, dict):
        items = {}

    ok, empty = 0, []
    report = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=UA, viewport={"width": 1400, "height": 1000},
            locale="ko-KR")
        page = ctx.new_page()
        # 이미지 자체는 안 받아도 된다. alt 만 쓰므로 바이트를 아낀다.
        # 다만 lazy 로드가 걸려야 alt 가 붙으므로 요청은 가게 둔다.

        for i, pd_no in enumerate(todo):
            if i:
                print(f"  (Crawl-delay {DELAY:.0f}초 대기)")
                page.wait_for_timeout(int(DELAY * 1000))

            print(f"\n[{i + 1}/{len(todo)}] {pd_no}")
            try:
                page.goto(PAGE.format(pd_no), timeout=60000,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(4000)

                # 상품설명 더보기
                try:
                    btn = page.get_by_role(
                        "button", name=re.compile("상품설명 더보기"))
                    if btn.count():
                        btn.first.scroll_into_view_if_needed(timeout=8000)
                        btn.first.click(timeout=8000)
                        print("  상품설명 더보기 눌렀다")
                        page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  더보기 버튼 못 눌렀다: {type(e).__name__}")

                # 상세 이미지가 lazy 라 화면에 들어와야 로드된다
                alt = ""
                for step in range(14):
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(1100)
                    found = page.evaluate(
                        "() => {const a=[...document.querySelectorAll('img')]"
                        ".map(i=>i.getAttribute('alt')||'')"
                        f".filter(x=>x.length>{ALT_MIN});"
                        "return a.length? a.join('\\n\\n') : '';}}"
                    )
                    if found and len(found) > len(alt):
                        alt = found
                    if alt and step >= 4:
                        break

                if not alt:
                    print("  긴 alt 를 못 찾았다")
                    empty.append(pd_no)
                    report.append({"pd_no": pd_no, "alt_len": 0, "찾음": []})
                    continue

                print(f"  alt {len(alt)}자 · 줄바꿈 {alt.count(chr(10))}개")
                got = parse_alt(alt)
                print(f"  뽑은 항목 {sorted(got)}")

                row = items.get(pd_no) or {}
                filled = []
                for k, v in got.items():
                    if not real(str(row.get(k) or "")):
                        row[k] = v
                        filled.append(k)
                row.setdefault("name", "")
                row["alt_source"] = "rendered_page_img_alt"
                row["alt_len"] = len(alt)
                row["alt_collected_at"] = now()
                row["source_url"] = PAGE.format(pd_no)
                items[pd_no] = row

                if filled:
                    ok += 1
                print(f"  채운 칸 {filled or '없음'}")
                report.append({"pd_no": pd_no, "alt_len": len(alt),
                               "찾음": sorted(got), "채움": filled})

            except Exception as e:
                print(f"  실패: {type(e).__name__}: {str(e)[:90]}")
                empty.append(pd_no)

        browser.close()

    doc["items"] = items
    doc["updated_at"] = now()
    doc.setdefault("source", "daisomall.co.kr")
    doc["alt_수집"] = {
        "generator": "scripts/daiso/collect_gosi_alt.py",
        "방식": ("렌더링된 페이지의 img alt 에서 글자를 꺼낸다. "
               "이미지를 내려받아 비전으로 읽지 않는다. alt 가 이미 글자다."),
        "robots": "/pd/pdr/ Allow · Crawl-delay 30 준수",
        "ran_at": now(),
        "대상": len(todo), "채움": ok, "못찾음": empty,
        "상품별": report,
    }
    GOSI.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")

    print(f"\n{'=' * 56}")
    print(f"대상 {len(todo)}건 · 채운 상품 {ok}건 · 못 찾은 것 {len(empty)}건")
    if empty:
        print(f"  못 찾음: {empty}")
    print(f"{'=' * 56}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
