#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 상세 이미지를 영문 패널로 바꾼다. 1084687 수작업 방식을 자동화한 것.

기준이 된 수작업 (data/manual/image_localization/1084687.json, 2026-10-16)
  사용자가 Shopify 9590780723457 (Dr.CPU+ 글루타치온 캡슐크림) 을 이미지 등록의
  기본 방식으로 지정했다. 그 상품은
    - 다이소 상세 이미지(상품설명 더보기 아래 /description/ 이미지)를 구간별로 잘라
    - 한글 설명을 지우고 영문을 같은 자리에 얹었다 (생성형 이미지 없이 로컬 합성)
    - 미백·주름 표현은 일반 화장품 표현으로 바꿨다
    - 01-...-en ~ 11-...-en 순서·이름으로 비공개 초안에 올렸다
  그런데 그 과정은 저장소 밖에서 사람이 했고 코드가 없었다. 일일 등록은 검수
  허용 목록의 썸네일만 정사각 JPEG 로 올렸고, 허용 목록에는 1067498 하나뿐이라
  나머지 상품은 이미지 0장으로 초안에 머물렀다 (2026-10-17 실측).

이 모듈이 하는 일 (상품 하나)
  1) 렌더링된 상품 페이지에서 /description/ 이미지를 찾는다 (requests 로는 안 보인다)
  2) 긴 상세 이미지를 균일 배경 띠에서 잘라 패널로 나눈다
  3) 패널마다 OCR(tesseract kor+eng)로 한글 줄의 위치를 찾는다
  4) 번역기가 그 줄들의 영문을 준다 (Gemini 무료 등급이 패널 이미지를 직접 읽는다.
     OCR 글자는 위치만 쓰고 번역 근거로 믿지 않는다). 번역기가 없으면 영문화하지 않는다
  5) 한글 글자 픽셀만 지우고(OpenCV inpaint, 비생성형) 영문을 얹는다
  6) 검사: 사람 얼굴(YuNet) · 고시 표 패널 · 미국 금칙 표현 · 다시 OCR 해서 한글 잔존
     하나라도 걸리면 그 패널은 쓰지 않는다. 조용히 통과시키지 않고 사유를 남긴다
  7) 결과 매니페스트를 data/image_localization/<pdNo>.json 에 쓴다.
     이미지 파일은 저장소에 넣지 않는다 (등록 실행 중 임시 폴더에서 바로 올린다)

하지 않는 것
  - 이미지 생성 API 를 쓰지 않는다. 제품 사진은 다이소 원본 그대로다.
  - 번역이 없으면 지어내지 않는다. 그 패널은 빠지고 사유가 남는다.
  - 문구 검사를 통과해도 법률·안전 승인이 아니다 (us_claim_rules.json 의 원칙).

사용
  python scripts/daiso/localize_detail_images.py 1084687 --out out/localized
  python scripts/daiso/localize_detail_images.py 1084687 --out out/localized --translations reviewed.json
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MANIFEST_DIR = DATA / "image_localization"
CLAIM_RULES = DATA / "us_claim_rules.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
sys.path.insert(0, str(ROOT / "scripts"))

PAGE = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
HANGUL = re.compile(r"[가-힣]")
REGULATORY_MARKERS = ("식약처", "심사", "보고서", "식품의약품안전처")
REMOVE = "[remove]"
METHOD = ("non-generative local text compositing over supplier detail images "
          "(OCR boxes + OpenCV inpaint + rendered English); no image generation API")

# 패널 자르기. 1084687 상세(850x15977)를 이 값으로 자르면 12조각, 714~1900px.
# 수작업 원본 11장(469x690 축소본)의 구간과 거의 같은 자리에서 잘렸다.
CUT_STD = 3.0          # 이 표준편차 아래인 가로줄은 균일 배경
CUT_RUN = 24           # 균일 배경이 이만큼 이어져야 자를 후보
PANEL_MIN, PANEL_TARGET, PANEL_MAX, PANEL_TAIL = 700, 1250, 1900, 350

# 결과물 재판독 기준
RESIDUAL_CONF = 80.0   # 결과물 재판독에서 이 신뢰도 이상인 한글이 남으면 실패
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans{bold}.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-{lbold}.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-{nbold}.ttf",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- 1) 상세 이미지 찾기

def rendered_detail_image_urls(pd_no: str, scrolls: int = 40) -> list[str]:
    """상품설명 더보기를 누르고 끝까지 내린 뒤 editor-content 의 /description/ 이미지.

    CLAUDE.md (2026-09-13): editor-content 는 스크립트가 그린다. HTTP 원본에는 없다.
    """
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    js = ("()=>[...document.querySelectorAll('div.editor-content img')]"
          ".map(i=>i.currentSrc||i.src).filter(s=>s.includes('/description/'))")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(locale="ko-KR", user_agent=UA)
            page.goto(PAGE.format(pd_no), timeout=60000, wait_until="domcontentloaded")
            btn = page.locator('button:has-text("상품설명 더보기")')
            try:
                btn.first.wait_for(state="visible", timeout=15000)
            except Exception:  # noqa: BLE001  버튼 없는 상품도 있다
                pass
            if btn.count():
                btn.first.click(timeout=8000)
            found: list[str] = []
            for _ in range(scrolls):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(900)
                for u in page.evaluate(js) or []:
                    if u not in found:
                        found.append(u)
            return found
        finally:
            browser.close()


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


# ---------------------------------------------------------------- 2) 패널 자르기

