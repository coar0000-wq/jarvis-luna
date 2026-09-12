#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 상품 고시 항목과 상세 이미지를 수집한다.

이 스크립트는 data/gosi.json을 화장품 상품 고시정보 저장소로 사용한다.
파일 끝에는 실제 줄바꿈을 기록해야 하며, 문자 그대로 \\n을 기록하면 안 된다.
"""

from __future__ import annotations

import html as H
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
GOSI = DATA / "gosi.json"
IMGDIR = DATA / "daiso_real" / "gosi_img"
API = "https://fapi.daisomall.co.kr"
DELAY = 10.0
TIMEOUT = 30
PLACEHOLDER = ("상세페이지 참조", "-", "", "상세 페이지 참조")

FIELD = {
    "1": "volume",
    "5": "maker",
    "6": "origin",
    "7": "ingredients",
    "9": "warnings",
}

GOSI_LABEL = [
    ("volume", ("내용물의 용량 또는 중량", "내용물의 용량", "내용량", "용량", "중량")),
    ("ingredients", ("기재·표시하여야 하는 모든 성분", "기재·표시 하여야하는 모든 성분", "모든 성분", "전성분")),
    ("maker", ("화장품제조업자", "화장품책임판매업자", "제조업자", "책임판매업자", "제조판매업자")),
    ("origin", ("제조국", "원산지")),
    ("expiry", ("사용기한 또는 개봉 후 사용기간", "제조번호 및 사용기간", "사용기한", "개봉 후 사용기간")),
    ("warnings", ("사용할 때의 주의사항", "사용할때의 주의사항", "주의사항")),
    ("functional", ("기능성 화장품", "심사필")),
    ("usage", ("사용방법",)),
]

ALT_MIN = 200
ALT_RE = re.compile(r'<img[^>]*\salt="([^\"]{%d,})"' % ALT_MIN, re.I)
PAGE_URL = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"


def post(path: str, pd_no: str) -> dict[str, Any] | None:
    body = json.dumps({"pdNo": str(pd_no)}).encode()
    request = urllib.request.Request(
        API + path,
        data=body,
        method="POST",
        headers={
            "User-Agent": "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.daisomall.co.kr",
            "Referer": PAGE_URL.format(pd_no),
        },
    )
    try:
        return json.loads(
            urllib.request.urlopen(request, timeout=TIMEOUT)
            .read()
            .decode("utf-8", "replace")
        )
    except Exception:
        return None


def clean(value: Any) -> str:
    text = H.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def alt_texts(html: str) -> list[str]:
    return [H.unescape(value) for value in ALT_RE.findall(html or "")]


def to_lines(alt: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in alt.split("\n")
        if line.strip()
    ]


def gosi_from_alt(alt: str) -> dict[str, str]:
    output: dict[str, str] = {}
    lines = to_lines(alt)
    labels = [label for _, variants in GOSI_LABEL for label in variants]

    for key, variants in GOSI_LABEL:
        for index, line in enumerate(lines):
            matched = next((variant for variant in variants if variant in line), None)
            if not matched:
                continue

            value = line.split(matched, 1)[1].lstrip(" :·-").strip()
            if not value and index + 1 < len(lines):
                next_line = lines[index + 1]
                if not any(label in next_line for label in labels):
                    value = next_line

            value = re.sub(r"\s+", " ", value).strip()
            if value and value not in PLACEHOLDER:
                output[key] = value[:600]
            break

    return output


def page_gosi(pd_no: str) -> tuple[dict[str, str], str]:
    try:
        request = urllib.request.Request(
            PAGE_URL.format(pd_no),
            headers={"User-Agent": "JarvisLunaResearchBot/1.0"},
        )
        html = urllib.request.urlopen(request, timeout=TIMEOUT).read().decode(
            "utf-8", "replace"
        )
    except Exception as exc:
        return {}, type(exc).__name__

    found: dict[str, str] = {}
    for alt in alt_texts(html):
        for key, value in gosi_from_alt(alt).items():
            found.setdefault(key, value)
    return found, ""


def main() -> int:
    try:
        doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"data/gosi.json 읽기 실패: {exc}")
        return 1

    items = doc.get("items") or {}
    if isinstance(items, list):
        items = {
            str(row.get("product_id")): row
            for row in items
            if isinstance(row, dict) and row.get("product_id")
        }
        doc["items"] = items
    if not isinstance(items, dict):
        print("data/gosi.json의 items는 object 또는 list여야 합니다.")
        return 1

    IMGDIR.mkdir(parents=True, exist_ok=True)

    for pd_no, row in items.items():
        if not isinstance(row, dict):
            continue

        response = post("/pd/pdr/pdDtl/selPdDtlNtfc", str(pd_no))
        if response and response.get("success"):
            for item in response.get("data", []):
                match = re.match(r"\s*(\d+)\.", str(item.get("ntfcIemNm") or ""))
                value = clean(item.get("ntfcIemCn"))
                if not match or value in PLACEHOLDER:
                    continue
                key = FIELD.get(match.group(1))
                if key and not str(row.get(key) or "").strip():
                    row[key] = value

        time.sleep(DELAY)
        alt_values, _ = page_gosi(str(pd_no))
        for key, value in alt_values.items():
            if value and not str(row.get(key) or "").strip():
                row[key] = value
                row.setdefault("자동_출처", {})[key] = "상품 페이지 img alt (고시 표)"

        row["captured_at"] = datetime.now(timezone.utc).isoformat()

    doc["last_auto_run"] = datetime.now(timezone.utc).isoformat()
    # 중요: "\\n"이 아니라 실제 개행 문자인 "\n"을 사용한다.
    GOSI.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("DAISO gosi updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
