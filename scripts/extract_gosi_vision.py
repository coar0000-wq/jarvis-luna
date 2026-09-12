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
  - 상세 이미지가 여러 장이면 필수 4항목이 찰 때까지 순서대로 읽는다.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
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
FIELDS = (
    "volume", "ingredients", "maker", "origin", "warnings",
    "expiry", "functional",
)
NEED = ("ingredients", "volume", "maker", "origin")

PROMPT = """이 이미지는 한국 화장품의 '상품정보 제공고시' 표이거나 그 일부가 담긴 상세 이미지입니다.
표(또는 이미지)에 적힌 내용을 그대로 옮겨 JSON 으로만 답하세요.

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
- 마케팅 문구만 있고 고시 표가 없으면 모든 값을 "" 로 두세요.
- JSON 외에 다른 말을 붙이지 마세요."""


def http_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if payload else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(
            urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8")
        )
    except urllib.error.HTTPError as exc:
        # attempt 루프에서 status 코드를 쓰도록 보존
        body = exc.read().decode("utf-8", "replace")[:200]
        err = RuntimeError(f"HTTP {exc.code}: {body}")
        setattr(err, "code", exc.code)
        raise err from exc


def pick_models(key: str) -> list[str]:
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return [forced]
    try:
        d = http_json(f"{API_ROOT}/models?key={key}&pageSize=200")
    except Exception as exc:
        print(f"모델 목록 조회 실패: {exc}")
        return ["gemini-2.0-flash", "gemini-1.5-flash"]
    usable = [
        m["name"].replace("models/", "")
        for m in d.get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    order, seen = [], set()
    for pat in (
        "2.5-flash", "2.0-flash", "flash-latest", "1.5-flash",
        "2.5-pro", "1.5-pro", "pro",
    ):
        for name in usable:
            if pat in name.lower() and name not in seen:
                order.append(name)
                seen.add(name)
    return order[:3] or usable[:2]


def mime_of(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".png":
        return "image/png"
    if suf in (".webp",):
        return "image/webp"
    return "image/jpeg"


def read_table(key: str, models: list[str], img: Path) -> tuple[dict | None, str]:
    """이미지 한 장을 읽는다. 과부하 시 재시도·다른 모델 전환."""
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": mime_of(img), "data": b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    last = ""
    d = None
    used = ""
    for model in models:
        for attempt in range(1, 3):
            try:
                d = http_json(
                    f"{API_ROOT}/models/{model}:generateContent?key={key}",
                    payload,
                )
                used = model
                last = ""
                break
            except Exception as exc:
                code = getattr(exc, "code", None)
                last = f"{model} {type(exc).__name__}: {exc}"[:160]
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
    except (KeyError, IndexError, TypeError):
        return None, "응답에 텍스트가 없음"
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        parsed = json.loads(txt)
        if not isinstance(parsed, dict):
            return None, "JSON 객체가 아님"
        parsed["_model"] = used
        return parsed, ""
    except json.JSONDecodeError:
        return None, "JSON 파싱 실패"


def image_candidates(row: dict) -> list[Path]:
    """gosi_images → gosi_image 순으로 존재하는 파일만."""
    paths: list[Path] = []
    seen: set[str] = set()
    for key in ("gosi_images", "detail_image_paths"):
        for item in row.get(key) or []:
            s = str(item).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            paths.append(ROOT / s)
    single = str(row.get("gosi_image") or "").strip()
    if single and single not in seen:
        paths.append(ROOT / single)
    return [p for p in paths if p.exists() and p.stat().st_size > 500]


def needs_fill(row: dict) -> bool:
    return not all(str(row.get(f) or "").strip() for f in NEED)


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    items = doc.get("items") or {}
    if isinstance(items, list):
        items = {
            str(r.get("product_id") or r.get("pd_no")): r
            for r in items
            if isinstance(r, dict) and (r.get("product_id") or r.get("pd_no"))
        }
        doc["items"] = items

    if not key:
        doc["vision_status"] = "skipped - GEMINI_API_KEY 없음"
        GOSI.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("GEMINI_API_KEY 없음 - 건너뜀")
        return 0

    todo = {k: v for k, v in items.items() if isinstance(v, dict) and needs_fill(v)}
    if not todo:
        doc["vision_status"] = "ok"
        doc["vision_note"] = "필수 4항목이 모두 채워져 있어 호출하지 않았다."
        doc["vision_at"] = datetime.now(timezone.utc).isoformat()
        GOSI.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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

        imgs = image_candidates(row)
        if not imgs:
            fails.append({"pd_no": pd_no, "reason": "고시 이미지 없음 (collect 먼저 실행)"})
            continue

        wrote_total: list[str] = []
        last_err = ""
        used_img = ""
        used_model = ""

        # 마케팅 이미지 뒤에 고시 표가 오는 경우가 많아 뒤에서부터도 시도
        ordered = list(imgs)
        # 중간·끝 이미지에 고시 표가 있는 경우가 많음 → 앞 2장 + 뒤 전체
        if len(ordered) > 3:
            ordered = ordered[:2] + list(reversed(ordered[2:]))

        for img in ordered:
            if not needs_fill(row):
                break
            got, err = read_table(key, models, img)
            if got is None:
                last_err = err
                time.sleep(DELAY)
                continue
            used_img = str(img.relative_to(ROOT))
            used_model = str(got.pop("_model", models[0]))
            for f in FIELDS:
                v = str(got.get(f) or "").strip()
                if v and not str(row.get(f) or "").strip():
                    row[f] = v
                    wrote_total.append(f)
                    filled += 1
            time.sleep(DELAY)

        if not wrote_total and last_err:
            fails.append({"pd_no": pd_no, "reason": last_err})
        else:
            row["vision_source"] = f"gemini:{used_model or models[0]}"
            if used_img:
                row["vision_image"] = used_img
            row["verified"] = bool(row.get("verified"))
            row["vision_at"] = datetime.now(timezone.utc).isoformat()
            # 텍스트 미수집 목록 갱신
            row["텍스트_미수집"] = [
                f for f in NEED if not str(row.get(f) or "").strip()
            ]
            ing = str(row.get("ingredients") or "")
            print(
                f"  {pd_no}  {len(set(wrote_total))}칸 · "
                f"전성분 {len(ing)}자  {str(row.get('name'))[:24]}"
            )

    if deferred:
        print(f"예산 초과로 {len(deferred)}건은 다음 회차로 미룸")

    doc["vision_deferred"] = deferred
    done = sum(
        1 for r in items.values()
        if isinstance(r, dict) and all(str(r.get(f) or "").strip() for f in NEED)
    )
    doc["vision_status"] = "ok"
    doc["vision_note"] = (
        "용량·전성분은 상세 이미지에만 있어 Gemini 비전으로 읽었다. "
        "읽기이지 생성이 아니다. 표에 없는 항목은 빈칸. "
        "verified 는 사람이 원본 이미지와 대조한 뒤 true 로 바꾼다."
    )
    doc["vision_failures"] = fails
    doc["gosi_ok_count"] = done
    doc["vision_at"] = datetime.now(timezone.utc).isoformat()
    GOSI.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n채운 칸 {filled} · 실패 {len(fails)}건")
    print(f"필수 4항목 완료 {done}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
