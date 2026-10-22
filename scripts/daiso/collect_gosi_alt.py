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

    ② 펼친 상세 이미지의 픽셀과, 제공되는 경우 img alt.
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

  alt는 일부 텍스트만 제공할 수 있으며 전체 고시를 보장하지 않는다.
  2026-10-20 1060646/1069430: 성분 전문은 하단 이미지 픽셀에만 있었다.
  잘못된 다른 향 이름도 alt에 있었으므로 제품/옵션 바인딩을 별도 확인한다.
  alt 미검출은 원본 고시 부재가 아니다. 무료 로컬 OCR 증적은
  scripts/daiso_notice_recovery.py로 수집하고 검토 전 정본 성분으로 쓰지 않는다.
  이 alt 수집기 자체에는 GEMINI_API_KEY가 필요 없다.

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
import unicodedata
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.gosi_observation_history import (validate_document, attempt, observe_field, mark_stale, publish_observation, receipt, sha, utcnow, ProviderStop, classify_stop, assert_not_stopped, persist_stop)
DATA = ROOT / "data"
GOSI = DATA / "gosi.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"
REGISTRY = DATA / "shopify_daily_registry.json"

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
    "return a.length ? a.join('\\n\\n') : '';}"
) % ALT_MIN

# alt 안에서 찾을 이름들. 앞에 있는 것부터 본다.
# 다이소 상세 이미지는 "라벨: 값" 또는 "라벨\n값" 두 형태를 섞어 쓴다.
LABELS: list[tuple[str, tuple[str, ...]]] = [
    ("volume", ("내용물의 용량 또는 중량", "용량 또는 중량", "내용량", "용량", "중량")),
    ("ingredients", ("기재·표시하여야 하는 모든 성분", "전성분", "모든 성분", "성분명")),
    # "제조업자 및 책임판매업자" 를 "제조업자" 보다 먼저 본다. 2026-10-17 1072800 정샘물 쿠션:
    # alt 가 "화장품제조업자 및 책임판매업자: (주)코스메카코리아 / (주)정샘물뷰티" 였는데
    # "화장품제조업자" 만 라벨로 잡혀 값이 "및 책임판매업자: (주)코스메카코리아 ..." 가 됐다.
    ("maker", ("제조업자 및 책임(제조) 판매업자", "화장품제조업자 및 책임판매업자",
               "제조업자 및 책임판매업자", "제조원 및 책임판매원", "화장품제조업자",
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


# Only explicit address labels delimit the company value. Never infer a country
# from these addresses, nor treat a parsed supplier notice as safety approval.
_MAKER_ADDRESS = re.compile(
    r"(?:^|[\s,;/])(?:\((?:공장|본사|주소|소재지)\)\s*[:：]?|(?:공장|본사|주소|소재지)\s*[:：])"
)
_MAKER_ROLES = tuple(sorted(
    next(names for field, names in LABELS if field == "maker") + ("책임판매원",),
    key=len, reverse=True,
))


def clean_maker(value: str) -> str:
    """Keep source company text; discard explicit addresses and role-only remnants."""
    value = _MAKER_ADDRESS.split(str(value or ""), maxsplit=1)[0].strip()
    value = re.sub(r"\s+", " ", value)
    residue = value
    for role in _MAKER_ROLES:
        residue = residue.replace(role, "")
    residue = re.sub(r"(?:및|[\s:：/·,;()&-])", "", residue)
    return value if residue and real(value) else ""


_NET_AMOUNT = re.compile(
    r"(?<![0-9A-Za-z_.,+\-])([+\-]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
    r"(?:\.[0-9]+)?|\.[0-9]+))\s*"
    r"(?:fl\.?\s*oz\.?|kg|mg|ml|g|l|oz|ea|pcs?|pieces?|sheets?|count|"
    r"밀리리터|리터|밀리그램|킬로그램|그램|개입|개|매|장|포|입)(?![A-Za-z])", re.I,
)
_NET_UNVERIFIED = re.compile(
    r"미\s*(?:확인|제공|표기|기재|상)|확인\s*(?:필요|불가|중)|추정|추측|예상|미정|"
    r"아님|아니[다며라고]|아닙|아냐|불명|알\s*수\s*없|(?:해당|정보)\s*없|오(?:기|타)|"
    r"(?:제공|표기|확인|기재)\s*(?:되지|안\s*(?:됨|된|함))|"
    r"상세\s*페이지\s*참조|별도\s*표기|"
    r"\bnot\s*(?:available|verified|provided|confirmed|known|correct|applicable|specified|[0-9])|"
    r"pending|unknown|estimated|unverified|unconfirmed|unspecified|uncertain|\bTB[CD]\b", re.I,
)


def clean_net_contents(value: str) -> str:
    """Require an explicit positive quantity and unit; never infer from a title.

    1076498 yielded '의 스틱형' and incorrectly passed collection completeness.
    This is only a syntax check, not product identity, label or safety approval.
    Preserve valid source text, including wet/dry quantities and pack counts.
    """
    if not isinstance(value, str) or not real(value):
        return ""
    normalized = unicodedata.normalize("NFKC", value).replace("−", "-")
    if _NET_UNVERIFIED.search(normalized):
        return ""
    quantities = _NET_AMOUNT.findall(normalized)
    if not quantities or any(Decimal(n.replace(",", "")) <= 0 for n in quantities):
        return ""
    return value.strip()


def notice_value(field: str, value: str) -> str:
    if field == "maker":
        return clean_maker(value)
    return clean_net_contents(value) if field == "volume" else value


def _label_position(line: str, name: str) -> int:
    pos = line.find(name)
    if pos < 0 or pos > 24 or (pos > 0 and line[pos - 1] == "("):
        return -1
    # This short new alias is a heading, not prose such as '성분명은 ...'.
    if name == "성분명":
        tail = line[pos + len(name):]
        if pos != 0 or (tail and not re.match(r"[\s:：·-]", tail)):
            return -1
    return pos


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
                pos = _label_position(line, nm)
                if pos < 0:
                    continue
                tail = line[pos + len(nm):].strip()
                # 긴 정식 라벨 뒤의 '(전성분):'은 값이 아니라 같은 라벨의
                # 반복 표기다. 이를 값으로 저장하지 말고 다음 줄을 읽는다.
                if re.fullmatch(r"\([^)]*(?:전성분|모든 성분)[^)]*\)\s*[:：]?", tail):
                    rest = ""
                else:
                    # 값이 '(주)메가코스'처럼 괄호로 시작할 수 있으므로
                    # 구분자만 제거하고 값의 괄호는 보존한다.
                    rest = tail.lstrip(" :：·" if field == "volume" else " :：·-").strip()
                if rest:
                    value = notice_value(field, rest)
                    if real(value):
                        out[field] = value
                else:
                    # 다음 라벨이 나올 때까지 모은다
                    buf = []
                    for nxt in lines[i + 1:]:
                        if not nxt:
                            if buf:
                                break
                            continue
                        if any(_label_position(nxt, x) >= 0 for x in all_names):
                            break
                        buf.append(nxt)
                    if buf:
                        value = notice_value(field, " ".join(buf).strip())
                        if real(value):
                            out[field] = value
                break

    return {k: v for k, v in out.items() if real(v)}


def targets() -> list[str]:
    """등록된 비공개 초안과 고시가 비어 있는 S등급 상품을 재수집한다."""
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

    # 2026-10-19: 1069429는 실제 Shopify 초안이지만 S등급이 아닌 바디
    # 대체 후보라 기존 S 전용 수집 대상에서 영구 누락됐다. 초안의 고시도
    # 같은 출처/증적 검증을 거쳐 수집한다. 이 목록은 판매 승인이 아니다.
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        registry = {}
    need = []
    for entry in registry.get("items") or []:
        pid = str(entry.get("pd_no") or "")
        if (entry.get("status") == "DRAFT" and re.fullmatch(r"[0-9]+", pid)
                and re.fullmatch(r"gid://shopify/Product/[0-9]+", str(entry.get("shopify_id") or ""))):
            row = gosi.get(pid) or {}
            if not all(real(notice_value(f, str(row.get(f) or ""))) for f in ("ingredients", "volume", "maker", "origin")):
                need.append(pid)
    for p in score.get("all_scored") or []:
        if p.get("grade") != "S":
            continue
        pid = str(p.get("pd_no"))
        row = gosi.get(pid) or {}
        if not all(real(notice_value(f, str(row.get(f) or "")))
                   for f in ("ingredients", "volume", "maker", "origin")):
            need.append(pid)
    # 실패한 앞쪽 상품만 매일 반복하지 않도록 마지막 시도 시각 순으로 순환한다.
    def last_attempt(pid):
        attempts = (gosi.get(pid) or {}).get("observation_attempts") or []
        return max((str(a.get("attempted_at") or "") for a in attempts), default="")
    return sorted(dict.fromkeys(need), key=last_attempt)[:MAX_ITEMS]


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

def main(*, check_access_only: bool = False) -> int:
    doc = json.loads(GOSI.read_text(encoding='utf-8-sig'))
    items = validate_document(doc)
    try:
        assert_not_stopped(doc, {'daiso'})
    except ProviderStop as exc:
        # 수집을 시작조차 못 했는데 Actions가 성공으로 표시되면 운영자가
        # '고시 누락'과 '공급자 접근 중단'을 구별할 수 없다. 대기 정책은 유지한다.
        print(f"GOSI_COLLECTION_BLOCKED: {exc}", file=sys.stderr)
        return 2
    if check_access_only:
        # Read-only orchestration precheck; no browser import, request, or
        # persisted stop/history changes, including when no collection is due.
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
                    # 2026-10-16: domcontentloaded 직후 count() 로 바로 봤더니 SPA 가 버튼을 그리기 전이라
                    # 세 상품 모두 expanded_button_clicked=False 였다(같은 페이지를 networkidle 후 보면 버튼이 있다).
                    # 버튼이 뜰 때까지 기다린다. 없는 상품도 있으니 시간 초과는 '버튼 없음' 으로 둔다.
                    try:
                        btn.first.wait_for(state='visible', timeout=15000)
                    except Exception:
                        pass
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
    try:
        assert_not_stopped(doc, {'daiso'})
    except ProviderStop as exc:
        print(f"GOSI_COLLECTION_BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main(check_access_only=sys.argv[1:] == ['--check-access-only']))
