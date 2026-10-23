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
import time
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

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


def _product_arguments(arguments):
    if not isinstance(arguments, (list, tuple)):
        raise ValueError('product arguments must be an explicit list or tuple')
    values = list(arguments)
    if any(not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value) for value in values):
        raise ValueError('invalid product argument: only explicit numeric product IDs are supported')
    if len(values) != len(set(values)):
        raise ValueError('duplicate explicit product IDs')
    return values


def targets(arguments=None) -> list[str]:
    """Discover targets only when the validated public argument list is empty."""
    arguments = _product_arguments(sys.argv[1:] if arguments is None else arguments)
    if arguments:
        return arguments
    if MAX_ITEMS < 1:
        raise ValueError('target limit must be positive; it cannot manufacture a no-op')
    # Missing/malformed discovery input cannot become an apparently empty run.
    gosi = validate_document(json.loads(GOSI.read_text(encoding='utf-8-sig')))
    score = json.loads(SCORE.read_text(encoding='utf-8-sig'))
    registry = json.loads(REGISTRY.read_text(encoding='utf-8-sig'))
    if (not isinstance(score, dict) or not isinstance(score.get('all_scored'), list) or
            any(not isinstance(row, dict) for row in score['all_scored']) or
            not isinstance(registry, dict) or not isinstance(registry.get('items'), list) or
            any(not isinstance(row, dict) for row in registry['items'])):
        raise ValueError('invalid target discovery input shape')

    # 2026-10-19: 1069429는 실제 Shopify 초안이지만 S등급이 아닌 바디
    # 대체 후보라 기존 S 전용 수집 대상에서 영구 누락됐다. 초안의 고시도
    # 같은 출처/증적 검증을 거쳐 수집한다. 이 목록은 판매 승인이 아니다.
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
        if not re.fullmatch(r"[0-9]+", pid):
            raise ValueError("invalid S-grade product identity")
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
        # Avoid a self-referencing nested visitor retaining every parsed string
        # until cyclic GC; preserve the original depth-first value order.
        pending = [json.loads(text)]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                pending.extend(reversed(list(value.values())))
            elif isinstance(value, list):
                pending.extend(reversed(value))
        text += '\n' + '\n'.join(strings)
    except ValueError:
        pass
    return re.sub(r'\s+', ' ', text)

def apply_alt(row, alt, responses, pd_no, scope, *, observer=None, record_attempt=None):
    observer = observer or observe_field
    record_attempt = record_attempt or attempt
    filled = []
    for field, value in parse_alt(alt).items():
        source = next((x for x in reversed(responses) if re.sub(r'\s+', ' ', value) in x['text']), None)
        if source is None:
            record_attempt(row, utcnow(), 'rendered_alt', 'unbound_field', field=field, capture_scope='parser_only', dom_sha256=sha(alt.encode()))
            continue
        evidence = dict(source['receipt'], source_received_at=source['receipt']['received_at'],
                        capture_scope=scope, dom_sha256=sha(alt.encode()),
                        intended_product_id=pd_no, product_identity_verified=False, human_verified=False)
        if observer(row, field, value, evidence): filled.append(field)
    return filled


class CaptureLimit(RuntimeError):
    """Incomplete evidence, never permission to invent or truncate a notice."""


