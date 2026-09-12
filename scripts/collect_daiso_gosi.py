#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 상품 고시 항목과 상세 이미지를 수집한다.

중요 (다이소 실제 구조):
  - 고시 API(/pd/pdr/pdDtl/selPdDtlNtfc)는 대부분 "상세페이지 참조"만 돌려준다.
  - 사용자가 '상품설명 더보기'에서 보는 고시 표는 **상세 이미지**에 있다.
  - 상세 HTML(pdDtlDc)도 텍스트가 아니라 <img> 목록이다.
  - 그래서 텍스트 필드가 비어 있다고 해서 페이지에 고시가 없는 것이 아니다.

이 스크립트는
  1) API에서 쓸 수 있는 값(원산지 등)을 채우고
  2) 상세 이미지 URL을 받아 저장·다운로드하고
  3) 상품명/소개문에서 용량을 보조 추출하고
  4) **이미 채워진 값은 절대 빈 값으로 덮어쓰지 않는다.**
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
DELAY = 2.0
TIMEOUT = 30
PLACEHOLDER = (
    "상세페이지 참조",
    "상세 페이지 참조",
    "-",
    "",
    "없음",
    "해당없음",
)

# API 고시 항목 번호 → 필드
FIELD = {
    "1": "volume",
    "5": "maker",
    "6": "origin",
    "7": "ingredients",
    "9": "warnings",
    "3": "expiry",
    "4": "usage",
    "8": "functional",
}

PAGE_URL = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"


