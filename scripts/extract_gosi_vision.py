#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고시 이미지를 Gemini 비전으로 읽어 gosi.json 을 채운다.

용량과 전성분은 다이소 API 어디에도 텍스트로 없다. 상세 이미지 안에
인쇄되어 있다. 그 이미지를 모델이 읽어 표를 그대로 옮긴다.

지어내는 것과 읽는 것은 다르다. 여기서 하는 일은 읽기다. 다만 오독은
있을 수 있으므로 다음을 지킨다.
  - 표에 없는 항목은 빈 문자열로 둔다. 모델에게도 그렇게 지시한다.
  - 결과마다 source 와 verified 를 남긴다. verified 는 사람이 켠다.
  - 원본 이미지 경로를 함께 남겨 언제든 대조할 수 있게 한다.
  - 사람이 이미 채운 값은 덮어쓰지 않는다.
"""
from __future__ import annotations
import base64, json, os, re, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOSI = ROOT / "data" / "gosi.json"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 120
DELAY = 3.0
# 워크플로 전체 한도가 60분인데 비전 한 단계가 39분을 먹은 적이 있다.
# 예산을 넘으면 남은 건 다음 회차로 넘긴다. 미룰 뿐 빠뜨리지 않는다.
BUDGET_SEC = float(os.environ.get("VISION_BUDGET_SEC") or 720)
FIELDS = ("volume", "ingredients", "maker", "origin", "warnings",
          "expiry", "functional")

PROMPT = """이 이미지는 한국 화장품의 '상품정보 제공고시' 표입니다.
표에 적힌 내용을 그대로 옮겨 JSON 으로만 답하세요.

{
  "volume": "내용물의 용량 또는 중량",
  "ingredients": "화장품법에 따라 기재해야 하는 모든 성분 전체",
  "maker": "화장품제조업자 및 책임판매업자",
  "origin": "제조국",
  "warnings": "사용할 때의 주의사항",
  "expiry": "사용기한 또는 개봉 후 사용기간",
  "functional": "기능성 화장품 여부"
}

규칙
- 표에 그 항목이 없거나 읽을 수 없으면 빈 문자열 "" 로 두세요.
- 요약하거나 정리하지 마세요. 특히 전성분은 하나도 빠뜨리지 말고
  쉼표까지 원문 그대로 옮기세요.
