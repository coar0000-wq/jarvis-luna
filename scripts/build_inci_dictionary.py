#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""대한화장품협회 성분사전 표준화명칭목록으로 INCI 사전을 만든다.

왜 만들었나 (2026-09-16)

  S등급 9건 중 5건이 us_label 에서 막혀 있었다. 빠진 칸은 전부
  ingredients_inci 하나였다. 한국 고시는 다 찼는데 영문 INCI 표기가
  없어서 미국 라벨을 못 만드는 상태였다.

  사전은 180개였고, 21개 상품의 전성분을 옮기려면 191종이 더 필요했다.
  사람이 하나씩 채우는 구조라 신상품이 들어올 때마다 같은 자리에서
  다시 막힌다. 실제로 그렇게 막혀 있었다.

  data/inci_dictionary.json 의 '주의' 항목은 이렇게 적혀 있다.

    "INCI 는 국제 표준 표기다. 지어내면 안 된다. 모르면 비워 두고
     못_옮긴_성분 에 남긴다. 틀린 성분표는 미국에서 라벨 위반이다."

  맞는 원칙이다. 그래서 지어내는 대신 정본을 가져온다.

정본

  대한화장품협회 성분사전(kcia.or.kr/cid) 이 한글 성분명과 INCI 영문명을
  표준화해 고시한다. 국내 제조사가 전성분 표시에 쓰는 그 표다.
  사이트에 '표준화명칭목록 다운로드' 가 있고 PDF 로 전체를 준다.

    https://kcia.or.kr/cid/files/표준화명칭목록
    2026-08-31 기준 · 1,575쪽 · 21,876항목

  표 형식은 이렇다.
    성분코드 | 표준 성분명 | 표준 영문명 | 구명칭 | 구영문명

  구명칭도 같이 싣는다. 제품 라벨이 옛 표기를 쓰는 경우가 많다.

  robots.txt 는 없다(404). 사람이 받는 그 파일을 같은 주소로 받는다.

파싱에서 걸린 것

  한글 이름이 쪽 너비를 넘으면 줄이 갈린다. 이어 붙일 때 공백을 넣으면
  이름이 깨진다.

    '소듐아크릴레이트/...타우레이트코폴' + '리머'
      공백을 넣으면  -> '...코폴 리머'   (사전에서 못 찾는다)
      붙여 쓰면      -> '...코폴리머'    (찾는다)

  앞줄이 한글로 끝나고 뒷줄이 한글로 시작하면 공백 없이 붙인다.

  영문명이 없는 항목이 1,192개 있다(가공소금, 조직배양삼 등).
  INCI 표기가 없는 것이라 옮길 값이 없다. 버린다.

손으로 넣은 것은 지우지 않는다

  기존 사전에는 원문 오타를 표준명으로 잇는 항목이 있다.
  2026-09-13 '소듐폴리아크릴로알다이메틸타우레이트'(정상은 '아크릴로일')
  가 그랬다. 그런 것은 정본에 없으므로 그대로 둔다.

  정본과 값이 다른 손입력 항목은 정본을 따르고 '정본과_달랐던_항목' 에
  남긴다. 사람이 보고 판단한다.

쓰는 법
  pip install pypdf
  python -u scripts/build_inci_dictionary.py
  DICT_PDF=로컬경로.pdf   이미 받아둔 파일을 쓰려면
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "inci_dictionary.json"
CACHE = ROOT / "data" / "daiso_real" / "kcia_std_names.pdf"

# 주소 끝이 한글이다. urllib 은 비ASCII 경로를 그대로 못 보낸다.
#
# 2026-09-16 첫 CI 실행이 여기서 죽었다.
#   UnicodeEncodeError: 'ascii' codec can't encode characters in position 15-21
# 브라우저 fetch 는 알아서 인코딩해 준다. urllib 은 안 해준다.
# 경로만 퍼센트 인코딩해서 보낸다.
SOURCE_PATH = "표준화명칭목록"
SOURCE_URL = "https://kcia.or.kr/cid/files/" + SOURCE_PATH
SOURCE_URL_ENCODED = "https://kcia.or.kr/cid/files/" + quote(SOURCE_PATH)
SOURCE_NAME = "대한화장품협회 성분사전 · 표준화명칭목록"
TIMEOUT = 180

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

HAN = re.compile(r"[가-힣]")
DROP_LINES = ("성분코드 표준 성분명", "기준", "성분사전 표준화명칭목록")

# 사전 본문이 아닌 설명 항목. 다시 쓸 때 그대로 살린다.
KEEP_KEYS = ("왜", "쓰는 곳", "늘리는 법", "주의", "오타_표기",
             "안_넣은_것", "안_넣은_이유")


def fetch_pdf() -> bytes:
    local = os.environ.get("DICT_PDF", "").strip()
    if local and Path(local).exists():
        print(f"로컬 PDF 사용: {local}")
        return Path(local).read_bytes()

    req = urllib.request.Request(SOURCE_URL_ENCODED, headers={"User-Agent": UA})
    print(f"내려받는다: {SOURCE_URL}")
    body = urllib.request.urlopen(req, timeout=TIMEOUT).read()
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"PDF 가 아니다 (앞 8바이트 {body[:8]!r})")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(body)
    print(f"  {len(body):,} 바이트")
    return body


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("::error::pypdf 가 없다.  pip install pypdf")
        raise

    import io
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception:                                      # noqa: BLE001
            pages.append("")
        if i and i % 400 == 0:
            print(f"  {i}/{len(reader.pages)} 쪽")
    print(f"  {len(reader.pages)} 쪽 읽었다")
    return "\n".join(pages)


