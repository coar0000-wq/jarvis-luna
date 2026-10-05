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
sys.path.insert(0, str(ROOT))
from scripts.gosi_observation_history import (validate_document, attempt, observe_field, mark_stale, publish_observation, receipt, sha, utcnow, ProviderStop, classify_stop, assert_not_stopped, persist_stop)
DATA = ROOT / "data"
GOSI = DATA / "gosi.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"

PAGE = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

DELAY = float(os.environ.get("DAISO_DELAY", "30"))
MAX_ITEMS = int(os.environ.get("DAISO_GOSI_MAX", "12"))
ALT_MIN = 200

# 상세가 길면 고시는 맨 아래에 있다. 고정 14회 · 19,600px 로 끊었더니
# 39,765px 짜리 상세에서 고시까지 가기 전에 멈췄다. 끝에 닿을 때까지 내린다.
MAX_SCROLL = int(os.environ.get("DAISO_GOSI_SCROLL", "40"))

# alt 는 상세 영역에서 먼저 찾는다. 전체 img 를 먼저 보면 상단 마케팅
# 배너의 긴 alt 를 고시로 착각한다.
ALT_JS = (
    "() => {"
    "const pick=(sel)=>[...document.querySelectorAll(sel)]"
    ".map(i=>i.getAttribute('alt')||'').filter(x=>x.length>%d);"
    "let a=pick('div.cms div.editor-area div.editor-content img');"
    "if(!a.length) a=pick('div.editor-content img');"
    "if(!a.length) a=pick('img');"
    "return a.length ? a.join('\\n\\n') : '';}"
) % ALT_MIN