- 추측해서 채우지 마세요. 보이는 글자만 옮기세요.
- JSON 외에 다른 말을 붙이지 마세요."""


def http_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url, data=data, method="POST" if payload else "GET",
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))


def pick_models(key: str) -> list[str]:
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return [forced]
    d = http_json(f"{API_ROOT}/models?key={key}&pageSize=200")
    usable = [m["name"].replace("models/", "") for m in d.get("models", [])
              if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    # 한 모델이 과부하면 다음 모델로 넘어간다. flash 계열이 싸고 빠르다.
    order, seen = [], set()
    # 성분 표기는 법률 자료라 정확도가 우선이다. Pro 와 확장 사고 모델을
    # 먼저 쓰고, 과부하면 flash 로 내려간다.
    for pat in ("3.1-pro", "gemini-3", "pro-latest", "2.5-pro", "pro",
                "thinking", "gemini-flash-latest", "2.5-flash", "flash"):
        for n in usable:
            if pat in n and n not in seen:
                seen.add(n)
                order.append(n)
    if not order:
        order = usable[:3]
    if not order:
        raise RuntimeError("generateContent 지원 모델 없음")
    # 후보가 많을수록 과부하 때 대기가 길어진다. 둘이면 충분하다.
    return order[:2]


def read_table(key: str, models: list[str], img: Path) -> tuple[dict | None, str]:
    """이미지 한 장을 읽는다.

    2026-09-05 첫 실행에서 14건 전부 503 으로 실패했다. 모델 과부하는
    흔한 일인데 재시도가 없어 그대로 끝났다. 이제 물러섰다가 다시 걸고,
    그래도 안 되면 다른 모델로 넘어간다.
    """
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    last = ""
    d = None
    for model in models:
        for attempt in range(1, 3):
            try:
                d = http_json(f"{API_ROOT}/models/{model}:generateContent?key={key}", payload)
                last = ""
                break
            except Exception as exc:
                code = getattr(exc, "code", None)
                last = f"{model} {type(exc).__name__}: {exc}"[:120]
                # 429/5xx 는 잠시 뒤 다시 하면 되는 경우가 많다
                if code in (429, 500, 502, 503, 504):
                    time.sleep(3 * attempt)
                    continue
                break
        if d is not None:
            break
    if d is None:
        return None, last or "호출 실패"
    try:
        txt = d["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return None, "응답에 텍스트가 없음"
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        return json.loads(txt), ""
    except json.JSONDecodeError:
        return None, "JSON 파싱 실패"


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    items = doc.get("items") or {}
    if not key:
        doc["vision_status"] = "skipped - GEMINI_API_KEY 없음"
        GOSI.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("GEMINI_API_KEY 없음 - 건너뜀")
        return 0

    # 이미 필수 4항목이 다 찬 것은 다시 부르지 않는다.
    # 이 건너뛰기가 없어서 14건 전부 완료된 뒤에도 매 회차 14건을
    # 다시 읽었고 그게 39분이었다. 읽을 게 없으면 즉시 끝난다.
    need = ("ingredients", "volume", "maker", "origin")
    todo = {k: v for k, v in items.items()
            if not all(str(v.get(f) or "").strip() for f in need)}
    if not todo:
        doc["vision_status"] = "ok"
        doc["vision_note"] = "필수 4항목이 모두 채워져 있어 호출하지 않았다."
        doc["vision_at"] = datetime.now(timezone.utc).isoformat()
        GOSI.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"읽을 항목 없음 - {len(items)}건 모두 완비. 호출 0회")
        return 0
    print(f"대상 {len(todo)}/{len(items)}건 · 예산 {BUDGET_SEC:.0f}초")

    models = pick_models(key)
    print(f"모델 후보: {', '.join(models)}")
    started = time.monotonic()
    filled, fails, deferred = 0, [], []
    for pd_no, row in todo.items():
        if time.monotonic() - started > BUDGET_SEC:
            deferred.append(pd_no)
            continue
        img = row.get("gosi_image")
        if not img:
            fails.append({"pd_no": pd_no, "reason": "고시 이미지 없음"})
            continue
        p = ROOT / img
        if not p.exists():
            fails.append({"pd_no": pd_no, "reason": f"파일 없음 {img}"})
            continue
        got, err = read_table(key, models, p)
        if got is None:
            fails.append({"pd_no": pd_no, "reason": err})
            time.sleep(DELAY)
            continue
        wrote = []
        for f in FIELDS:
            v = str(got.get(f) or "").strip()
            # 사람이 이미 채운 값은 건드리지 않는다
            if v and not str(row.get(f) or "").strip():
                row[f] = v
                wrote.append(f)
                filled += 1
        row["vision_source"] = f"gemini:{models[0]}"
        row["vision_image"] = img
        row["verified"] = bool(row.get("verified"))   # 사람이 켜는 값
        row["vision_at"] = datetime.now(timezone.utc).isoformat()
        ing = str(row.get("ingredients") or "")
        print(f"  {pd_no}  {len(wrote)}칸 · 전성분 {len(ing)}자  {str(row.get('name'))[:24]}")
        time.sleep(DELAY)

    if deferred:
        print(f"예산 초과로 {len(deferred)}건은 다음 회차로 미룸")
    doc["vision_deferred"] = deferred
    req = ("ingredients", "volume", "maker", "origin")
    done = sum(1 for r in items.values() if all(str(r.get(f) or "").strip() for f in req))
    doc["vision_status"] = "ok"
    doc["vision_note"] = (
        "용량·전성분은 이미지에만 있어 Gemini 비전으로 읽었다. 읽기이지 생성이 아니다. "
        "표에 없는 항목은 빈칸으로 두게 지시했다. verified 는 사람이 원본 이미지와 "
        "대조한 뒤 true 로 바꾼다. 게시 전 검수는 여전히 필요하다.")
    doc["vision_failures"] = fails
    doc["gosi_ok_count"] = done
    doc["vision_at"] = datetime.now(timezone.utc).isoformat()
    GOSI.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n채운 칸 {filled} · 실패 {len(fails)}건")
    print(f"필수 4항목 완료 {done}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
