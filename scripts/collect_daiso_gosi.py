#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 고시 항목과 상세 이미지를 수집한다.

2026-09-05 확인한 사실
  POST fapi.daisomall.co.kr/pd/pdr/pdDtl/selPdDtlNtfc  고시 11개 항목
  POST fapi.daisomall.co.kr/pd/pdr/pdDtl/selPdDtlDesc  상세 설명 HTML

11개 중 실제 값이 들어 있는 것은 3개뿐이다.
  6. 제조국 / 10. 품질보증기준 / 11. 소비자 상담 전화번호
나머지 8개는 전부 "상세페이지 참조" 다.

2026-09-10 고쳤다. 고시 표는 img 의 alt 에 있었다.

  식물원 병풀 클리어 앰플(pdNo 1041749)로 확인했다.
    img[alt] 길이 1,077자 · src 경로 종류 = description
    제품명·용량·제조국·전성분·주의사항·품질보증·상담전화가 다 있다
    줄바꿈 60개로 나뉜 표 형태다

  09-05 에 "텍스트로는 어디에도 없다" 고 적은 것은 덜 보고 단정한 것이다.
  세 번 헤맸고 왜 그랬는지 적어 둔다.
    1) selPdDtlDesc 의 pdDtlDc 를 봤다. 309자 평문이라 아무것도 없었다.
    2) 렌더된 페이지 innerText 를 훑었다. 0건이었다.
       alt 속성은 innerText 에 안 들어간다. 그래서 안 보였다.
    3) 이미지 82장을 상세 이미지로 착각했다. /banner/ 경로였고
       DOM 부모를 따라가 보니 전부 광고 슬라이드(ad-img-box)였다.
    innerHTML 로 훑으니 그제야 나왔다. 속성 안에 있었던 것이다.

  중요한 것은 이 alt 가 상품 페이지 HTML 안에 그대로 있다는 점이다.
  collect_daiso.py 가 이미 받아오는 그 HTML 이다. 추가 요청이 아니다.
  API 를 더 뒤질 일도, 사람이 이미지를 열어 옮겨 적을 일도 아니었다.
  우리가 alt 를 한 번도 안 읽었을 뿐이다.

  그래서 순서를 이렇게 한다.
    1. 고시 API(selPdDtlNtfc) 에서 값이 있는 항목을 받는다
    2. 상품 페이지 HTML 의 긴 alt 에서 고시 표를 읽는다
    3. 그래도 빈 항목만 이미지를 남기고 사람에게 넘긴다
  못 찾은 항목은 비워 둔다. OCR 로도 추측으로도 채우지 않는다.
  어느 항목을 어디서 얻었는지 자동_출처 에 적는다.

