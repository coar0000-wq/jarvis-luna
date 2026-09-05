#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 고시 항목과 상세 이미지를 수집한다.

2026-09-05 확인한 사실
  POST fapi.daisomall.co.kr/pd/pdr/pdDtl/selPdDtlNtfc  고시 11개 항목
  POST fapi.daisomall.co.kr/pd/pdr/pdDtl/selPdDtlDesc  상세 설명 HTML

11개 중 실제 값이 들어 있는 것은 3개뿐이다.
  6. 제조국 / 10. 품질보증기준 / 11. 소비자 상담 전화번호
나머지 8개는 전부 "상세페이지 참조" 다.

용량과 전성분은 상세 이미지 안에 인쇄되어 있고 텍스트로는 어디에도 없다.
selPdDtlInfo, selPdDtlDesc, 페이지 HTML 셋 다 확인했다.
그래서 이미지를 받아 두고 사람이 보고 채우게 한다. OCR 로 지어내지 않는다.

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

        time.sleep(DELAY)
        d = post("/pd/pdr/pdDtl/selPdDtlDesc", pd_no)
        urls = []
        try:
            raw = H.unescape(((d or {}).get("data") or {}).get("pdDtlDesc", {}).get("pdDtlDc") or "")
            urls = [full_size(u) for u in re.findall(r'src="([^"]+)"', raw)]
        except Exception:
            pass
        if not urls:
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
        print(f"  {pd_no}  자동 {len(got)}항목 · 이미지 {len(saved)}장  {row.get('name','')[:26]}")
        time.sleep(DELAY)

    required = ("ingredients", "volume", "maker", "origin")
    done = sum(1 for r in items.values() if all(str(r.get(f) or "").strip() for f in required))
    doc["사람이_할_일"] = (
        "gosi_image 를 열면 제품명·용량·사용기한·기능성·제조업자·제조국·"
        "전성분이 한 표에 인쇄되어 있다. 그것을 보고 volume, ingredients, "
        "maker 를 채운다. 표를 그대로 옮겨 적고 요약하지 않는다.")
    doc["auto_filled_note"] = (
        "제조국·품질보증·상담전화는 selPdDtlNtfc 로 자동으로 찬다. "
        "용량과 전성분은 상세 이미지 안에 인쇄되어 있어 텍스트로 받을 수 없다. "
        "detail_images 를 열어 보고 사람이 채운다. OCR 로 지어내지 않는다.")
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