class ResponseCapture:
    """Bound Python evidence retention; body() transport buffering is separate.

    Status checks always precede capture admission. Reserve slots before a
    body RPC because sync Playwright event callbacks can nest in greenlets.
    Request identity is fixed at request start, never at response arrival.
    """
    TEXT_MIMES = {'application/json', 'application/ld+json', 'application/xml',
                  'application/xhtml+xml', 'text/html', 'text/plain', 'text/xml'}
    RESOURCE_TYPES = {'document', 'xhr', 'fetch'}

    def __init__(self, generation, stop, *, max_body_bytes=2 * 1024 * 1024,
                 max_total_bytes=8 * 1024 * 1024, max_text_bytes=16 * 1024 * 1024,
                 max_responses=64, max_inflight=2, max_requests=512):
        limits = (max_body_bytes, max_total_bytes, max_text_bytes,
                  max_responses, max_inflight, max_requests)
        if any(type(value) is not int or value < 1 for value in limits):
            raise ValueError('capture limits must be positive integers')
        self.generation, self.stop = generation, stop
        self.max_body_bytes, self.max_total_bytes = max_body_bytes, max_total_bytes
        self.max_text_bytes, self.max_responses = max_text_bytes, max_responses
        self.max_inflight, self.max_requests = max_inflight, max_requests
        self.requests, self.responses, self.issues = {}, [], []
        self.count = self.inflight = self.reserved = self.raw_bytes = self.text_bytes = 0
        self.binary_skipped = self.denials = 0
        self.stopped = False

    @staticmethod
    def relevant(url):
        host = (urlsplit(url).hostname or '').lower()
        return host == 'daisomall.co.kr' or host.endswith('.daisomall.co.kr')

    def issue(self, reason):
        if reason not in self.issues:
            self.issues.append(reason)

    def request_started(self, request):
        if not self.relevant(request.url) or request.resource_type not in self.RESOURCE_TYPES:
            return
        if len(self.requests) >= self.max_requests:
            self.issue('request_identity_limit')
            return
        self.requests[request] = self.generation

    def request_finished(self, request):
        self.requests.pop(request, None)

    def received(self, response):
        if not self.relevant(response.url):
            return
        if response.status in (401, 403, 429):
            if not self.stopped:
                self.stopped = True
                self.denials += 1
                self.stop(ProviderStop('daiso', response.status,
                                      'quota' if response.status == 429 else 'auth'))
            return
        if self.stopped or self.issues:
            return
        request = response.request
        if request.resource_type not in self.RESOURCE_TYPES:
            self.binary_skipped += 1
            return
        generation = self.requests.get(request)
        if generation != self.generation:
            self.issue('response_without_current_request_identity')
            return
        headers = response.headers
        mime = headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if mime not in self.TEXT_MIMES and not mime.endswith('+json'):
            if mime.startswith(('image/', 'audio/', 'video/', 'font/')):
                self.binary_skipped += 1
            else:
                self.issue('unsupported_evidence_content_type')
            return
        length = headers.get('content-length')
        try:
            declared = int(length) if length is not None else self.max_body_bytes
            if declared < 0:
                raise ValueError('negative length')
        except (ValueError, TypeError):
            self.issue('invalid_response_length')
            return
        if declared > self.max_body_bytes:
            self.issue('response_body_limit')
            return
        # Reserve the full possible body for missing/incorrect Content-Length.
        # This bounds admitted work, not the browser's initial transport buffer.
        reservation = self.max_body_bytes
        if self.count >= self.max_responses:
            self.issue('response_count_limit')
            return
        if self.inflight >= self.max_inflight:
            self.issue('response_inflight_limit')
            return
        if self.raw_bytes + self.reserved + reservation > self.max_total_bytes:
            self.issue('response_total_limit')
            return
        self.count += 1
        self.inflight += 1
        self.reserved += reservation
        try:
            raw = response.body()
            if self.stopped:
                return
            if not isinstance(raw, bytes) or len(raw) > self.max_body_bytes:
                self.issue('response_body_limit')
                return
            self.raw_bytes += len(raw)
            evidence = receipt(raw, response.url, 'browser_response_application_bytes')
            text = response_text(raw)
            if response.status >= 400:
                denied = classify_stop(text, 'daiso')
                if denied:
                    self.stopped = True
                    self.denials += 1
                    self.stop(denied)
                    return
            size = sys.getsizeof(text)
            if self.text_bytes + size > self.max_text_bytes:
                self.issue('response_text_limit')
                return
            # A nested callback can exhaust admission or stop the provider.
            if self.stopped or self.issues or generation != self.generation:
                return
            self.text_bytes += size
            self.responses.append({'receipt': evidence, 'text': text})
        except Exception as exc:
            denied = classify_stop(exc, 'daiso')
            if denied:
                self.stopped = True
                self.denials += 1
                self.stop(denied)
            else:
                self.issue('response_body_error:' + type(exc).__name__)
        finally:
            self.inflight -= 1
            self.reserved -= reservation

    def check(self):
        if self.issues:
            raise CaptureLimit(','.join(self.issues))

    def metrics(self):
        return {'response_count': self.count, 'captured_count': len(self.responses),
                'source_bytes': self.raw_bytes, 'retained_text_bytes': self.text_bytes,
                'binary_skipped': self.binary_skipped, 'denials': self.denials,
                'capture_issues': list(self.issues)}