# alt 안에서 찾을 이름들. 앞에 있는 것부터 본다.
# 다이소 상세 이미지는 "라벨: 값" 또는 "라벨\n값" 두 형태를 섞어 쓴다.
LABELS: list[tuple[str, tuple[str, ...]]] = [
    ("volume", ("내용물의 용량 또는 중량", "용량 또는 중량", "내용량", "용량", "중량")),
    ("ingredients", ("기재·표시하여야 하는 모든 성분", "전성분", "모든 성분")),
    ("maker", ("제조업자 및 책임(제조) 판매업자", "화장품제조업자",
               "화장품책임판매업자", "제조업자", "책임판매업자",
               "제조판매업자", "제조원")),
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
                # 고시 이미지에는 "화장품법에 따라 기재·표시하여야 하는
                # 모든 성분(전성분)"처럼 법령 안내가 라벨 앞에 붙기도 한다.
                # startswith만 쓰면 원문이 있는데도 전성분을 영원히 놓친다.
                # 마케팅 본문 오인 방지를 위해 라벨이 줄 앞 24자 안에 있을
                # 때만 고시 라벨로 인정한다.
                pos = line.find(nm)
                if pos < 0 or pos > 24 or (pos > 0 and line[pos - 1] == "("):
                    continue
                tail = line[pos + len(nm):].strip()
                # 긴 정식 라벨 뒤의 '(전성분):'은 값이 아니라 같은 라벨의
                # 반복 표기다. 이를 값으로 저장하지 말고 다음 줄을 읽는다.
                if re.fullmatch(r"\([^)]*(?:전성분|모든 성분)[^)]*\)\s*[:：]?", tail):
                    rest = ""
                else:
                    # 값이 '(주)메가코스'처럼 괄호로 시작할 수 있으므로
                    # 구분자만 제거하고 값의 괄호는 보존한다.
                    rest = tail.lstrip(" :：·-").strip()
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
                        if any(0 <= nxt.find(x) <= 24 for x in all_names):
                            break
                        buf.append(nxt)
                    if buf:
                        out[field] = " ".join(buf).strip()
                break

    return {k: v for k, v in out.items() if real(v)}


def targets() -> list[str]:
    """고시가 아직 비어 있는 S등급 상품."""
    if len(sys.argv) > 1:
        return [a for a in sys.argv[1:] if not a.startswith('-') and (a.isdigit() or a[:1].isalnum())]

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


def response_text(raw):
    text = raw.decode('utf-8', 'replace')
    try:
        strings = []
        def visit(x):
            if isinstance(x, str): strings.append(x)
            elif isinstance(x, dict):
                for y in x.values(): visit(y)
            elif isinstance(x, list):
                for y in x: visit(y)
        visit(json.loads(text))
        text += '\n' + '\n'.join(strings)
    except ValueError:
        pass
    return re.sub(r'\s+', ' ', text)

def apply_alt(row, alt, responses, pd_no, scope):
    filled = []
    for field, value in parse_alt(alt).items():
        source = next((x for x in reversed(responses) if re.sub(r'\s+', ' ', value) in x['text']), None)
        if source is None:
            attempt(row, utcnow(), 'rendered_alt', 'unbound_field', field=field, capture_scope='parser_only', dom_sha256=sha(alt.encode()))
            continue
        evidence = dict(source['receipt'], source_received_at=source['receipt']['received_at'],
                        capture_scope=scope, dom_sha256=sha(alt.encode()),
                        intended_product_id=pd_no, product_identity_verified=False, human_verified=False)
        if observe_field(row, field, value, evidence): filled.append(field)
    return filled

def main() -> int:
    doc = json.loads(GOSI.read_text(encoding='utf-8-sig'))
    items = validate_document(doc)
    try:
        assert_not_stopped(doc, {'daiso'})
    except ProviderStop as exc:
        print(str(exc))
        return 0
    from playwright.sync_api import sync_playwright
    todo = targets()
    if not todo: return 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA, locale='ko-KR')
        page = ctx.new_page()
        responses, stop_box = [], []
        def received(response):
            if 'daisomall.co.kr' not in response.url: return
            if response.status in (401, 403, 429):
                stop_box.append(ProviderStop('daiso', response.status))
                return
            try:
                raw = response.body()
                evidence = receipt(raw, response.url, 'browser_response_application_bytes')
                text = response_text(raw)
                if response.status >= 400:
                    stop = classify_stop(text, 'daiso')
                    if stop: stop_box.append(stop)
                responses.append({'receipt': evidence, 'text': text})
            except Exception as exc:
                stop = classify_stop(exc, 'daiso')
                if stop: stop_box.append(stop)
        page.on('response', received)
        try:
            for i, pd_no in enumerate(todo):
                if stop_box: break
                if i: page.wait_for_timeout(int(max(30, DELAY) * 1000))
                responses.clear()
                row = items.setdefault(pd_no, {'product_id': pd_no})
                when = utcnow()
                try:
                    page.goto(PAGE.format(pd_no), timeout=60000, wait_until='domcontentloaded')
                    if stop_box: raise stop_box[0]
                    btn = page.locator('button:has-text("상품설명 더보기")')
                    expanded = bool(btn.count())
                    if expanded: btn.first.click(timeout=8000)
                    alt, reached_end, last_height, stable = '', False, -1, 0
                    for _ in range(MAX_SCROLL):
                        if stop_box: raise stop_box[0]
                        page.mouse.wheel(0, 1600)
                        page.wait_for_timeout(1100)
                        found = page.evaluate(ALT_JS)
                        if len(found or '') > len(alt): alt = found
                        height, bottom = page.evaluate('() => {const e=document.scrollingElement;return [e.scrollHeight,e.scrollTop+e.clientHeight];}')
                        stable = stable + 1 if height == last_height else 0
                        last_height = height
                        if bottom >= height - 80 and stable >= 2:
                            reached_end = True
                            break
                    if stop_box: raise stop_box[0]
                    filled = apply_alt(row, alt, responses, pd_no, 'rendered_alt_partial_page') if alt else []
                    attempt(row, when, 'rendered_alt', 'fields_added' if filled else 'no_bound_fields', expanded_button_clicked=expanded, scroll_end_reached=reached_end, capture_scope='rendered_alt_partial_page', page_verification=False)
                    if not alt: mark_stale(row)
                except ProviderStop as exc:
                    persist_stop(doc, exc)
                    attempt(row, when, 'rendered_alt', 'stopped', reason=str(exc))
                    mark_stale(row)
                    break
                except Exception as exc:
                    stop = classify_stop(exc, 'daiso')
                    if stop:
                        persist_stop(doc, stop)
                        break
                    attempt(row, when, 'rendered_alt', 'failed', error_type=type(exc).__name__)
                    mark_stale(row)
        finally:
            browser.close()
        if stop_box: persist_stop(doc, stop_box[0])
    publish_observation(ROOT, doc)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())