def panel_cuts(gray) -> list[int]:
    """균일 배경 띠의 가운데에서 자른다. 목표 높이에 가깝고 띠가 두꺼운 곳을 고른다."""
    import numpy as np  # noqa: PLC0415

    h = gray.shape[0]
    flat = list(gray.std(axis=1) < CUT_STD) + [False]
    runs, start = [], None
    for y, f in enumerate(flat):
        if f and start is None:
            start = y
        elif not f and start is not None:
            if y - start >= CUT_RUN:
                runs.append(((start + y) // 2, y - start))
            start = None
    cuts = [0]
    while h - cuts[-1] > PANEL_MAX:
        s = cuts[-1]
        options = [(c, w) for c, w in runs if PANEL_MIN <= c - s <= PANEL_MAX]
        c = (max(options, key=lambda cw: cw[1] - abs(cw[0] - s - PANEL_TARGET) * 0.05)[0]
             if options else s + PANEL_MAX)
        cuts.append(int(c))
    if h - cuts[-1] < PANEL_TAIL and len(cuts) > 1:
        cuts.pop()                      # 너무 짧은 꼬리는 앞 패널에 붙인다
    cuts.append(h)
    del np
    return cuts


# ---------------------------------------------------------------- 3) 글줄 찾기 + OCR
#
# 처음에는 tesseract 의 쪽 판독(psm 3/11) 상자를 그대로 썼다. 1084687 에서 실측하니
#   - 한 문장이 상자 두세 개로 쪼개지고 (패널2 "핵심 성분 안정화" 가 3조각)
#   - 세 단 문단이 한 상자로 묶이고 (패널5)
#   - "한 알에 담은 듀얼 포뮬러" "#미백케어 #글루타치온" 같은 줄은 아예 못 찾았다.
# 그래서 글줄 위치는 이미지 처리(형태학 기울기 + 가로 닫기)로 먼저 찾고,
# tesseract 는 그 한 줄만 잘라 읽어(psm 7) 한글 줄인지 판정하는 데만 쓴다.
# 같은 네 패널에서 빠진 줄 없이 줄 단위 상자가 나왔다.

# Two processes, one OpenMP thread each: avoid nested Tesseract oversubscription.
# Preserve every input pixel; oversized inputs fail review rather than downsampling
# small Korean ingredient/warning text or silently omitting candidate lines.
OCR_WORKERS = 2
OCR_LINE_SECONDS = 60
OCR_PANEL_SECONDS = 180
OCR_MAX_LINE_PIXELS = 1_000_000
OCR_MAX_PANEL_PIXELS = 8_000_000
OCR_MAX_BOXES = 256
_OCR_READY: bool | None = None


def _ocr_env() -> dict[str, str]:
    return {**os.environ, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}


def ensure_ocr_ready() -> None:
    """한국어 OCR 이 실제로 실리는지 확인한다. 안 되면 멈춘다 (조용히 통과하지 않는다).

    2026-10-17 실측: kor.traineddata 가 378바이트 오류 응답으로 깨져 있었는데
    `tesseract --list-langs` 는 kor 를 보여 줬고, 판독 호출은 종료 코드 0 으로
    영어로만 읽었다. 그 결과 한글이 그대로 박힌 1084687 패널 11장이 '한글 없음'
    으로 판정돼 '-en' 이름으로 통과했다. 언어를 못 실으면 tesseract 는 stderr 에
    "Failed loading language" 를 남긴다. 그 줄과 파일 크기를 함께 본다.
    """
    global _OCR_READY
    if _OCR_READY:
        return
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract_missing")
    langs = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=30, env=_ocr_env())
    if langs.returncode != 0:
        raise RuntimeError("tesseract_language_probe_failed")
    listed = (langs.stdout + langs.stderr).decode("utf-8", "ignore").split()
    if "kor" not in listed:
        raise RuntimeError("tesseract_kor_missing")
    from PIL import Image  # noqa: PLC0415

    buf = io.BytesIO()
    Image.new("RGB", (60, 30), (255, 255, 255)).save(buf, "PNG")
    _tess(["-l", "kor+eng", "--psm", "7"], buf.getvalue(), 60)
    _OCR_READY = True


def _tess(args: list[str], data: bytes, timeout: float, *, deadline: float | None = None) -> bytes:
    """At most two full-resolution attempts within one wall-clock budget.

    A killed process is reaped by subprocess.run before retry. Never interpret a
    timeout, language-load failure or nonzero exit as an empty/no-Korean result.
    """
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract_missing")
    end = min(time.monotonic() + timeout, deadline if deadline is not None else float("inf"))
    for attempt in range(2):
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("ocr_budget_exhausted")
        try:
            out = subprocess.run([exe, "stdin", "stdout", *args], input=data,
                                 capture_output=True, timeout=remaining / (2 - attempt),
                                 env=_ocr_env())
        except subprocess.TimeoutExpired as exc:
            if attempt == 1:
                raise RuntimeError("ocr_timeout_after_retry") from exc
            continue
        if b"Failed loading language" in out.stderr or b"Error opening data file" in out.stderr:
            raise RuntimeError("tesseract_language_unloadable")
        if out.returncode != 0:
            raise RuntimeError(f"tesseract_exit:{out.returncode}")
        return out.stdout
    raise RuntimeError("ocr_timeout_after_retry")


def _area(b) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b) -> int:
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def text_line_boxes(rgb, *, deadline: float | None = None) -> list[list[int]]:
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    # 회색 한 채널이 아니라 R·G·B 각 채널 기울기의 최댓값을 쓴다. 베이지 사진 위 주황 글씨
    # ('3가지 맞춤 솔루션', 1084687 패널9)는 밝기 차이가 작아 회색 기울기로는 상자가 안 생겼다.
    k = np.ones((3, 3), np.uint8)
    grad = np.max(np.stack([cv2.morphologyEx(rgb[:, :, c], cv2.MORPH_GRADIENT, k) for c in range(3)]), axis=0)
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3)))
    n, _, st, _ = cv2.connectedComponentsWithStats(bw, 8)
    boxes = []
    for i in range(1, n):
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError("ocr_budget_exhausted")
        x, y, w, h, area = (int(v) for v in st[i])
        if 8 <= h <= 90 and w >= 14 and w / h >= 1.2 and area / (w * h) >= 0.25:
            boxes.append([x, y, x + w, y + h])
            if len(boxes) > OCR_MAX_BOXES:
                raise RuntimeError("ocr_line_count_budget_exceeded")
    # 큰 글씨는 낱말 사이가 넓어 낱말마다 상자가 생긴다. 같은 줄이고 간격이 글자 높이 이내면 잇는다.
    # 단(열) 사이는 글자 높이보다 넓어서 이어지지 않는다 (1084687 패널5 세 단 확인).
    boxes.sort(key=lambda b: (b[1], b[0]))
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError("ocr_budget_exhausted")
            for j in range(len(boxes)):
                if i == j:
                    continue
                a, b = boxes[i], boxes[j]
                ha, hb = a[3] - a[1], b[3] - b[1]
                vov = min(a[3], b[3]) - max(a[1], b[1])
                gap = b[0] - a[2]
                if (vov >= 0.6 * min(ha, hb) and abs(ha - hb) <= 0.45 * max(ha, hb)
                        and -2 <= gap <= 1.0 * max(ha, hb)):
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    boxes.pop(j)
                    changed = True
                    break
            if changed:
                break
    return boxes