def post(path: str, pd_no: str) -> dict[str, Any] | None:
    body = json.dumps({"pdNo": str(pd_no)}).encode()
    request = urllib.request.Request(
        API + path,
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
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
    except Exception as exc:
        print(f"  API 실패 {path}: {type(exc).__name__}")
        return None


def clean(value: Any) -> str:
    text = H.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def is_placeholder(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    if v in PLACEHOLDER:
        return True
    if "상세페이지" in v or "상세 페이지" in v:
        return True
    return False


def set_if_empty(row: dict[str, Any], key: str, value: str, source: str) -> None:
    """이미 값이 있으면 유지. 빈칸일 때만 채운다."""
    if not value or is_placeholder(value):
        return
    if str(row.get(key) or "").strip():
        return
    row[key] = value
    row.setdefault("자동_출처", {})[key] = source


def volume_from_text(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G|kg|KG)\b",
        text,
    )
    if not m:
        return ""
    return f"{m.group(1)}{m.group(2).lower()}"


def download_image(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    try:
        # CDN resize 파라미터 제거해 원본에 가깝게
        clean_url = re.sub(r"/dims/.*$", "", url)
        req = urllib.request.Request(
            clean_url,
            headers={"User-Agent": UA, "Referer": "https://www.daisomall.co.kr/"},
        )
        data = urllib.request.urlopen(req, timeout=TIMEOUT).read()
        if len(data) < 500:
            return False
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def collect_one(pd_no: str, row: dict[str, Any]) -> None:
    name = str(row.get("name") or "")
    print(f"- {pd_no} {name[:40]}")

    # 1) 공식 고시 API (대부분 '상세페이지 참조' — 원산지 정도만 실값)
    response = post("/pd/pdr/pdDtl/selPdDtlNtfc", str(pd_no))
    api_filled = 0
    if response and response.get("success"):
        for item in response.get("data") or []:
            match = re.match(r"\s*(\d+)\.", str(item.get("ntfcIemNm") or ""))
            value = clean(item.get("ntfcIemCn"))
            if not match or is_placeholder(value):
                continue
            key = FIELD.get(match.group(1))
            if key:
                before = str(row.get(key) or "").strip()
                set_if_empty(row, key, value, "daiso_api:selPdDtlNtfc")
                if not before and str(row.get(key) or "").strip():
                    api_filled += 1
    print(f"  API 실값 {api_filled}칸")

    time.sleep(DELAY)

    # 2) 상세 설명 API — 고시는 이미지로 들어 있음
    desc_res = post("/pd/pdr/pdDtl/selPdDtlDesc", str(pd_no))
    detail_imgs: list[str] = []
    if desc_res and desc_res.get("success"):
        desc = ((desc_res.get("data") or {}).get("pdDtlDesc") or {})
        raw_html = H.unescape(desc.get("pdDtlDc") or "")
        detail_imgs = re.findall(r'src="(https?://[^"]+)"', raw_html)
        # 소개 텍스트에서 용량·기능성 보조 추출
        vsip = clean(H.unescape(str(desc.get("vsipPdDtl") or "")))
        if vsip:
            row["detail_blurb"] = vsip[:800]
            vol = volume_from_text(vsip)
            set_if_empty(row, "volume", vol, "daiso_api:vsipPdDtl")
            if "기능성" in vsip:
                set_if_empty(
                    row,
                    "functional",
                    "기능성 화장품(상세 소개문)",
                    "daiso_api:vsipPdDtl",
                )

    # 3) 상품명에서 용량
    set_if_empty(row, "volume", volume_from_text(name), "product_name")

    # 4) 상세 이미지 저장 (사용자가 더보기에서 보는 그 고시 이미지)
    IMGDIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for i, url in enumerate(detail_imgs):
        # 파일명: {pdNo}_{index}.jpg
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        dest = IMGDIR / f"{pd_no}_{i:02d}{ext}"
        if download_image(url, dest):
            saved.append(str(dest.relative_to(ROOT)))
        time.sleep(0.3)

    if detail_imgs:
        row["detail_images"] = detail_imgs
    if saved:
        row["gosi_image"] = saved[0]
        row["gosi_images"] = saved
        row["고시_위치"] = (
            "텍스트 API는 '상세페이지 참조'만 반환. "
            "실제 고시 표는 상품설명 더보기 상세 이미지에 있음. "
            "비전/OCR 또는 수동 입력이 필요."
        )
        print(f"  상세 이미지 {len(saved)}/{len(detail_imgs)}장 저장")
    else:
        print("  상세 이미지 없음/다운로드 실패")

    row["captured_at"] = datetime.now(timezone.utc).isoformat()
    # 비어 있는 필수칸 표시 (거짓으로 '완료'라고 쓰지 않음)
    missing = [
        k for k in ("volume", "maker", "origin", "ingredients")
        if not str(row.get(k) or "").strip()
    ]
    row["텍스트_미수집"] = missing
    if missing and saved:
        row["다음_조치"] = (
            f"이미지 {len(saved)}장에서 비전으로 {', '.join(missing)} 추출 필요"
        )


def main() -> int:
    try:
        doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"data/gosi.json 읽기 실패: {exc}")
        return 1

    items = doc.get("items") or {}
    if isinstance(items, list):
        items = {
            str(row.get("product_id") or row.get("pd_no")): row
            for row in items
            if isinstance(row, dict)
            and (row.get("product_id") or row.get("pd_no"))
        }
        doc["items"] = items
    if not isinstance(items, dict):
        print("data/gosi.json의 items는 object 또는 list여야 합니다.")
        return 1

    print(f"고시 수집 대상 {len(items)}건")
    print("참고: 다이소 고시 본문은 이미지고, API는 '상세페이지 참조'가 기본입니다.")

    for pd_no, row in items.items():
        if not isinstance(row, dict):
            continue
        try:
            collect_one(str(pd_no), row)
        except Exception as exc:
            print(f"  오류 {pd_no}: {exc}")
            row["collect_error"] = f"{type(exc).__name__}: {exc}"

    doc["last_auto_run"] = datetime.now(timezone.utc).isoformat()
    doc["수집_설명"] = (
        "공식 고시 API는 대부분 '상세페이지 참조'. "
        "사용자가 보는 고시 표는 상품설명 더보기 상세 이미지. "
        "이미지는 data/daiso_real/gosi_img/ 에 저장. "
        "전성분·제조사는 비전 추출 또는 수동 입력이 필요하다."
    )
    GOSI.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("DAISO gosi updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