MAX_PRODUCT_GROWTH_BYTES = 1024 * 1024
MAX_CHECKPOINT_DOCUMENT_BYTES = 8 * 1024 * 1024


def _document_bytes(document):
    return (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


class CollectionDeadline(RuntimeError):
    pass


def _progress(phase, **values):
    print('GOSI_PROGRESS ' + json.dumps(dict(phase=phase, **values), ensure_ascii=False), flush=True)


def _capture_limits():
    return {key: int(os.environ.get(env, default)) for key, env, default in (
        ('max_body_bytes', 'DAISO_GOSI_MAX_BODY_BYTES', 2 * 1024 * 1024),
        ('max_total_bytes', 'DAISO_GOSI_MAX_CAPTURE_BYTES', 8 * 1024 * 1024),
        ('max_text_bytes', 'DAISO_GOSI_MAX_TEXT_BYTES', 16 * 1024 * 1024),
        ('max_responses', 'DAISO_GOSI_MAX_RESPONSES', 64),
        ('max_inflight', 'DAISO_GOSI_MAX_INFLIGHT', 2),
    )}


def collect_worker(document, todo, writer):
    """Browser-only child. Never writes the canonical file or its manifest."""
    from playwright.sync_api import sync_playwright
    items = validate_document(document)
    deadline = writer.deadline
    stop_box, attempted, completed = [], [], []
    code, reason, current = 0, None, None
    journal_failed = False
    def state(phase, **extra):
        return dict(phase=phase, selected=list(todo), attempted=list(attempted),
                    completed=list(completed), unattempted=[p for p in todo if p not in attempted], **extra)
    def guard(capture=None):
        if stop_box:
            raise stop_box[0]
        if time.monotonic() >= deadline:
            raise CollectionDeadline('collection_deadline')
        if capture:
            capture.check()
    def timeout(milliseconds):
        guard()
        return max(1, min(milliseconds, int((deadline - time.monotonic()) * 1000)))
    def stopped(exc):
        nonlocal journal_failed
        if not stop_box:
            stop_box.append(exc)
            # Fsync the small observed denial before any further body work or
            # browser teardown. Publication and ACK are supervisor-owned.
            try:
                writer.emit('stop', {'product_id': current, 'code': exc.code,
                            'category': exc.category, 'observed_at': utcnow()}, wait_for_ack=False)
            except Exception:
                journal_failed = True
                raise
    _progress('collection_start', target_count=len(todo), targets=todo)
    try:
        # Reserve checkpoint capacity before even launching a browser for the
        # first selected product, and before every subsequent page dispatch.
        current, when = todo[0], utcnow()
        decision = writer.emit('start_product', {'product_id': current, 'attempted_at': when}, wait_for_ack=True)
        if decision.get('admitted') is False:
            raise CaptureLimit('checkpoint_capacity')
        attempted.append(current)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(timeout=timeout(60000))
            try:
                context = browser.new_context(user_agent=UA, locale='ko-KR')
                for index, product_id in enumerate(todo):
                    guard()
                    if index:
                        # No page remains open across products. Preserve delay;
                        # then recheck stop/deadline before creating any page.
                        delay = max(30, DELAY)
                        if time.monotonic() + delay >= deadline:
                            raise CollectionDeadline('deadline_before_required_delay')
                        time.sleep(delay)
                        guard()
                    if index:
                        current, when = product_id, utcnow()
                        decision = writer.emit('start_product', {'product_id': product_id, 'attempted_at': when}, wait_for_ack=True)
                        if decision.get('admitted') is False:
                            raise CaptureLimit('checkpoint_capacity')
                        attempted.append(product_id)
                    product_start_size = len(_document_bytes(document))
                    row = items.setdefault(product_id, {'product_id': product_id})
                    observations, attempts = [], []
                    def observe(local_row, field, value, provenance):
                        result = observe_field(local_row, field, value, provenance)
                        observations.append(dict(field=field, value=value, provenance=provenance))
                        return result
                    def record(local_row, at, source, status, **details):
                        attempt(local_row, at, source, status, **details)
                        attempts.append(dict(attempted_at=at, source=source, status=status, **details))
                    capture = ResponseCapture((index, product_id), stopped, **_capture_limits())
                    page = context.new_page()
                    guard()
                    page.on('request', capture.request_started)
                    page.on('requestfinished', capture.request_finished)
                    page.on('requestfailed', capture.request_finished)
                    page.on('response', capture.received)
                    stale, outcome = False, 'success'
                    _progress('product_start', product_id=product_id, index=index + 1, target_count=len(todo))
                    try:
                        guard(capture)
                        page.goto(PAGE.format(product_id), timeout=timeout(60000), wait_until='domcontentloaded')
                        guard(capture)
                        button = page.locator('button:has-text("상품설명 더보기")')
                        try:
                            button.first.wait_for(state='visible', timeout=timeout(15000))
                        except Exception:
                            guard(capture)
                        guard(capture)
                        expanded = bool(button.count())
                        guard(capture)
                        if expanded:
                            button.first.click(timeout=timeout(8000))
                        alt, reached_end, last_height, stable = '', False, -1, 0
                        for _ in range(MAX_SCROLL):
                            guard(capture)
                            page.mouse.wheel(0, 1600)
                            guard(capture)
                            page.wait_for_timeout(min(1100, timeout(1100)))
                            guard(capture)
                            found = page.evaluate(ALT_JS)
                            guard(capture)
                            if len(found or '') > len(alt):
                                alt = found
                            height, bottom = page.evaluate('() => {const e=document.scrollingElement;return [e.scrollHeight,e.scrollTop+e.clientHeight];}')
                            guard(capture)
                            stable = stable + 1 if height == last_height else 0
                            last_height = height
                            if bottom >= height - 80 and stable >= 2:
                                reached_end = True
                                break
                        guard(capture)
                        filled = apply_alt(row, alt, capture.responses, product_id,
                                           'rendered_alt_partial_page', observer=observe,
                                           record_attempt=record) if alt else []
                        record(row, when, 'rendered_alt', 'fields_added' if filled else 'no_bound_fields',
                               expanded_button_clicked=expanded, scroll_end_reached=reached_end,
                               capture_scope='rendered_alt_partial_page', page_verification=False)
                        stale = not alt
                    except ProviderStop as exc:
                        stopped(exc)
                        code, reason, outcome, stale = 2, 'provider_stop', 'stopped', True
                    except (CollectionDeadline, CaptureLimit) as exc:
                        code = 124 if isinstance(exc, CollectionDeadline) else 1
                        reason = str(exc)
                        outcome = 'deadline' if code == 124 else 'resource_limited'
                        record(row, when, 'rendered_alt', outcome, reason=reason)
                        stale = True
                    except Exception as exc:
                        denied = classify_stop(exc, 'daiso')
                        if denied:
                            stopped(denied)
                            code, reason, outcome = 2, 'provider_stop', 'stopped'
                        else:
                            code, reason, outcome = 1, type(exc).__name__, 'failed'
                            record(row, when, 'rendered_alt', 'failed', error_type=type(exc).__name__)
                        stale = True
                    # Complete source-bound results are durable before close(),
                    # context shutdown, or the next product can block execution.
                    if len(_document_bytes(document)) - product_start_size > MAX_PRODUCT_GROWTH_BYTES:
                        # No truncation or oversized new fields become evidence.
                        observations.clear()
                        attempts.clear()
                        code, reason, outcome, stale = 1, 'product_document_growth_limit', 'resource_limited', True
                        record(row, when, 'rendered_alt', outcome, reason=reason)
                    writer.emit('product_result', dict(product_id=product_id,
                                observations=observations, attempts=attempts, stale=stale,
                                outcome=outcome, metrics=capture.metrics()), wait_for_ack=True)
                    if outcome == 'success':
                        completed.append(product_id)
                    _progress('product_checkpoint', product_id=product_id, outcome=outcome, **capture.metrics())
                    page.close()
                    if code:
                        break
                    guard()
                context.close()
            finally:
                browser.close()
    except ProviderStop as exc:
        stopped(exc)
        code, reason = 2, 'provider_stop'
    except CollectionDeadline as exc:
        code, reason = 124, str(exc)
    except CaptureLimit as exc:
        code, reason = 1, str(exc)
    except Exception as exc:
        denied = classify_stop(exc, 'daiso')
        if denied:
            stopped(denied)
            code, reason = 2, 'provider_stop'
        else:
            code, reason = 1, type(exc).__name__
    if journal_failed:
        raise RuntimeError('denial_journal_failed')
    writer.emit('complete', {'exit_code': code, 'state': state('complete', reason=reason)}, wait_for_ack=True)
    return code


def _validated_time(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return value


def _publish_checkpoint(root, document, *, journal, deadline, cleanup_seconds):
    """Bound filesystem publisher execution; uncertain commits keep pending marker.

    The publisher retains the original transaction/snapshot guards. A child is
    needed because fsync/git/filesystem work must not stall the control loop.
    """
    import hashlib
    import signal
    import subprocess
    import uuid
    from scripts.moe_evaluation_history import atomic_write
    remaining = deadline - time.monotonic()
    grace = min(2.0, cleanup_seconds / 2, remaining / 4)
    if remaining <= 0 or grace <= 0:
        raise CollectionDeadline('checkpoint_publication_deadline')
    directory = journal / 'publications'
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    source, result = directory / (token + '.input.json'), directory / (token + '.receipt.json')
    raw = _document_bytes(document)
    if len(raw) > MAX_CHECKPOINT_DOCUMENT_BYTES:
        raise ValueError('checkpoint_document_limit')
    atomic_write(directory, source.name, raw)
    command = [sys.executable, str(Path(__file__).resolve()), '--publish-checkpoint',
               str(root), str(source), str(result)]
    process = subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    try:
        _, error = process.communicate(timeout=max(0.001, min(10.0, deadline - time.monotonic() - grace)))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=max(0.001, grace / 2))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=max(0.001, grace / 2))
            except subprocess.TimeoutExpired:
                pass
        raise CollectionDeadline('checkpoint_publication_deadline')
    if process.returncode != 0:
        raise RuntimeError('checkpoint_publication_failed:' + (error or b'')[-1000:].decode('utf-8', 'replace'))
    if not result.is_file() or result.stat().st_size > 65536:
        raise ValueError('checkpoint_receipt_missing_or_invalid')
    evidence = json.loads(result.read_bytes())
    canonical = (Path(root) / 'data/gosi.json').read_bytes()
    if evidence.get('current_sha256') != hashlib.sha256(canonical).hexdigest():
        raise ValueError('checkpoint_canonical_binding_mismatch')
    return evidence


