#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사용자가 직접 만든 사이트를 브랜드 기준으로 삼는다.

왜
  브랜드 키트를 만들 때 색을 Open Color 에서 골랐다. 근거가 있는 선택이긴
  했지만 어디까지나 우리가 정한 것이다. 그런데 사용자가 이미 만들어둔
  사이트가 있으면 그게 먼저다. 브랜드는 사람이 정하는 것이고 나는 그걸
  따라야 한다.

  coarfamily-cyber.github.io/wep 을 보니 이미 갖춰져 있었다.
    브랜드명   Coar Family
    포지셔닝   K-Beauty · Seoul. Sourced in Seoul, shipped to your door.
    색 체계    CSS 변수 15개로 정리된 팔레트
    글꼴       Cormorant Garamond (제목) + SF Pro Text (본문)
    다국어     EN / JP / ZH / ES, i18n 키 26개
    PWA        manifest.json + service worker
    관리자      비밀번호 로그인, 제품 추가, 이미지 업로드

  우리가 고른 청록 #12b886 은 이제 쓸 이유가 없다.

무엇을 하나
  사이트에서 색·글꼴·제품명·문구를 뽑아 디자인팀 자산으로 남긴다.
  제품 문구는 법률팀도 본다. 미국에서 못 쓰는 표현이 있으면 지금 잡는 게
  낫다. 나중에 리스팅에 그대로 옮겨지면 그때는 늦다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST = ROOT / "data" / "manual" / "own_sites.txt"
OUT = ROOT / "data" / "own_site.json"
RULES = ROOT / "data" / "us_claim_rules.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 25
DELAY = 2.0

# 색 이름에서 역할을 읽는다. --color-apple-blue 처럼 이름이 붙어 있으면
# 그 자체가 설계 의도라서 굳이 추측할 필요가 없다.
ROLE_HINT = {
    "accent": ("blue", "orange", "violet", "teal", "gold", "rose", "signal"),
    "text": ("obsidian", "carbon", "black", "graphite", "ink"),
    "surface": ("white", "frost", "paper", "mist", "silver"),
    "muted": ("platinum", "smoke", "gray", "grey"),
}


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(900000).decode("utf-8", "replace")


def role_of(name: str) -> str:
    low = name.lower()
    for role, keys in ROLE_HINT.items():
        if any(k in low for k in keys):
            return role
    return "other"


def visible_text(html: str) -> str:
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", body)
    txt = (txt.replace("&amp;", "&").replace("&nbsp;", " ")
              .replace("&#10094;", "").replace("&#10095;", ""))
    return re.sub(r"\s+", " ", txt).strip()


def analyze(url: str, html: str) -> dict:
    def one(pat, flags=0):
        m = re.search(pat, html, flags)
        return m.group(1).strip() if m else ""

    css_vars = re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8}|[^;]{2,40});", html)
    colors = [{"var": k, "value": v.strip(), "role": role_of(k)}
              for k, v in css_vars if v.strip().startswith("#")]
    tokens = {k: v.strip() for k, v in css_vars if not v.strip().startswith("#")}

    fonts = []
    for fam in re.findall(r"fonts\.googleapis\.com/css2\?family=([^&\"']+)", html):
        fonts.append({"source": "Google Fonts", "family": fam.split(":")[0].replace("+", " ")})
    for fam in set(re.findall(r"font-family\s*:\s*([^;\}]{4,80})", html)):
        f = fam.strip().strip("'\"")
        if f.startswith("var("):
            continue
        fonts.append({"source": "CSS", "family": f[:60]})

    # 제품명과 짧은 설명. 카드 구조가 사이트마다 달라 눈에 보이는 글자에서
    # 뽑는다. 정확도보다 빠뜨리지 않는 쪽을 택했다.
    text = visible_text(html)
    langs = sorted(set(re.findall(r"data-i18n=\"([^\"]+)\"", html)))
    flags = sorted(set(re.findall(r"\b(EN|JP|ZH|ES|KO|FR|DE)\b", text)))

    return {
        "url": url,
        "title": one(r"<title[^>]*>([^<]{2,120})</title>"),
        "description": one(r'<meta[^>]+name="description"[^>]+content="([^"]{5,200})"'),
        "lang": one(r'<html[^>]+lang="([^"]+)"'),
        "colors": colors,
        "color_top": [c for c, _ in Counter(
            re.findall(r"#[0-9a-fA-F]{6}\b", html)).most_common(8)],
        "tokens": tokens,
        "fonts": fonts,
        "i18n_keys": len(langs),
        "languages": flags,
        "pwa": {"manifest": "manifest.json" in html,
                "service_worker": "serviceWorker" in html},
        "has_admin": bool(re.search(r"관리자|admin", html)),
        "visible_text": text[:2500],
        "bytes": len(html),
    }


