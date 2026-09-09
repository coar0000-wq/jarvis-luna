#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 뷰티관에서 상품 URL 목록만 받아 큐로 만든다.

왜 만들었나
  수집기가 사이트맵 19,739개를 순서대로 훑는다. 그런데 뷰티관 밖 상품이
  대부분이라 받아본 뒤에야 버린다. 한 회차 110건 중 82건이 그랬다.
  robots.txt 가 Crawl-delay 30 을 요구하므로 82 × 30초 = 41분이 버려진다.

  방문한 것은 crawl_state 에 남아 두 번 받지는 않는다. 그래도 남은
  18,449건 중 비뷰티가 85% 면 약 131시간을 한 번씩은 내야 한다.

왜 이 방법인가
  먼저 네 가지를 직접 받아 확인했다.
    뷰티관 허브 /ds/diy2/C245  HTTP 200 인데 pdNo 가 0개다. 클라이언트 렌더링이다.
    사이트맵                   11.9MB 단일 파일. 분류 정보가 없다.
    상품 <url> 블록            lastmod, changefreq, priority 뿐이다.
    pdNo 구간                  뷰티와 비뷰티가 같은 대역에 섞여 있다.
  그래서 평범한 HTTP 로는 받기 전에 뷰티인지 알 방법이 없었다.

  Gemini url_context 는 페이지를 렌더해서 읽는다. 그걸로 목록을 받는다.

숫자를 받지 않는다
  이 스크립트는 상품 URL 만 가져온다. 이름도 가격도 받지 않는다.
  LLM 이 옮겨 적은 숫자는 틀릴 수 있고, 우리는 그 값으로 마진을 계산한다.
  URL 은 틀리면 404 나 파싱 실패로 바로 드러나므로 위험이 다르다.
  가격과 이름은 collect_daiso.py 가 원래대로 직접 받는다.

robots.txt (2026-09-08 확인)
  daisomall.co.kr 의 User-agent: * 는 /ds/ 와 /pd/pdr/ 을 허용하고
  Crawl-delay 30 을 건다. 우리가 직접 받는 것은 그 규칙을 지킨다.
  이 스크립트는 우리가 페이지를 긁는 게 아니라 Gemini 에게 읽어달라고
  맡기는 것이며, 대상 경로는 허용된 /ds/ 다.

환경변수
  GEMINI_API_KEY      필수
  GEMINI_URL_MODEL    선택. 비우면 API 에 모델 목록을 물어 고른다.
  DAISO_QUEUE_ONLY    선택. 카테고리 이름 하나만 시험할 때 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "daiso_real" / "beauty_queue.json"
CATMAP = ROOT / "scripts" / "daiso" / "category_map.json"

# 엔드포인트를 잘못 적어 404 를 받았다. 작동하는 collect_via_gemini.py 와
# 같은 주소를 쓴다.
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
TIMEOUT = 120
RETRIES = 3
BASE = "https://www.daisomall.co.kr"

# 뷰티관 하위 카테고리. hub_url 이 C245 이고 그 아래를 훑는다.
# 카테고리 번호는 화면에서 확인한 값이 아니라, 허브 페이지를 Gemini 가
# 읽어 목록을 돌려주므로 여기서는 허브만 지정한다.
HUB = "https://www.daisomall.co.kr/ds/diy2/C245"

PROMPT = """Open {url} and list the product detail page URLs shown on it.

Return ONLY a JSON array of strings. Each string must be a full URL that
looks like https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1234567

Hard rules:
- Only URLs that are actually linked on this page. Do not invent pdNo values.
- Do not return category, event, or search URLs. Product pages only.
- If the page did not load or shows no products, return an empty array [].
- Do not include products you recall from memory. Only what is on this page.
- Maximum 60 URLs."""

PD_RE = re.compile(r"https://www\.daisomall\.co\.kr/pd/pdr/SCR_PDR_0001\?pdNo=\d+")


API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