robots.txt 는 www 기준 Crawl-delay 30 이다. fapi 는 다른 호스트지만
같은 서비스이므로 넉넉히 쉬어 간다.
"""
from __future__ import annotations
import json, re, time, urllib.request, html as H
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GOSI = DATA / "gosi.json"
IMGDIR = DATA / "daiso_real" / "gosi_img"
API = "https://fapi.daisomall.co.kr"
DELAY = 10.0
TIMEOUT = 30
PLACEHOLDER = ("상세페이지 참조", "-", "", "상세 페이지 참조")

# 고시 번호 -> gosi.json 필드
FIELD = {"1": "volume", "5": "maker", "6": "origin", "7": "ingredients", "9": "warnings"}


def post(path: str, pd_no: str) -> dict | None:
    body = json.dumps({"pdNo": str(pd_no)}).encode()
    req = urllib.request.Request(
        API + path, data=body, method="POST",
        headers={"User-Agent": "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)",
                 "Accept": "application/json", "Content-Type": "application/json",
                 "Origin": "https://www.daisomall.co.kr",
                 "Referer": f"https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={pd_no}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace"))
    except Exception:
        return None


def clean(v: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))).strip()


def full_size(url: str) -> str:
    """/dims/resize/850/... 를 떼어 원본을 받는다. 성분 글씨가 작아 원본이 필요하다."""
    return re.sub(r"/dims/.*$", "", url)


# 고시 표 alt 안에서 항목을 찾는 표지어.
# 실제 alt(1,077자)에서 확인한 위치는 이랬다.
#   제품명@15  용량@39  제조국@60  제조번호@489  주의사항@806
#   상담@898  품질보증@995
# 표지어 뒤에 같은 줄로 값이 오거나 다음 줄로 넘어간다. 둘 다 받는다.
GOSI_LABEL = [
    ("volume",      ("내용물의 용량 또는 중량", "내용물의 용량", "내용량", "용량", "중량")),
    ("ingredients", ("기재·표시하여야 하는 모든 성분", "기재·표시 하여야하는 모든 성분",
                     "모든 성분", "전성분")),
    ("maker",       ("화장품제조업자", "화장품책임판매업자", "제조업자",
                     "책임판매업자", "제조판매업자")),
    ("origin",      ("제조국", "원산지")),
    ("expiry",      ("사용기한 또는 개봉 후 사용기간", "제조번호 및 사용기간",
                     "사용기한", "개봉 후 사용기간")),
    ("warnings",    ("사용할 때의 주의사항", "사용할때의 주의사항", "주의사항")),
    ("functional",  ("기능성 화장품", "심사필")),
    ("usage",       ("사용방법",)),
]

# alt 가 이 길이를 넘으면 고시 표로 본다. 보통 alt 는 짧은 설명이라
# 이만큼 긴 것은 표를 통째로 옮겨 적은 것뿐이었다. 실측 1,077자.
ALT_MIN = 200
ALT_RE = re.compile(r'<img[^>]*\salt="([^"]{%d,})"' % ALT_MIN, re.I)
PAGE_URL = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"


def alt_texts(page_html: str) -> list[str]:
    """상품 페이지 HTML 에서 긴 alt 를 뽑는다."""
    return [H.unescape(a) for a in ALT_RE.findall(page_html or "")]


def to_lines(alt: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln).strip() for ln in alt.split("\n") if ln.strip()]


def gosi_from_alt(alt: str) -> dict:
    """고시 표 글자에서 항목을 뽑는다.

    "내용물의 용량 또는 중량 : 30ml" 처럼 표지어 뒤에 값이 오는 형태와
    표지어 다음 줄에 값이 오는 형태를 받는다.
    표지어를 못 찾으면 그 항목은 비운다. 추측해서 채우지 않는다.
    """
    out: dict[str, str] = {}
    lines = to_lines(alt)
    if not lines:
        return out
    all_labels = [x for _, ls in GOSI_LABEL for x in ls]
    for key, labels in GOSI_LABEL:
        for i, ln in enumerate(lines):
            hit = next((x for x in labels if x in ln), None)
            if not hit:
                continue
            val = ln.split(hit, 1)[1].lstrip(" :·-").strip()
            if not val and i + 1 < len(lines):
                nxt = lines[i + 1]
                if not any(x in nxt for x in all_labels):
                    val = nxt
            val = re.sub(r"\s+", " ", val).strip()
            if val and val not in PLACEHOLDER and len(val) > 1:
                out[key] = val[:600]
            break
    return out


def page_gosi(pd_no: str) -> tuple[dict, str]:
    """상품 페이지를 받아 alt 에서 고시를 읽는다. (값, 실패사유)"""
    try:
        req = urllib.request.Request(
            PAGE_URL.format(pd_no),
            headers={"User-Agent": "JarvisLunaResearchBot/1.0 "
                                   "(+contact: coar0000@naver.com)",
                     "Accept-Language": "ko-KR,ko;q=0.9"})
        html = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace")
    except Exception as exc:                                   # noqa: BLE001
        return {}, f"{type(exc).__name__}"
    found: dict = {}
    for alt in alt_texts(html):
        for k, v in gosi_from_alt(alt).items():
            found.setdefault(k, v)
    return found, ""


def main() -> int:
    doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    items = doc.get("items") or {}
    IMGDIR.mkdir(parents=True, exist_ok=True)

    filled, imgs, fails = 0, 0, []
    for pd_no, row in items.items():
        n = post("/pd/pdr/pdDtl/selPdDtlNtfc", pd_no)
        got = {}
        if n and n.get("success") and isinstance(n.get("data"), list):
            for x in n["data"]:
                m = re.match(r"\s*(\d+)\.", str(x.get("ntfcIemNm") or ""))
                val = clean(x.get("ntfcIemCn"))
                if m and val not in PLACEHOLDER:
                    key = FIELD.get(m.group(1))
                    if key:
                        got[key] = val
        else:
            fails.append({"pd_no": pd_no, "step": "selPdDtlNtfc", "reason": "응답 없음 또는 실패"})

        # 실제 값만 덮어쓴다. 사람이 채워 둔 값은 지우지 않는다.
        for k, v in got.items():
            if v and not str(row.get(k) or "").strip():
                row[k] = v
                filled += 1

        # 상품 페이지 HTML 의 긴 alt 에서 고시 표를 읽는다.
        # 고시 표는 이미지인데 그 전문이 alt 에 글자로 있다. 실측 1,077자.
        time.sleep(DELAY)
        from_alt, alt_err = page_gosi(pd_no)
        if alt_err:
            fails.append({"pd_no": pd_no, "step": "page-alt", "reason": alt_err})
        for k, v in from_alt.items():
            if v and not str(row.get(k) or "").strip():
                row[k] = v
                row.setdefault("자동_출처", {})[k] = "상품 페이지 img alt (고시 표)"
                filled += 1

        time.sleep(DELAY)
        d = post("/pd/pdr/pdDtl/selPdDtlDesc", pd_no)
        urls = []
        try:
            raw = H.unescape(((d or {}).get("data") or {}).get("pdDtlDesc", {}).get("pdDtlDc") or "")
            urls = [full_size(u) for u in re.findall(r'src="([^"]+)"', raw)]
        except Exception:
            pass

        # 필수 항목이 다 찼으면 이미지를 받을 이유가 없다. 사람도 안 부른다.
        need_now = [f for f in ("ingredients", "volume", "maker", "origin")
                    if not str(row.get(f) or "").strip()]
        if not need_now:
            urls = []
        elif not urls:
            fails.append({"pd_no": pd_no, "step": "selPdDtlDesc", "reason": "상세 이미지 없음"})
        # 고시 표는 마지막 이미지에 통째로 들어 있다. 앞의 4장만 받으면 놓친다.
        # 실제로 6장 중 6번째가 제품명·용량·사용기한·제조업자·전성분 표였다.
        saved = []
        for i, u in enumerate(urls[:12], 1):
            dst = IMGDIR / f"{pd_no}_{i:02d}.jpg"
            try:
                b = urllib.request.urlopen(urllib.request.Request(
                    u, headers={"User-Agent": "JarvisLunaResearchBot/1.0",
                                "Referer": "https://www.daisomall.co.kr/"}), timeout=TIMEOUT).read()
                if b[:2] == b"\xff\xd8" or b[:8] == b"\x89PNG\r\n\x1a\n":
                    dst.write_bytes(b)
                    saved.append(str(dst.relative_to(ROOT)).replace("\\", "/"))
                    imgs += 1
            except Exception as exc:
                fails.append({"pd_no": pd_no, "step": "image", "reason": f"{type(exc).__name__}"})
        row["detail_images"] = saved
        # 고시 표는 통상 마지막 장이다. 사람이 먼저 열어 볼 파일을 짚어 준다.
        row["gosi_image"] = saved[-1] if saved else ""
        row["captured_at"] = datetime.now(timezone.utc).isoformat()
        row["사람_필요"] = [f for f in ("ingredients", "volume", "maker", "origin")
                         if not str(row.get(f) or "").strip()]
        print(f"  {pd_no}  고시API {len(got)} · alt {len(from_alt)} · "
              f"이미지 {len(saved)}장 · 남은 항목 {len(row['사람_필요'])}  "
              f"{row.get('name','')[:24]}")
        time.sleep(DELAY)

    required = ("ingredients", "volume", "maker", "origin")
    done = sum(1 for r in items.values() if all(str(r.get(f) or "").strip() for f in required))
    doc["사람이_할_일"] = (
        "gosi_image 를 열면 제품명·용량·사용기한·기능성·제조업자·제조국·"
        "전성분이 한 표에 인쇄되어 있다. 그것을 보고 volume, ingredients, "
        "maker 를 채운다. 표를 그대로 옮겨 적고 요약하지 않는다.")
    doc["auto_filled_note"] = (
        "먼저 고시 API(selPdDtlNtfc) 에서 값이 있는 항목을 받는다. "
        "그다음 상품 페이지 HTML 의 긴 img alt 에서 고시 표를 읽는다. "
        "고시 표는 이미지인데 그 전문이 alt 에 글자로 있다. 실측 1,077자. "
        "09-05 에는 alt 를 안 읽어서 '텍스트로는 없다' 고 잘못 적어뒀다. "
        "그래도 빈 항목만 이미지를 남기고 사람에게 넘긴다. "
        "어느 항목을 어디서 얻었는지는 각 상품의 자동_출처 에 적는다. "
        "못 찾은 것은 비워 둔다. OCR 로도 추측으로도 채우지 않는다.")
    doc["auto_source"] = "POST fapi.daisomall.co.kr/pd/pdr/pdDtl/selPdDtlNtfc, selPdDtlDesc"
    doc["last_auto_run"] = datetime.now(timezone.utc).isoformat()
    doc["auto_failures"] = fails
    doc["gosi_ok_count"] = done
    GOSI.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n자동 채움 {filled}칸 · 이미지 {imgs}장 · 실패 {len(fails)}건")
    print(f"필수 4항목 완료 {done}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