def ocr_line(rgb, box, *, deadline: float | None = None) -> tuple[str, float]:
    """한 줄만 잘라 읽는다. 작은 글씨는 두 배로 키워 읽는다."""
    from PIL import Image  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415

    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract_missing")
    end = min(time.monotonic() + OCR_LINE_SECONDS, deadline if deadline is not None else float("inf"))
    if time.monotonic() >= end:
        raise RuntimeError("ocr_budget_exhausted")
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = max(0, box[0] - 4), max(0, box[1] - 4), min(w, box[2] + 4), min(h, box[3] + 4)
    import numpy as np  # noqa: PLC0415

    from PIL import ImageOps  # noqa: PLC0415

    scale = 2 if y1 - y0 < 40 else 1
    if (x1 - x0) * (y1 - y0) <= 0:
        raise RuntimeError("ocr_invalid_line_box")
    if ((x1 - x0) * scale + 40) * ((y1 - y0) * scale + 40) > OCR_MAX_LINE_PIXELS:
        raise RuntimeError("ocr_line_size_budget_exceeded")
    crop = Image.fromarray(rgb[y0:y1, x0:x1])
    if crop.height < 40:
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    # 둘레에 배경색 여백을 준다. 여백 없이 자르면 1084687 패널7 '덜어냅니다' 가 'S40 HLCp'(신뢰도 0)
    # 로 읽혔고, 같은 줄에 20px 여백을 주면 '덜어냄니다' 로 읽혔다.
    edge = np.concatenate([np.array(crop)[0], np.array(crop)[-1]])
    crop = ImageOps.expand(crop, border=20, fill=tuple(int(v) for v in np.median(edge, axis=0)))

    def read(img, lang) -> tuple[str, float]:
        if img.width * img.height > OCR_MAX_LINE_PIXELS:
            raise RuntimeError("ocr_line_size_budget_exceeded")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        stdout = _tess(["-l", lang, "--psm", "7", "-c", "tessedit_create_tsv=1"], buf.getvalue(), OCR_LINE_SECONDS, deadline=end)
        words = [r for r in csv.DictReader(io.StringIO(stdout.decode("utf-8", "ignore")),
                                           delimiter="\t", quoting=csv.QUOTE_NONE)
                 if r.get("level") == "5" and (r.get("text") or "").strip()]
        if not words:
            return "", 0.0
        return " ".join(w["text"] for w in words), sum(float(w["conf"]) for w in words) / len(words)

    import cv2  # noqa: PLC0415

    # 이진화는 상자 그대로 자른 조각에서 하고, 흰 여백은 그 뒤에 붙인다. 바깥 흰 바탕이나
    # 여백 색까지 넣고 이진화하면 주황 배지('수분 충전 케어')에서 빈 값이 나왔다.
    exact = rgb[box[1]:box[3], box[0]:box[2]]           # 바깥 여백 4px 없이 상자 그대로
    if exact.shape[0] < 40:
        exact = cv2.resize(exact, (exact.shape[1] * 2, exact.shape[0] * 2), interpolation=cv2.INTER_LANCZOS4)
    g = cv2.cvtColor(exact, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw == 0).mean() > 0.5:          # 검은 쪽이 다수면 그쪽이 배경이다 → 글씨가 검게 뒤집는다
        bw = 255 - bw
    binary = ImageOps.expand(Image.fromarray(bw), border=20, fill=255)
    # 차례로 읽어 한글 두 자 이상이 신뢰도 50 이상으로 나오면 멈춘다.
    #   kor+eng 원본 → kor 원본 → kor+eng 이진화 → kor 이진화
    # 1084687 실측: '덜어냅니다' 는 kor+eng 로는 'BO} SLICt', kor 단독으로는 '덜어냄니다'.
    # 색 배지 위 흰 글씨('집중 영양 케어')는 이진화해야 읽혔다. 영문 줄(LACTO EXOSOME 등)은
    # kor 단독으로 읽으면 엉뚱한 한글이 나올 수 있어 신뢰도 50 을 함께 요구한다.
    first = read(crop, "kor+eng")
    for img, lang in ((crop, "kor+eng"), (crop, "kor"), (binary, "kor+eng"), (binary, "kor")):
        text, conf = first if (img is crop and lang == "kor+eng") else read(img, lang)
        if len(HANGUL.findall(text)) >= 2 and conf >= 50:
            return text, conf
    return first