def run_collection_supervisor(document, todo):
    """Only this parent applies and publishes bounded worker observations."""
    import hashlib
    import math
    import tempfile
    from scripts.daiso.gosi_collection_runtime import run_supervised
    items = validate_document(document)
    if len(todo) != len(set(todo)) or any(not isinstance(p, str) or not p for p in todo):
        raise ValueError('invalid selected product identities')
    budget = float(os.environ.get('DAISO_GOSI_BUDGET_SECONDS', '1200'))
    deadline = float(os.environ.get('DAISO_GOSI_DEADLINE_MONOTONIC', time.monotonic() + budget))
    cleanup = float(os.environ.get('DAISO_GOSI_CLEANUP_SECONDS', '20'))
    if not all(math.isfinite(x) and x > 0 for x in (budget, deadline, cleanup)):
        raise ValueError('invalid collection budget')
    baseline = GOSI.read_bytes()
    attempted, completed, stopped_codes, admission_refused = [], [], [], []
    product_document_bound = None
    active = None
    terminal = None
    def event_received(event):
        nonlocal active, terminal, items, product_document_bound
        kind, payload = event['kind'], event['payload']
        if not isinstance(payload, dict):
            raise ValueError('event payload must be an object')
        product_id = payload.get('product_id')
        if kind != 'complete' and product_id not in todo:
            raise ValueError('event product outside selected targets')
        if kind == 'start_product':
            if stopped_codes or active is not None or product_id in attempted:
                raise ValueError('invalid or stopped product dispatch')
            from scripts.gosi_safety_checkpoint import collection_admission
            product_document_bound = len(_document_bytes(document)) + MAX_PRODUCT_GROWTH_BYTES + 65536
            if (product_document_bound > MAX_CHECKPOINT_DOCUMENT_BYTES or
                    not collection_admission(ROOT, reserve_bytes=4 * product_document_bound + 65536)):
                admission_refused.append(product_id)
                return False
            active = product_id
            attempted.append(product_id)
            row = items.setdefault(product_id, {'product_id': product_id})
            attempt(row, _validated_time(payload['attempted_at']), 'rendered_alt', 'started')
        elif kind == 'stop':
            code = payload.get('code')
            if type(code) is not int or code not in (401, 403, 429):
                raise ValueError('invalid provider status')
            _validated_time(payload['observed_at'])
            if not stopped_codes:
                stopped_codes.append(code)
                denied = ProviderStop('daiso', code, 'quota' if code == 429 else 'auth')
                persist_stop(document, denied, stopped_at=payload['observed_at'])
                row = items.setdefault(product_id, {'product_id': product_id})
                attempt(row, payload['observed_at'], 'rendered_alt', 'stopped', reason=str(denied))
                mark_stale(row)
        elif kind == 'product_result':
            if product_id != active:
                raise ValueError('out-of-order product result')
            observations, attempts = payload.get('observations'), payload.get('attempts')
            if (not isinstance(observations, list) or len(observations) > len(LABELS) or
                    not isinstance(attempts, list) or len(attempts) > len(LABELS) + 2 or
                    type(payload.get('stale')) is not bool or
                    payload.get('outcome') not in {'success', 'stopped', 'failed', 'deadline', 'resource_limited'}):
                raise ValueError('invalid bounded product result')
            from copy import deepcopy
            prospective = deepcopy(document)
            row = prospective['items'][product_id]
            for observation in observations:
                field, value, evidence = observation['field'], observation['value'], observation['provenance']
                if (field not in {name for name, _ in LABELS} or not isinstance(value, str) or not value or
                        not isinstance(evidence, dict) or evidence.get('intended_product_id') != product_id or
                        evidence.get('capture_scope') != 'rendered_alt_partial_page' or
                        evidence.get('product_identity_verified') is not False or
                        evidence.get('human_verified') is not False or evidence.get('verified') is not False or
                        not ResponseCapture.relevant(evidence.get('source', '')) or
                        not re.fullmatch('[0-9a-f]{64}', evidence.get('sha256', '')) or
                        type(evidence.get('byte_count')) is not int or
                        not 0 < evidence['byte_count'] <= _capture_limits()['max_body_bytes']):
                    raise ValueError('invalid source-bound observation')
                _validated_time(evidence['received_at'])
                observe_field(row, field, value, evidence)
            for observation in attempts:
                details = dict(observation)
                at, source, status = details.pop('attempted_at'), details.pop('source'), details.pop('status')
                if source != 'rendered_alt' or status not in {'unbound_field', 'fields_added', 'no_bound_fields', 'failed', 'deadline', 'resource_limited'}:
                    raise ValueError('invalid attempt event')
                attempt(row, _validated_time(at), source, status, **details)
            if payload['stale']:
                mark_stale(row)
            if payload['outcome'] == 'success':
                if stopped_codes:
                    raise ValueError('success after provider stop')
                completed.append(product_id)
            if len(_document_bytes(prospective)) > product_document_bound:
                raise ValueError('product_document_growth_limit')
            document.clear()
            document.update(prospective)
            items = validate_document(document)
            active = None
        elif kind == 'complete':
            if terminal is not None or type(payload.get('exit_code')) is not int:
                raise ValueError('invalid completion')
            terminal = payload
            if payload['exit_code'] == 0 and (active is not None or stopped_codes or completed != todo):
                raise ValueError('incomplete worker cannot succeed')
            return
        else:
            raise ValueError('unknown collector event')
        _publish_checkpoint(ROOT, document, journal=journal, deadline=deadline, cleanup_seconds=cleanup)
    journal = Path(tempfile.mkdtemp(prefix='gosi-runtime-', dir=os.environ.get('RUNNER_TEMP'))) / 'journal'
    from scripts.moe_evaluation_history import safe_path, sync_dir
    pending = safe_path(ROOT, '.gosi-collection.pending')
    marker = json.dumps({'baseline_sha256': hashlib.sha256(baseline).hexdigest(),
                         'journal_dir': str(journal), 'selected': todo}).encode()
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(marker)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(pending.parent)
    command = [sys.executable, '-u', str(Path(__file__).resolve()), '--collection-worker', json.dumps(todo)]
    outcome = run_supervised(command, journal_dir=journal, baseline_bytes=baseline,
                             deadline=deadline, cleanup_seconds=cleanup, on_event=event_received)
    code = int(outcome['exit_code'])
    if stopped_codes and not outcome.get('error') and outcome.get('cleanup_confirmed'):
        code = 2
    if code and active is not None and not outcome.get('error') and outcome.get('cleanup_confirmed'):
        row = items[active]
        attempt(row, utcnow(), 'rendered_alt', 'interrupted', reason=outcome.get('reason', 'worker_incomplete'))
        mark_stale(row)
        _publish_checkpoint(ROOT, document, journal=journal, deadline=deadline, cleanup_seconds=cleanup)
    reconciled = (not outcome.get('error') and outcome.get('cleanup_confirmed') and
                  outcome.get('reason') in {'complete', 'provider_stop', 'worker_deadline',
                                            'worker_reported_failure', 'no_worker_budget'})
    if reconciled:
        if pending.read_bytes() != marker:
            raise ValueError('collection pending marker changed')
        pending.unlink()
        sync_dir(pending.parent)
    report = dict(outcome, reconciled=bool(reconciled), exit_code=code, selected=todo, attempted=attempted, completed=completed,
                  unattempted=[p for p in todo if p not in attempted], provider_stop_codes=stopped_codes,
                  admission_refused=admission_refused,
                  baseline_sha256=hashlib.sha256(baseline).hexdigest(), journal_dir=str(journal))
    report_path = Path(os.environ.get('GOSI_COLLECTION_REPORT', str(journal/'collection-result.json')))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    _progress('collection_result', exit_code=code, attempted_count=len(attempted),
              completed_count=len(completed), unattempted_count=len(report['unattempted']),
              report=str(report_path), reason=outcome.get('reason'))
    return code