def pick_model(key: str) -> tuple[str, str]:
    """쓸 모델을 정한다.

    예전에는 os.environ.get("GEMINI_URL_MODEL", "기본값") 였다. 그런데
    워크플로가 ${{ vars.GEMINI_URL_MODEL }} 을 넘기는데 저장소에 그 변수가
    없어서 빈 문자열이 들어온다. get 의 기본값은 키가 없을 때만 쓰이므로
    빈 문자열이 그대로 모델 이름이 됐다.

    그 결과 Gemini 수집이 09-03 부터 09-07 까지 엿새 내내
    "Model '' not found" 로 실패했다. 매번 0건이었는데 아무도 몰랐다.

    이제 지정이 없으면 API 에 모델 목록을 물어 고른다. 이름을 추측해
    박아두면 모델이 바뀔 때 또 같은 일이 난다.
    """
    forced = (os.environ.get("GEMINI_URL_MODEL") or "").strip()
    if forced:
        return forced, "환경변수 지정"
    try:
        req = urllib.request.Request(f"{API_ROOT}/models?key={key}&pageSize=200")
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:                                    # noqa: BLE001
        return "", f"모델 목록 조회 실패: {type(e).__name__}: {e}"
    names = [m["name"].replace("models/", "") for m in d.get("models", [])
             if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    # 페이지를 읽는 일이라 정확도보다 속도와 비용이 낫다. flash 계열 우선.
    for pat in ("gemini-flash-latest", "gemini-3", "2.5-flash", "flash", "pro"):
        for n in names:
            if pat in n:
                return n, f"목록에서 고름 (후보 {len(names)}개)"
    return (names[0], f"목록 첫 항목 (후보 {len(names)}개)") if names else ("", "쓸 모델 없음")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def call(key: str, model: str, url: str) -> tuple[list, str, str]:
    """Gemini 에게 페이지를 읽혀 상품 URL 목록을 받는다."""
    body = {"model": model, "input": PROMPT.format(url=url),
            "tools": [{"type": "url_context"}]}
    data = json.dumps(body).encode("utf-8")
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=data, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                res = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            if e.code in (429, 500, 503):
                time.sleep(5 * attempt)
                continue
            return [], last, ""
        except Exception as e:                                # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(5 * attempt)
    else:
        return [], last or "재시도 소진", ""

    text, fetch_status = "", ""
    for step in res.get("steps", []):
        st = step.get("type")
        if st == "url_context_result":
            fetch_status = json.dumps(
                {k: v for k, v in step.items() if k != "type"},
                ensure_ascii=False)[:300]
        elif st == "model_output":
            for cb in step.get("content", []):
                if cb.get("type") == "text":
                    text += cb.get("text", "")

    if not text:
        return [], f"모델 출력 없음. url_context 상태: {fetch_status or '없음'}", fetch_status

    # 모델이 코드펜스를 붙이거나 설명을 덧붙여도 URL 만 골라낸다.
    # JSON 파싱에 실패해도 정규식으로 건질 수 있으면 건진다.
    urls = PD_RE.findall(text)
    if not urls:
        return [], f"상품 URL 없음: {text[:160]}", fetch_status
    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq, "", fetch_status


def probe(key: str, model: str, url: str) -> str:
    """빈 배열이 왔을 때, 페이지를 정말 읽었는지 되묻는다.

    첫 회차가 [] 를 돌려줬다. 그런데 [] 는 두 가지를 똑같이 뜻한다.
      1. 페이지를 못 열었다 (렌더 실패·차단·타임아웃)
      2. 페이지는 열었는데 상품 링크가 없었다
    둘은 대응이 정반대다. 1이면 이 방법을 접고 다른 길을 찾아야 하고,
    2면 허브 주소를 바꾸면 된다. 같은 요청을 한 번 더 보내봐야
    또 [] 만 온다. 그래서 무엇을 봤는지 직접 묻는다.

    이 답은 기록에만 남긴다. 수집 데이터로 쓰지 않는다.
    """
    q = (f"Open {url}. Do not list links. Answer in one short line:\n"
         f"the page <title>, then how many product cards you can see, "
         f"then the first 40 characters of visible body text. "
         f"If you could not open the page, say exactly: COULD_NOT_OPEN")
    body = {"model": model, "input": q, "tools": [{"type": "url_context"}]}
    data = json.dumps(body).encode("utf-8")
    try:
        req = urllib.request.Request(
            ENDPOINT, data=data, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as e:                                    # noqa: BLE001
        return f"진단 호출 실패: {type(e).__name__}: {e}"
    out = ""
    for step in res.get("steps", []):
        if step.get("type") == "model_output":
            for cb in step.get("content", []):
                if cb.get("type") == "text":
                    out += cb.get("text", "")
    return (out or "(진단 응답 없음)").strip()[:400]


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("::error::GEMINI_API_KEY 가 없다. 호출하지 않고 멈춘다.")
        return 1

    model, how = pick_model(key)
    print(f"  모델: {model or '(없음)'} — {how}")
    if not model:
        print(f"::error::쓸 모델을 못 정했다. {how}")
        return 1

    only = (os.environ.get("DAISO_QUEUE_ONLY") or "").strip()
    targets = [("뷰티관 허브", HUB)]
    if only and only != "hub":
        targets = [(only, f"{BASE}/ds/diy2/{only}")]

    prev = load(OUT, {}) or {}
    known = set(prev.get("urls") or [])

    got, errors, statuses = [], [], []
    for name, url in targets:
        urls, err, st = call(key, model, url)
        row = {"target": name, "url": url,
               "count": len(urls), "url_context": st[:200]}
        if not urls:
            row["진단"] = probe(key, model, url)
            print(f"  {name}: 진단 - {row['진단'][:160]}")
        statuses.append(row)
        if err:
            errors.append({"target": name, "url": url, "error": err})
            print(f"  {name}: 실패 - {err[:120]}")
        else:
            print(f"  {name}: 상품 URL {len(urls)}건")
        got.extend(urls)

    fresh = [u for u in got if u not in known]
    merged = list(known) + fresh

    payload = {
        "generated_at": now_iso(),
        "generator": "scripts/daiso/build_beauty_queue.py",
        "왜": ("사이트맵을 훑으면 뷰티관 밖 상품을 받아본 뒤 버린다. "
              "한 회차 110건 중 82건이 그랬고 Crawl-delay 30 이라 41분이 버려졌다."),
        "신뢰": ("URL 만 받는다. 이름과 가격은 collect_daiso.py 가 직접 받는다. "
               "LLM 이 옮긴 숫자를 실측값으로 쓰지 않는다."),
        "model": model,
        "model_pick": how,
        "진단이란": ("count 가 0 인 대상에는 진단 칸이 붙는다. Gemini 에게 "
                  "그 페이지에서 무엇을 봤는지 되물은 답이다. 기록용이며 "
                  "수집 데이터로 쓰지 않는다."),
        "targets": statuses,
        "errors": errors,
        "new_this_run": len(fresh),
        "total": len(merged),
        "urls": merged,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            if len((load(OUT, {}) or {}).get("urls") or []) == len(merged):
                break
        except Exception:                                     # noqa: BLE001
            pass
        time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"큐 {len(merged)}건 (이번에 새로 {len(fresh)}건) · 실패 {len(errors)}")
    for s in statuses:
        print(f"  {s['target']}: {s['count']}건")
    if not merged:
        print("::warning::큐가 비었다. 사이트맵 방식으로 계속 돈다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