def korean_lines(rgb) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    if rgb.shape[0] * rgb.shape[1] > OCR_MAX_PANEL_PIXELS:
        raise RuntimeError("ocr_panel_size_budget_exceeded")
    end = time.monotonic() + OCR_PANEL_SECONDS
    boxes = text_line_boxes(rgb, deadline=end)
    if time.monotonic() >= end:
        raise RuntimeError("ocr_budget_exhausted")
    if len(boxes) > OCR_MAX_BOXES:
        raise RuntimeError("ocr_line_count_budget_exceeded")
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        reads = list(pool.map(lambda b: ocr_line(rgb, b, deadline=end), boxes))
    import numpy as np  # noqa: PLC0415

    out = []
    for b, (text, conf) in zip(boxes, reads):
        # 한글 두 자 이상이면 신뢰도와 상관없이 한글 줄로 본다. 보라 띠 위 흰 글씨 '미백 캡슐' 은
        # 'ZH' 로 반쯤 읽혀 신뢰도 35 였고, 45 기준에서 빠져 결과물에 한글이 남았다 (1084687 패널2).
        hangul = len(HANGUL.findall(text))
        if hangul >= 2 or (hangul >= 1 and conf >= 45):
            q = (rgb[b[1]:b[3], b[0]:b[2]].reshape(-1, 3) // 16).astype(np.int16)
            vals, counts = np.unique(q, axis=0, return_counts=True)
            out.append({"box": b, "ocr": text, "conf": round(conf, 1),
                        "bg": [int(v) * 16 + 8 for v in vals[counts.argmax()]]})
    return out


def group_units(lines: list[dict]) -> list[dict]:
    """이어지는 줄을 한 번역 단위로 묶는다. 한국어 문장은 줄을 넘어 이어진다.

    아래 줄이 바로 붙어 있고(줄 간격 < 글자 높이) 글자 크기가 비슷하고
    왼쪽 끝 또는 가운데가 맞으면 같은 문단이다. 크기 허용치를 35% 로 두었더니
    1084687 패널5 의 단 제목(30px)이 아래 본문(22px)과 한 단위로 묶였다. 22% 로 줄였다.
    """
    units: list[dict] = []
    for ln in sorted(lines, key=lambda l: (l["box"][1], l["box"][0])):
        b = ln["box"]
        h = b[3] - b[1]
        for u in units:
            last = u["lines"][-1]["box"]
            lh = last[3] - last[1]
            gap = b[1] - last[3]
            left = abs(b[0] - last[0]) <= max(6, 0.4 * lh)
            center = abs((b[0] + b[2]) / 2 - (last[0] + last[2]) / 2) <= max(8, 0.6 * lh)
            same_bg = max(abs(x - y) for x, y in zip(ln.get("bg") or [0, 0, 0],
                                                     u["lines"][-1].get("bg") or [0, 0, 0])) <= 40
            # 배경이 다른 줄(주황 배지·띠 위 글씨)은 위 문단과 묶지 않는다. 1084687 패널0 에서
            # 큰 제목 두 줄과 아래 #해시태그 배지가 한 단위가 되어 영문이 배지 밖으로 나갔다.
            if -2 <= gap <= 0.9 * lh and abs(h - lh) <= 0.22 * max(h, lh) and (left or center) and same_bg:
                u["lines"].append(ln)
                break
        else:
            units.append({"lines": [ln]})
    for i, u in enumerate(units, 1):
        bs = [l["box"] for l in u["lines"]]
        u["id"] = i
        u["box"] = [min(x[0] for x in bs), min(x[1] for x in bs), max(x[2] for x in bs), max(x[3] for x in bs)]
        u["ocr"] = " / ".join(l["ocr"] for l in u["lines"])
        lefts = [x[0] for x in bs]
        centers = [(x[0] + x[2]) / 2 for x in bs]
        u["align"] = "left" if len(bs) > 1 and max(lefts) - min(lefts) <= 6 else (
            "center" if len(bs) > 1 and max(centers) - min(centers) <= 10 else "auto")
    return units


def hangul_boxes(img_bytes: bytes) -> list[dict]:
    """한글 번역 단위 (id, box, lines, ocr, align)."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    rgb = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
    return group_units(korean_lines(rgb))


def page_hangul(img_bytes: bytes) -> list[str]:
    """쪽 전체 판독(psm 11). 줄 찾기와 다른 방법이라 줄 찾기가 놓친 글을 잡는다."""
    stdout = _tess(["-l", "kor+eng", "--psm", "11", "-c", "tessedit_create_tsv=1"], img_bytes, 180)
    rows = csv.DictReader(io.StringIO(stdout.decode("utf-8", "ignore")), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [r["text"] for r in rows if r.get("level") == "5" and float(r.get("conf") or -1) >= RESIDUAL_CONF
            and len(HANGUL.findall(r.get("text") or "")) >= 2]


# 번역한 자리 밖에서 줄 판독이 한글을 보았을 때, 이 신뢰도 이상이어야 남은 한글로 센다.
# 2026-10-17 1084687 패널1 실측: 원본의 실제 한글 줄 신뢰도 87.4~95.1 (9줄),
# 사진 속 용기 반사·인쇄를 한글로 잘못 읽은 것은 13.8~45.8 (3줄). 합성 결과물에서는
# 반사 잡음 '이글' 19.1, '나그' 19.7 이 새로 잡혀 제대로 된 패널이 통째로 버려졌다.
# 그 사이(60)에 둔다. 번역한 자리 안은 신뢰도와 상관없이 센다 (지우기 실패는 반드시 잡는다).
OUTSIDE_RESIDUAL_CONF = 60.0


def residual_hangul(img_bytes: bytes, ignore: list[list[int]] | None = None,
                    translated: list[list[int]] | None = None) -> list[str]:
    """결과물에 남은 한글. 줄 단위 판독과 쪽 전체 판독 두 방법으로 본다.

    같은 방법으로만 다시 보면 처음에 놓친 줄은 다시 봐도 놓친다 (1084687 패널8 배지).
    그래서 독립된 쪽 판독(psm 11)을 함께 쓴다. 줄 판독은 한글 두 자 이상이면 신뢰도와
    상관없이 센다 (보수적: 영문 줄을 한글로 잘못 읽어 패널을 버리는 쪽이 한글이 남는 것보다 낫다).
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    rgb = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
    # 번역기가 이미지를 보고 '한글 아님'("") 으로 답한 자리(사진 질감·영문 제목을 OCR 이
    # 한글로 잘못 읽은 곳)는 줄 판독에서 다시 세지 않는다. 1084687 패널7 의 'HOW TO USE' 가
    # '나 가시 니 오 도' 로 읽혔다. 쪽 판독(psm 11, 신뢰도 80 이상)은 이 예외 없이 그대로 본다.
    ignore = ignore or []

    def ignored(b):
        return any(_inter(b, g) >= 0.5 * min(_area(b), _area(g)) for g in ignore)

    def in_translated(b):
        if translated is None:          # 자리 정보를 안 주면 예전처럼 전부 센다
            return True
        return any(_inter(b, g) > 0 for g in translated)

    left = [l["ocr"] for l in korean_lines(rgb)
            if len(HANGUL.findall(l["ocr"])) >= 2 and not ignored(l["box"])
            and (in_translated(l["box"]) or l["conf"] >= OUTSIDE_RESIDUAL_CONF)]
    return left + page_hangul(img_bytes)


# ---------------------------------------------------------------- 4) 번역

TRANSLATE_PROMPT = """You localize a Korean cosmetics product detail image into US English.
The numbered boxes below were found by OCR on the attached image. The OCR text may be wrong;
read the Korean in the image itself at each box position (pixel boxes x0,y0,x1,y1).
Rules:
- Return natural, short English marketing copy that fits the same space. Keep numbers, units, ratios and ingredient names exact.
- Do not add any claim that is not in the image. No medical, drug, FDA, clinical or dermatologist claims.
- Korean regulatory or drug-like claims (미백, 주름개선, 기능성 화장품, 치료, 재생) must become cosmetic wording:
  whitening -> "for a brighter-looking complexion"; anti-wrinkle -> "helps smooth the look of fine lines";
  "functional cosmetic" -> omit.
- If a box holds Korean regulatory status (기능성 화장품, 식약처) or a claim that cannot be made cosmetic, return "[remove]":
  the Korean is erased and nothing is written.
- If a box is not Korean text at all (logo, packaging print, noise), return "" and it is left untouched.
Return JSON only: {"items":[{"id":1,"en":"..."}]}
Product: __TITLE__
Boxes:
__BOXES__"""


class GeminiTranslator:
    """무료 등급 Gemini 가 패널 이미지를 보고 번역한다. 이미지 생성은 하지 않는다."""

    name = "gemini_vision_translation"
    # 회차(프로세스) 전체 호출 상한과 정지. 무료 등급인지는 코드가 확인할 수 없다
    # (scripts/gemini_escalation.py 와 같은 전제). 그래서 호출 수를 묶고, 401/402/403/429 가
    # 한 번이라도 나면 그 회차에는 더 부르지 않는다. 상품 3개 × 패널 약 10장 기준 30.
    calls = 0
    stopped: str | None = None
    MAX_CALLS = int(os.environ.get("LOCALIZE_MAX_TRANSLATION_CALLS", "30"))

    def __init__(self, key: str, model: str):
        self.key, self.model = key, model

    def translate(self, panel_png: bytes, boxes: list[dict], title: str, panel_sha: str) -> dict[int, str]:
        cls = GeminiTranslator
        if cls.stopped:
            raise RuntimeError(f"translator_stopped:{cls.stopped}")
        if cls.calls >= cls.MAX_CALLS:
            raise RuntimeError("translation_call_budget_exhausted")
        cls.calls += 1
        try:
            return self._translate(panel_png, boxes, title)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 402, 403, 429):
                cls.stopped = f"http_{exc.code}"
            raise

    def _translate(self, panel_png: bytes, boxes: list[dict], title: str) -> dict[int, str]:
        listing = "\n".join(f'{b["id"]}: box={b["box"]} lines={len(b.get("lines") or [1])} ocr="{b["ocr"]}"'
                             for b in boxes)
        body = {
            "contents": [{"parts": [
                {"text": TRANSLATE_PROMPT.replace("__TITLE__", title).replace("__BOXES__", listing)},
                {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(panel_png).decode()}},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.key}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            doc = json.loads(r.read())
        text = doc["candidates"][0]["content"]["parts"][0]["text"]
        items = json.loads(text).get("items") or []
        return {int(i["id"]): str(i.get("en") or "").strip() for i in items if "id" in i}


class FileTranslator:
    """사람(또는 검토자)이 확인한 번역 파일. 패널 sha256 + 상자 번호로 찾는다.

    형식: {"translator": "누가 번역했는지 사실대로", "panels": {"<sha256>": {"1": "English", ...}}}
    """

    def __init__(self, path: Path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        self.name = f"reviewed_file:{doc.get('translator') or 'unspecified'}"
        self.panels = doc.get("panels") or {}

    def translate(self, panel_png, boxes, title, panel_sha):
        got = self.panels.get(panel_sha)
        if got is None:
            raise LookupError("no_reviewed_translation_for_panel")
        return {int(k): str(v) for k, v in got.items()}


def translator_from_env(path: str | None = None):
    if path:
        return FileTranslator(Path(path))
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return GeminiTranslator(key, os.environ.get("GEMINI_VISION_MODEL", "gemini-flash-latest"))
    return None


# ---------------------------------------------------------------- 문구 검사

def claim_rules() -> tuple[list[str], dict[str, str]]:
    doc = json.loads(CLAIM_RULES.read_text(encoding="utf-8"))
    banned = [t.lower() for g in (doc.get("banned") or {}).values() if isinstance(g, list) for t in g]
    return banned, {k.lower(): v for k, v in (doc.get("safe_alternatives") or {}).items()}


def guard_claims(text: str, banned: list[str], safe: dict[str, str]) -> tuple[str, list[str]]:
    """안전한 대체 표현이 있으면 바꾸고, 그래도 남는 금칙어는 돌려준다 (그 패널은 버린다)."""
    out = text
    for bad, good in sorted(safe.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{re.escape(bad)}\b", good, out, flags=re.I)
    low = out.lower()
    hits = sorted({b for b in banned if re.search(rf"(?<![a-z]){re.escape(b)}(?![a-z])", low)})
    return out, hits


# ---------------------------------------------------------------- 5) 지우고 얹기

def font_path(bold: bool) -> str:
    """저장소에 넣은 Poppins(OFL) 를 먼저 쓴다. 러너마다 시스템 글꼴이 달라 결과가 흔들렸다.

    처음 DejaVu Sans Bold 로 그렸더니 글자 폭이 넓어 1084687 제목이 세 줄로 꺾였다.
    """
    own = ROOT / "assets" / "fonts" / ("Poppins-Bold.ttf" if bold else "Poppins-Regular.ttf")
    if own.exists():
        return str(own)
    for pattern in FONT_CANDIDATES:
        p = pattern.format(bold="-Bold" if bold else "", lbold="Bold" if bold else "Regular",
                           nbold="Bold" if bold else "Regular")
        if Path(p).exists():
            return p
    raise RuntimeError("latin_font_missing")


def _wrap(draw, text, font, box_w):
    lines = []
    for para in text.split("\n"):        # 번역에 줄바꿈이 있으면 그대로 지킨다
        cur = ""
        for w in para.split():
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) <= box_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


class TextOverflow(RuntimeError):
    """영문이 원래 자리에 들어가지 않는다. 넘치게 그리지 않고 그 패널을 뺀다."""


def _fit(draw, text, box_w, box_h, bold, line_h0=None, single_line=False):
    """상자에 맞는 가장 큰 글자. 먼저 번역의 줄 수 그대로(추가 줄바꿈 없이) 맞추고,
    원래 글자 높이의 55% 아래로 내려가야 하면 그때 줄바꿈을 허용한다.

    1084687 패널0 제목이 'Custom care in the ratio you / choose, / matched…' 로
    한 단어만 따로 떨어진 줄이 생겼다. 줄 수를 지키는 쪽을 먼저 본다.
    """
    from PIL import ImageFont  # noqa: PLC0415

    paras = text.count("\n") + 1
    start = max(11, int(min(box_h / paras, (line_h0 or box_h)) * 0.86))
    floor = max(11, int(start * 0.55))
    if single_line:
        # 원문이 한 줄(배지·띠 위 글씨)이면 줄을 늘리지 않고 글자만 줄인다. 줄을 늘리면
        # 배지 밖으로 넘친다 (2026-10-17 1084687 패널1 '#BrighteningCare ...' 가 두 줄로
        # 꺾여 주황 배지 아래 베이지 배경에 걸쳤다). 11px 에서도 안 들어가면 None.
        for size in range(start, 10, -1):
            font = ImageFont.truetype(font_path(bold), size)
            if draw.textlength(text, font=font) <= box_w * 1.01:
                return font, [text], int(size * 1.22)
        return None
    for allow_wrap in (False, True):
        size = start
        while size >= (floor if not allow_wrap else 11):
            font = ImageFont.truetype(font_path(bold), size)
            lines = _wrap(draw, text, font, box_w)
            line_h = int(size * 1.22)
            if ((allow_wrap or len(lines) == paras) and len(lines) * line_h <= box_h * 1.12
                    and all(draw.textlength(l, font=font) <= box_w * 1.01 for l in lines)):
                return font, lines, line_h
            size -= 1
    font = ImageFont.truetype(font_path(bold), 11)
    return font, _wrap(draw, text, font, box_w), 13


def _free_span(arr, y0, y1, x, step, limit, bg):
    """x 에서 step 방향으로 bg 와 같은 색이 이어지는 끝. 글이 다른 요소를 덮지 않게 한다.

    1084687 패널2 왼쪽 문단을 오른쪽 여백까지 넓혔더니 보라색 '미백 캡슐' 라벨 밑으로
    파고들었다. 넓히기 전에 그 방향 열이 배경색뿐인지 본다.
    """
    import numpy as np  # noqa: PLC0415

    h, w = arr.shape[:2]
    end = x
    while 0 <= end + step < w and abs(end + step - x) <= limit:
        col = arr[max(0, y0):min(h, y1), end + step].astype(np.int16)
        if np.abs(col - bg).max(axis=1).max() > 36:
            break
        end += step
    return end


def composite(panel_rgb, units: list[dict], english: dict[int, str]):
    """한글 글자 픽셀만 지우고(Telea inpaint, 비생성형) 같은 자리에 영문을 그린다.

    배경색은 줄 상자 안에서 가장 흔한 색(16단계 양자화 최빈값)으로 본다. 상자 테두리
    중앙값을 썼더니 주황 알약 배지(#미백케어…) 에서 바깥 흰 배경을 배경으로 잡아
    배지 자체를 글자로 지웠다.
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from PIL import Image, ImageDraw  # noqa: PLC0415

    arr = np.array(panel_rgb)
    h, w = arr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    style = {}
    # 번역이 "" 인 단위는 한글이 아니라고 본 것(로고·포장 인쇄·잡음)이라 건드리지 않는다.
    # "[remove]" 는 지우기만 한다 (한국 제도 표현 등).
    units = [u for u in units if (english.get(u["id"]) or "").strip()]
    for u in units:
        colors, bgs = [], []
        for ln in u["lines"]:
            x0, y0, x1, y1 = ln["box"]
            x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
            region = arr[y0:y1, x0:x1].astype(np.int16)
            q = (region // 16).reshape(-1, 3)
            vals, counts = np.unique(q, axis=0, return_counts=True)
            mode = vals[counts.argmax()]
            bg = np.median(region.reshape(-1, 3)[(q == mode).all(axis=1)], axis=0)
            bgs.append(bg)
            diff = np.abs(region - bg).max(axis=2)
            sub = np.where(diff > 40, 255, 0).astype(np.uint8)
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], sub)
            strong = region[diff > 90]
            if len(strong) > 8:
                colors.append(np.median(strong, axis=0))
        bg = np.median(np.array(bgs), axis=0)
        color = (tuple(int(c) for c in np.median(np.array(colors), axis=0)) if colors else
                 ((25, 25, 25) if bg.mean() > 128 else (250, 250, 250)))
        style[u["id"]] = {"bg": bg, "color": color}
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    clean = cv2.inpaint(arr, mask, 3, cv2.INPAINT_TELEA)
    img = Image.fromarray(clean)
    draw = ImageDraw.Draw(img)
    for u in units:
        text = (english.get(u["id"]) or "").strip()
        if not text or text == REMOVE:
            continue
        x0, y0, x1, y1 = u["box"]
        bg = style[u["id"]]["bg"]
        line_h0 = int(np.median([l["box"][3] - l["box"][1] for l in u["lines"]]))
        centered = u["align"] == "center" or (u["align"] == "auto" and abs((x0 + x1) / 2 - w / 2) < w * 0.08)
        # 넓힐 수 있는 만큼만 넓힌다 (배경이 이어지는 데까지, 최대 가로의 25%)
        left = _free_span(clean, y0, y1, x0, -1, int(w * 0.25), bg) + 6
        right = _free_span(clean, y0, y1, x1, +1, int(w * 0.25), bg) - 6
        if centered:
            grow = max(0, min(x0 - left, right - x1))
            x0, x1 = x0 - grow, x1 + grow
        else:
            x1 = max(x1, right)
        x0, x1 = max(0, x0), min(w, x1)
        bw, bh = x1 - x0, y1 - y0
        single = len(u["lines"]) == 1 and "\n" not in text
        fit = _fit(draw, text, bw, bh, bold=line_h0 >= 26, line_h0=line_h0, single_line=single)
        if fit is None:
            raise TextOverflow(f"unit {u['id']}")
        font, lines, lh = fit
        top = y0 + max(0, (bh - lh * len(lines)) // 2)
        for i, line in enumerate(lines):
            tw = draw.textlength(line, font=font)
            x = x0 + (bw - tw) / 2 if centered else x0
            draw.text((x, top + i * lh), line, font=font, fill=style[u["id"]]["color"])
    return img


# ---------------------------------------------------------------- 6) 정보 패널

def info_panel(pd_no: str, title: str, width: int = 850):
    """영문 제품 정보 패널. 확인된 값만 쓴다. 한글·자리표시 문구가 든 칸은 뺀다."""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    try:
        row = (json.loads(LABELS.read_text(encoding="utf-8")) or {}).get(str(pd_no)) or {}
    except (OSError, json.JSONDecodeError):
        row = {}

    def ok(v):
        v = str(v or "").strip()
        return v if v and not HANGUL.search(v) and "URL" not in v else ""

    fields = [("Product", title), ("Net contents", ok(row.get("net_contents"))),
              ("Ingredients", ok(row.get("ingredients_inci"))),
              ("Country of origin", ok(row.get("country_of_origin")))]
    fields = [(k, v) for k, v in fields if v]
    if not any(k == "Ingredients" for k, _ in fields):
        return None, "ingredients_inci_unavailable"
    head = ImageFont.truetype(font_path(True), 34)
    lab = ImageFont.truetype(font_path(True), 20)
    body = ImageFont.truetype(font_path(False), 20)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    blocks, y = [], 120
    for k, v in fields:
        words, lines, cur = v.split(), [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if probe.textlength(t, font=body) <= width - 120 or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        blocks.append((k, lines, y))
        y += 34 + len(lines) * 28 + 22
    img = Image.new("RGB", (width, y + 70), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((60, 50), "Product Information", font=head, fill=(25, 25, 25))
    for k, lines, top in blocks:
        d.text((60, top), k, font=lab, fill=(90, 90, 90))
        for i, ln in enumerate(lines):
            d.text((60, top + 32 + i * 28), ln, font=body, fill=(30, 30, 30))
    d.text((60, y + 20), "From supplier materials. See the package for complete details.", font=body, fill=(110, 110, 110))
    return img, None


# ---------------------------------------------------------------- 7) 상품 하나

def slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return "-".join(s.split("-")[:4]) or fallback


def localize_product(pd_no: str, title: str, out_dir: Path, translator=None,
                     sources: list[tuple[str, bytes]] | None = None) -> dict:
    """상품 하나를 처리하고 매니페스트를 돌려준다. 실패해도 예외 대신 사유를 남긴다."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    out_dir.mkdir(parents=True, exist_ok=True)
    man = {"schema_version": 1, "product_id": str(pd_no), "title_en": title, "generated_at": now(),
           "method": METHOD, "reference_example": "data/manual/image_localization/1084687.json",
           "translator": getattr(translator, "name", None), "sources": [], "panels": [],
           "outputs": [], "status": "failed", "reasons": [],
           # status describes conversion only, never evidence-backed gallery completion.
           "gallery_status": "review_required", "gallery_complete": False,
           "gallery_review_reasons": ["role_rights_and_label_evidence_review_required"]}
    try:
        if sources is None:
            urls = rendered_detail_image_urls(str(pd_no))
            sources = [(u, download(u)) for u in urls]
    except Exception as exc:  # noqa: BLE001
        man["reasons"].append(f"detail_images_unavailable:{type(exc).__name__}")
        return man
    if not sources:
        man["reasons"].append("no_description_images")
        return man
    try:
        ensure_ocr_ready()
    except Exception as exc:  # noqa: BLE001  OCR 없이 '한글 없음' 으로 통과시키지 않는다
        man["reasons"].append(f"ocr_unavailable:{exc}")
        return man
    if translator is None:
        man["reasons"].append("translator_unavailable")
    banned, safe = claim_rules()
    try:
        import daiso_images as di  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        di = None
    n = 0
    for src_url, data in sources:
        man["sources"].append({"url": src_url, "sha256": sha(data), "bytes": len(data)})
        full = Image.open(io.BytesIO(data)).convert("RGB")
        cuts = panel_cuts(np.asarray(full.convert("L"), dtype=np.float32))
        for a, b in zip(cuts, cuts[1:]):
            panel = full.crop((0, a, full.width, b))
            buf = io.BytesIO()
            panel.save(buf, "PNG")
            png = buf.getvalue()
            row = {"source_sha256": sha(data), "y": [a, b], "panel_sha256": sha(png), "status": "excluded"}
            man["panels"].append(row)
            try:
                if di is None or di.count_faces(png) > 0:
                    row["reason"] = "human_face" if di is not None else "face_detector_unavailable"
                    continue
                boxes = hangul_boxes(png)
            except Exception as exc:  # noqa: BLE001
                row["reason"] = f"inspection_failed:{exc}"
                row["inspection_incomplete"] = True
                continue
            joined = "".join(x["ocr"] for x in boxes).replace(" ", "")
            if "상품정보" in joined or "제공고시" in joined:
                row["reason"] = "gosi_table_replaced_by_info_panel"
                continue
            # 한국 식약처 심사·보고 내용은 미국 판매 이미지에 옮길 수 없다 (us_claim_rules "한국 제도 표현").
            # 1084687 수작업도 이 패널("닥터씨피유의 기본 원칙")은 쓰지 않았다.
            if any(k in joined for k in REGULATORY_MARKERS):
                row["reason"] = "korean_regulatory_panel"
                continue
            row["korean_boxes"] = len(boxes)
            english: dict[int, str] = {}
            if boxes:
                if translator is None:
                    row["reason"] = "translator_unavailable"
                    continue
                try:
                    english = translator.translate(png, boxes, title, row["panel_sha256"])
                except Exception as exc:  # noqa: BLE001
                    row["reason"] = f"translation_failed:{type(exc).__name__}"
                    continue
                missing = [x["id"] for x in boxes if x["id"] not in english]
                if missing:
                    row["reason"] = f"translation_incomplete:{missing}"
                    continue
                hits = []
                for k, v in list(english.items()):
                    english[k], h = guard_claims(v, banned, safe)
                    hits += h
                if hits:
                    row["reason"] = f"claim_terms:{sorted(set(hits))}"
                    continue
                try:
                    out = composite(panel, boxes, english)
                except TextOverflow as exc:
                    row["reason"] = f"text_overflow:{exc}"
                    continue
            else:
                out = panel
            buf = io.BytesIO()
            out.save(buf, "JPEG", quality=92)
            jpg = buf.getvalue()
            not_korean = [x["box"] for x in boxes if not (english.get(x["id"]) or "").strip()]
            done = [x["box"] for x in boxes if (english.get(x["id"]) or "").strip()]
            try:
                left = residual_hangul(jpg, not_korean, done)
            except Exception as exc:  # noqa: BLE001  failed inspection is not no Korean
                row["reason"] = f"residual_inspection_failed:{exc}"
                row["inspection_incomplete"] = True
                continue
            if left:
                row["reason"] = "korean_text_remaining"
                row["residual"] = left[:5]
                continue
            n += 1
            # 맨 위 단위가 그 패널의 제목이다 (수작업 파일명 01-glutathione-main, 07-how-to-use 처럼).
            shown = [english[k] for k in sorted(english) if english[k] and english[k] != REMOVE]
            head = (shown[0] if shown else "").replace("\n", " ")
            name = f"{n:02d}-{slug(head, 'product')}-en.jpg"
            (out_dir / name).write_bytes(jpg)
            alt = f"{title} — {head}" if head else title
            row.update(status="used", file=name)
            man["outputs"].append({"file": name, "sha256": sha(jpg), "bytes": len(jpg),
                                   "width": out.width, "height": out.height, "alt": alt[:500],
                                   "english": {str(k): v for k, v in english.items()}})
    info, why = info_panel(str(pd_no), title)
    if info is not None:
        n += 1
        buf = io.BytesIO()
        info.save(buf, "JPEG", quality=92)
        jpg = buf.getvalue()
        name = f"{n:02d}-product-information-en.jpg"
        (out_dir / name).write_bytes(jpg)
        man["outputs"].append({"file": name, "sha256": sha(jpg), "bytes": len(jpg), "width": info.width,
                               "height": info.height, "alt": f"{title} — product information"})
    else:
        man["reasons"].append(f"info_panel_skipped:{why}")
    used = sum(1 for p in man["panels"] if p["status"] == "used")
    incomplete = any(p.get("inspection_incomplete") for p in man["panels"])
    man["status"] = "ok" if used and not incomplete else "failed"
    if incomplete:
        man["reasons"].append("ocr_inspection_incomplete")
        man["gallery_review_reasons"].append("ocr_inspection_incomplete")
    if not used:
        man["reasons"].append("no_localized_panels")
    man["summary"] = {"panels": len(man["panels"]), "used": used,
                      "excluded": {r: sum(1 for p in man["panels"] if p.get("reason", "").split(":")[0] == r)
                                   for r in sorted({p.get("reason", "").split(":")[0]
                                                    for p in man["panels"] if p["status"] != "used"})}}
    return man


def write_manifest(man: dict) -> Path:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    p = MANIFEST_DIR / f"{man['product_id']}.json"
    p.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pd_no")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", default="out/localized")
    ap.add_argument("--translations")
    ap.add_argument("--source-file", help="이미 받은 상세 이미지 파일 (URL 은 --source-url)")
    ap.add_argument("--source-url", default="")
    ap.add_argument("--no-manifest", action="store_true")
    a = ap.parse_args(argv)
    sources = None
    if a.source_file:
        sources = [(a.source_url or Path(a.source_file).name, Path(a.source_file).read_bytes())]
    man = localize_product(a.pd_no, a.title or a.pd_no, Path(a.out) / a.pd_no,
                           translator_from_env(a.translations), sources)
    if not a.no_manifest:
        print("manifest", write_manifest(man).relative_to(ROOT))
    print(json.dumps({"status": man["status"], "summary": man.get("summary"), "reasons": man["reasons"],
                      "outputs": [o["file"] for o in man["outputs"]]}, ensure_ascii=False, indent=1))
    return 0 if man["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

