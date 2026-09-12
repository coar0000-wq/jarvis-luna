#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 고시 항목과 상세 이미지를 수집한다.

수정본 (2026-09-12)
- data/gosi.json 만 사용
- 공무원 고시 데이터와 충돌 방지
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

FIELD = {"1": "volume", "5": "maker", "6": "origin", "7": "ingredients", "9": "warnings"}

# 이 파일은 data/gosi.json 전용입니다.
# exam_gosi.json 을 절대 읽거나 쓰지 않습니다.

def post(path: str, pd_no: str):
    body = json.dumps({"pdNo": str(pd_no)}).encode()
    req = urllib.request.Request(API + path, data=body, method="POST", headers={
        "User-Agent": "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.daisomall.co.kr",
        "Referer": f"https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={pd_no}"
    })
    try:
        return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8","replace"))
    except Exception:
        return None

def clean(v:str)->str:
    return re.sub(r"\\s+"," ",H.unescape(re.sub(r"<[^>]+>"," ",str(v or "")))).strip()

def full_size(url:str)->str:
    return re.sub(r"/dims/.*$","",url)

GOSI_LABEL=[("volume",("내용물의 용량 또는 중량","내용물의 용량","내용량","용량","중량")),("ingredients",("기재·표시하여야 하는 모든 성분","기재·표시 하여야하는 모든 성분","모든 성분","전성분")),("maker",("화장품제조업자","화장품책임판매업자","제조업자","책임판매업자","제조판매업자")),("origin",("제조국","원산지")),("expiry",("사용기한 또는 개봉 후 사용기간","제조번호 및 사용기간","사용기한","개봉 후 사용기간")),("warnings",("사용할 때의 주의사항","사용할때의 주의사항","주의사항")),("functional",("기능성 화장품","심사필")),("usage",("사용방법",))]
ALT_MIN=200
ALT_RE=re.compile(r'<img[^>]*\\salt="([^\"]{%d,})"'%ALT_MIN,re.I)
PAGE_URL="https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"

def alt_texts(html):
    return [H.unescape(a) for a in ALT_RE.findall(html or "")]

def to_lines(alt):
    return [re.sub(r"\\s+"," ",x).strip() for x in alt.split("\\n") if x.strip()]

def gosi_from_alt(alt):
    out={}; lines=to_lines(alt)
    labels=[x for _,ls in GOSI_LABEL for x in ls]
    for key,ls in GOSI_LABEL:
        for i,ln in enumerate(lines):
            hit=next((x for x in ls if x in ln),None)
            if not hit: continue
            val=ln.split(hit,1)[1].lstrip(" :·-").strip()
            if not val and i+1<len(lines):
                nxt=lines[i+1]
                if not any(x in nxt for x in labels): val=nxt
            val=re.sub(r"\\s+"," ",val).strip()
            if val and val not in PLACEHOLDER: out[key]=val[:600]
            break
    return out

def page_gosi(pd_no):
    try:
        req=urllib.request.Request(PAGE_URL.format(pd_no),headers={"User-Agent":"JarvisLunaResearchBot/1.0"})
        html=urllib.request.urlopen(req,timeout=TIMEOUT).read().decode("utf-8","replace")
    except Exception as e:
        return {},type(e).__name__
    found={}
    for alt in alt_texts(html):
        for k,v in gosi_from_alt(alt).items(): found.setdefault(k,v)
    return found,""

def main():
    doc=json.loads(GOSI.read_text(encoding="utf-8-sig"))
    items=doc.get("items") or {}
    IMGDIR.mkdir(parents=True,exist_ok=True)
    if isinstance(items,list):
        items={str(x.get("product_id")):x for x in items if isinstance(x,dict) and x.get("product_id")}
        doc["items"]=items
    for pd_no,row in items.items():
        n=post("/pd/pdr/pdDtl/selPdDtlNtfc",pd_no)
        if n and n.get("success"):
            for x in n.get("data",[]):
                m=re.match(r"\\s*(\\d+)\\.",str(x.get("ntfcIemNm") or "")); val=clean(x.get("ntfcIemCn"))
                if m and val not in PLACEHOLDER:
                    key=FIELD.get(m.group(1))
                    if key and not str(row.get(key) or "").strip(): row[key]=val
        time.sleep(DELAY)
        alt,_=page_gosi(pd_no)
        for k,v in alt.items():
            if v and not str(row.get(k) or "").strip():
                row[k]=v
                row.setdefault("자동_출처",{})[k]="상품 페이지 img alt (고시 표)"
        row["captured_at"]=datetime.now(timezone.utc).isoformat()
    doc["last_auto_run"]=datetime.now(timezone.utc).isoformat()
    GOSI.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print("DAISO gosi updated")
if __name__=="__main__":
    raise SystemExit(main())