def claim_check(text: str) -> list[dict]:
    """미국에서 못 쓰는 표현이 사이트에 이미 있는지 본다.

    지금 잡는 편이 낫다. 리스팅으로 옮겨간 뒤에 잡으면 카피를 다시 써야 한다.
    """
    rules = load(RULES) or {}
    hits = []
    low = text.lower()
    for group, terms in (rules.get("banned") or {}).items():
        for t in terms:
            if str(t).lower() in low:
                i = low.find(str(t).lower())
                hits.append({"group": group, "term": t,
                             "context": text[max(0, i - 40):i + 60].strip()})
    return hits


def main() -> int:
    if not LIST.exists():
        LIST.parent.mkdir(parents=True, exist_ok=True)
        LIST.write_text(
            "# 내가 만든 사이트. 브랜드 기준으로 삼는다.\n"
            "# 형식: URL | 메모\n"
            "#\n"
            "# https://coarfamily-cyber.github.io/wep/ | 스토어프론트 시안\n",
            encoding="utf-8")
        print(f"{LIST.relative_to(ROOT)} 를 만들었다.")
        return 0

    sites, failed = [], []
    for raw in LIST.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _, note = line.partition("|")
        url = url.strip()
        if not url.startswith("http"):
            continue
        try:
            html = fetch(url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            failed.append({"url": url, "error": f"{type(e).__name__}"})
            continue
        info = analyze(url, html)
        info["note"] = note.strip()
        info["claim_risks"] = claim_check(info["visible_text"])
        sites.append(info)
        time.sleep(DELAY)

    primary = sites[0] if sites else {}
    risks = [r for s in sites for r in s.get("claim_risks") or []]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/ingest_own_site.py",
        "왜": ("브랜드는 사람이 정하는 것이다. 사용자가 이미 만든 사이트가 있으면 "
              "우리가 고른 색보다 그게 먼저다."),
        "브랜드_기준": {
            "name": primary.get("title", ""),
            "url": primary.get("url", ""),
            "글꼴": [f["family"] for f in (primary.get("fonts") or [])],
            "색_변수": {c["var"]: c["value"] for c in (primary.get("colors") or [])},
            "언어": primary.get("languages", []),
            "pwa": primary.get("pwa", {}),
        },
        "sites": len(sites),
        "failed": failed,
        "claim_risk_count": len(risks),
        "claim_risks": risks[:20],
        "items": sites,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            json.loads(OUT.read_text(encoding="utf-8-sig"))
            break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"사이트 {len(sites)}개 · 실패 {len(failed)}")
    for s in sites:
        print(f"  {s['title']} · 색 {len(s['colors'])}개 · 글꼴 "
              f"{len(s['fonts'])}종 · 언어 {','.join(s['languages'])}")
    if risks:
        print(f"  미국 표현 주의 {len(risks)}건:")
        for r in risks[:5]:
            print(f"    [{r['group']}] '{r['term']}' — {r['context'][:60]}")
    else:
        print("  미국 금지 표현 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