def parse(text: str) -> tuple[dict, dict, int]:
    lines = [l.strip() for l in text.split("\n")
             if l.strip() and not any(d in l for d in DROP_LINES)]

    entries: list[list] = []
    for line in lines:
        m = re.match(r"^(\d+)\s+(.*)$", line)
        if m:
            entries.append([int(m.group(1)), m.group(2)])
        elif entries:
            prev = entries[-1][1]
            # 한글 단어가 쪽 너비에서 잘린 경우엔 공백 없이 붙인다.
            if prev and HAN.match(prev[-1]) and HAN.match(line[0]):
                entries[-1][1] = prev + line
            else:
                entries[-1][1] = prev + " " + line

    def groups_of(s: str) -> list[tuple[bool, str]]:
        """토큰을 한글 덩이와 영문 덩이로 가른다."""
        out: list[tuple[bool, str]] = []
        cur: list[str] = []
        cur_ko: bool | None = None
        for tok in s.split():
            ko = bool(HAN.search(tok))
            if cur_ko is None or ko == cur_ko:
                cur.append(tok)
                cur_ko = ko
            else:
                out.append((cur_ko, " ".join(cur)))
                cur, cur_ko = [tok], ko
        if cur:
            out.append((bool(cur_ko), " ".join(cur)))
        return out

    std: dict[str, str] = {}
    old: dict[str, str] = {}
    no_english = 0
    for _code, body in entries:
        g = groups_of(body)
        # [한글명, 영문명, (구명칭), (구영문명)] 이 아니면 쓰지 않는다
        if len(g) < 2 or not g[0][0] or g[1][0]:
            no_english += 1
            continue
        ko, en = g[0][1].strip(), g[1][1].strip()
        if not (ko and en):
            no_english += 1
            continue
        std.setdefault(ko, en)
        if len(g) >= 3 and g[2][0]:
            for alias in re.split(r"[|]", g[2][1]):
                alias = alias.strip()
                if alias and alias not in std:
                    old.setdefault(alias, en)
    return std, old, no_english


def main() -> int:
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        prev = {}
    hand = dict(prev.get("kr_to_inci") or {})

    try:
        data = fetch_pdf()
        text = pdf_text(data)
        std, old, no_en = parse(text)
    except Exception as exc:                                   # noqa: BLE001
        print(f"::error::정본을 못 받았다: {type(exc).__name__}: {exc}")
        print("기존 사전을 그대로 둔다. 덮어써서 잃는 것이 없게 한다.")
        return 1

    if len(std) < 10000:
        print(f"::error::표준명이 {len(std)}개뿐이다. 파싱이 깨진 것으로 본다.")
        print("기존 사전을 그대로 둔다.")
        return 1

    # 정본 -> 구명칭 -> 손입력 순으로 쌓는다. 앞이 이긴다.
    merged: dict[str, str] = {}
    merged.update(std)
    for k, v in old.items():
        merged.setdefault(k, v)

    conflicts = {}
    hand_only = 0
    for k, v in hand.items():
        if k not in merged:
            merged[k] = v            # 오타 표기 등. 정본에 없으니 살린다.
            hand_only += 1
        elif merged[k] != v:
            conflicts[k] = {"정본": merged[k], "기존_손입력": v}

    doc = {
        "생성": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generator": "scripts/build_inci_dictionary.py",
        "정본": SOURCE_NAME,
        "정본_주소": SOURCE_URL,
        "정본_기준일": "PDF 표지 기준일 (내려받은 파일에 적혀 있다)",
        "만드는_법": (
            "표준화명칭목록 PDF 를 받아 '표준 성분명 -> 표준 영문명' 을 옮긴다. "
            "구명칭도 같은 영문명으로 잇는다. 라벨이 옛 표기를 쓰는 일이 많다. "
            "영문명이 없는 항목은 옮길 값이 없어 넣지 않는다."
        ),
        "count": len(merged),
        "표준명_수": len(std),
        "구명칭_수": len(old),
        "손입력_유지": hand_only,
        "영문명_없어_제외": no_en,
    }
    for k in KEEP_KEYS:
        if k in prev:
            doc[k] = prev[k]
    doc["주의"] = (
        "INCI 는 국제 표준 표기다. 지어내면 안 된다. 이 사전은 대한화장품협회 "
        "표준화명칭목록을 그대로 옮긴 것이고, 거기 없는 것은 넣지 않는다. "
        "틀린 성분표는 미국에서 라벨 위반이다."
    )
    if conflicts:
        doc["정본과_달랐던_항목"] = conflicts
        doc["정본과_달랐던_항목_설명"] = (
            "손으로 넣어 두었던 값이 정본과 달랐다. 정본을 따랐다. "
            "사람이 보고 정본이 맞는지 판단한다."
        )
    doc["kr_to_inci"] = dict(sorted(merged.items()))

    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print("\n" + "=" * 46)
    print(f"표준명 {len(std):,} · 구명칭 {len(old):,} · 손입력 유지 {hand_only}")
    print(f"영문명 없어 제외 {no_en:,}")
    if conflicts:
        print(f"정본과 달랐던 손입력 {len(conflicts)}건 (정본을 따랐다)")
        for k, v in list(conflicts.items())[:5]:
            print(f"  {k}: 정본 {v['정본']} / 기존 {v['기존_손입력']}")
    print(f"사전 {len(merged):,}개 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("::error::INCI 사전 생성기가 예상 못한 예외로 멈췄다.",
              file=sys.stderr)
        sys.exit(1)