def run_guarded_collection(arguments=None):
    """Contain all supervisor I/O with a disk-free outer process watchdog.

    The existing cleanup reserve is split, not added: inner work stops at
    deadline-reserve; the outer guard retains the final quarter for cleanup.
    """
    import math
    from scripts.daiso.gosi_collection_runtime import run_guarded
    arguments = _product_arguments(sys.argv[1:] if arguments is None else arguments)
    budget = float(os.environ.get('DAISO_GOSI_BUDGET_SECONDS', '1200'))
    deadline = float(os.environ.get('DAISO_GOSI_DEADLINE_MONOTONIC', time.monotonic() + budget))
    cleanup = float(os.environ.get('DAISO_GOSI_CLEANUP_SECONDS', '20'))
    if not all(math.isfinite(x) and x > 0 for x in (budget, deadline, cleanup)):
        raise ValueError('invalid collection budget')
    outer_cleanup = cleanup / 4
    environment = dict(os.environ, DAISO_GOSI_DEADLINE_MONOTONIC=str(deadline - outer_cleanup),
                       DAISO_GOSI_CLEANUP_SECONDS=str(cleanup - outer_cleanup))
    command = [sys.executable, '-u', str(Path(__file__).resolve()), '--guarded-collection', *arguments]
    outcome = run_guarded(command, deadline=deadline, cleanup_seconds=outer_cleanup, env=environment)
    _progress('guard_result', exit_code=outcome['exit_code'], reason=outcome['reason'],
              cleanup_confirmed=outcome['cleanup_confirmed'])
    return outcome['exit_code']


def guarded_collection_worker(arguments=None):
    from scripts.daiso.gosi_collection_runtime import emit_guard_result
    # Fail before source work if an internal entrypoint was invoked directly.
    fd = int(os.environ['GOSI_GUARD_RESULT_FD'])
    os.fstat(fd)
    if not os.environ.get('GOSI_GUARD_NONCE'):
        raise ValueError('missing collection guard identity')
    arguments = _product_arguments([] if arguments is None else arguments)
    code = main(arguments=arguments)
    emit_guard_result(code)
    return code


def main(*, check_access_only: bool = False, arguments=None) -> int:
    from scripts.gosi_observation_history import require_continuity
    require_continuity(ROOT)
    doc = json.loads(GOSI.read_text(encoding='utf-8-sig'))
    validate_document(doc)
    try:
        assert_not_stopped(doc, {'daiso'})
    except ProviderStop as exc:
        print(f'GOSI_COLLECTION_BLOCKED: {exc}', file=sys.stderr)
        return 2
    if check_access_only:
        return 0
    todo = targets(arguments)
    if not todo:
        _progress('collection_no_op', reason='no_eligible_targets', target_count=0,
                  input_sha256={path.name: sha(path.read_bytes()) for path in (GOSI, SCORE, REGISTRY)})
        return 0
    return run_collection_supervisor(doc, todo)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--guarded-collection']:
        raise SystemExit(guarded_collection_worker(sys.argv[2:]))
    if sys.argv[1:2] == ['--publish-checkpoint']:
        if len(sys.argv) != 5:
            raise SystemExit('invalid internal publisher arguments')
        from scripts.moe_evaluation_history import atomic_write
        target_root, source, output = map(Path, sys.argv[2:5])
        evidence = publish_observation(target_root, json.loads(source.read_bytes()))
        atomic_write(output.parent, output.name, (json.dumps(evidence) + '\n').encode())
        raise SystemExit(0)
    if sys.argv[1:2] == ['--collection-worker']:
        if len(sys.argv) != 3:
            raise SystemExit('invalid internal worker arguments')
        from scripts.daiso.gosi_collection_runtime import JournalWriter
        writer = JournalWriter.from_env()
        baseline = json.loads(writer.baseline_path.read_text(encoding='utf-8-sig'))
        raise SystemExit(collect_worker(baseline, json.loads(sys.argv[2]), writer))
    if sys.argv[1:] == ['--check-access-only']:
        raise SystemExit(main(check_access_only=True))
    raise SystemExit(run_guarded_collection())
