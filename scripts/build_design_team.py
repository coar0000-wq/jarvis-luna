#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디자인팀 보드를 만든다.

두 가지를 담는다.
  1) 스토어 구축 체크리스트
     사용자가 지정한 Shopify 디자인 영상 4편의 실제 챕터에서 뽑은 단계다.
     제목·챕터·길이는 yt-dlp 로 받은 메타데이터이고, 임의로 만든 항목이 없다.
     각 단계의 상태는 저장소 산출물 실재 여부로 판정한다. 확인할 근거가
     없으면 "확인 불가" 로 두고 완료로 적지 않는다.
  2) 레퍼런스 수집
     robots.txt 가 허용하고 실제 호출로 항목이 나온 피드만 등록했다.
"""
from __future__ import annotations
import gzip, html, json, re, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "design_team.json"
UA = "Mozilla/5.0 (compatible; JARVIS-LUNA/1.0; +https://github.com/coar0000-wq/jarvis-luna)"
TIMEOUT, PER_FEED, DELAY = 25, 15, 0.5

# ── 참고 영상. 제목·길이·챕터는 2026-09-05 yt-dlp 조회값이다 ──────────────
VIDEOS = [
    {"id": "HsMGvW2TE64", "title": "How to Build a Full Shopify Store using AI (Claude Code)",
     "channel": "Metics Media", "minutes": 54, "uploaded": "2026-07-14", "chapters": 17},
    {"id": "vqAzmtwekmw", "title": "Designing Shopify Themes Has Changed Forever (Tutorial)",
     "channel": "Brendan Gillen", "minutes": 33, "uploaded": "2026-08-27", "chapters": 6},
    {"id": "IQDtl0Dacjo", "title": "How to Use Claude Cowork to Build and Run a Shopify Store",
     "channel": "Learn With Shopify", "minutes": 8, "uploaded": "2026-08-31", "chapters": 8},
    {"id": "d2ILKOcChx4", "title": "Shopify 웹사이트 디자인 튜토리얼 2026 - 단계별 가이드",
     "channel": "Metics Media | 한국어", "minutes": 41, "uploaded": "2025-09-01", "chapters": 0},
]

# ── 체크리스트. source 는 근거가 된 영상과 챕터 ─────────────────────────
# check 는 저장소에서 확인할 파일. None 이면 자동 판정하지 않는다.
STEPS = [
    {"id": "store-open", "label": "Shopify 스토어 개설 및 기본 설정",
     "source": "HsMGvW2TE64 1분 Create Your Shopify Store / 48분 Set Up Your Store Settings",
     "check": None},
    {"id": "toolchain", "label": "Node·Git·Shopify CLI·Claude Code 설치",
     "source": "HsMGvW2TE64 2분 Set Up Your Tools & Install Node / 7분 Install Git & the Shopify CLI",
     "check": None},
    {"id": "products", "label": "상품·컬렉션 등록",
     "source": "HsMGvW2TE64 13분 Add Your Products & Collections",
     "check": "shopify_products.json"},
    {"id": "listing-copy", "label": "영문 리스팅 카피 준비",
     "source": "IQDtl0Dacjo 4분 Create Product Launch Content",
     "check": "shopify_listing_copy.json"},
    {"id": "design-system", "label": "디자인 시스템 정의 (색·타이포·간격)",
     "source": "vqAzmtwekmw 1분 Building a Design System in Claude Design",
     "check": None},
    {"id": "theme-base", "label": "Shopify Horizon 테마를 기준으로 커스텀 테마 생성",
     "source": "vqAzmtwekmw 5분 Create a Shopify Theme in Claude Design",
     "check": None},
    {"id": "assets", "label": "레퍼런스·이미지 자산 수집 및 정리",
     "source": "HsMGvW2TE64 18분 Gather Inspiration & Organize Assets",
     "check": None},
    {"id": "sections", "label": "섹션 구성 (히어로·컬렉션·상품 상세)",
     "source": "HsMGvW2TE64 37분 Build Out the Rest of Your Sections",
     "check": None},
    {"id": "header-footer", "label": "헤더·푸터 및 마감 정리",
     "source": "HsMGvW2TE64 41분 Add Your Header, Footer & Polish",
     "check": None},
    {"id": "theme-upload", "label": "테마 업로드 후 Shopify 에디터에서 수정",
     "source": "vqAzmtwekmw 18분 How to Send a Claude Design to Shopify / HsMGvW2TE64 45분",
     "check": None},
    {"id": "seo", "label": "상품 페이지 SEO·AI 검색 최적화",
     "source": "IQDtl0Dacjo 5분 Optimize Shopify Product Pages for SEO and AI Search",
     "check": None},
    {"id": "publish", "label": "게시 및 라이브 전환",
     "source": "HsMGvW2TE64 53분 Publish & Go Live",
     "check": None},
]

# ── 레퍼런스 피드. 2026-09-05 실제 호출로 항목 수를 확인했다 ────────────
FEEDS = [
    ("Shopify Changelog", "https://changelog.shopify.com/feed"),
    ("Shopify Dev Changelog", "https://shopify.dev/changelog/feed.xml"),
    ("Shopify Engineering", "https://shopify.engineering/blog.atom"),
    ("Smashing Magazine", "https://www.smashingmagazine.com/feed/"),
    ("A List Apart", "https://alistapart.com/main/feed/"),
    ("web.dev", "https://web.dev/static/blog/feed.xml"),
]

# robots.txt 가 Disallow: / 여서 등록하지 않은 곳. 지어내지 않고 남겨 둔다.
NOT_COLLECTED = {
    "CSS-Tricks": "robots.txt 가 Disallow: / 로 전면 차단",
    "Nielsen Norman Group": "robots.txt 가 Disallow: / 로 전면 차단",
    "UX Collective": "robots.txt 가 Disallow: / 로 전면 차단",
    "Shopify Blog / Partners": "공개 RSS 주소 없음 (본문이 피드가 아닌 HTML)",
    "Baymard Institute": "RSS 404",
    "Awwwards": "HTTP 502",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S | re.I)
    return clean(m.group(1)) if m else ""


def iso_date(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return m.group(0)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        return ""


def fetch(url: str) -> str:
    raw = urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT).read(3_000_000)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def collect_references():
    items, fails = [], []
    for name, url in FEEDS:
        try:
            text = fetch(url)
            blocks = (re.findall(r"<item[\s>].*?</item>", text, re.S | re.I)
                      or re.findall(r"<entry[\s>].*?</entry>", text, re.S | re.I))
            rows = []
            for b in blocks[:PER_FEED]:
                title = tag(b, "title")
                link = tag(b, "link")
                if not link:
                    m = re.search(r'<link[^>]+href=["\']([^"\']+)', b, re.I)
                    link = m.group(1) if m else ""
                date = (tag(b, "pubDate") or tag(b, "published") or tag(b, "updated"))
                if title and link:
                    rows.append({"title": title[:300], "url": link, "date": iso_date(date),
                                 "summary": (tag(b, "description") or tag(b, "summary"))[:300],
                                 "feed": name})
            if not rows:
                fails.append({"feed": name, "url": url, "reason": "항목 0건"})
                continue
            items += rows
            print(f"  RSS {name:24s} {len(rows):3d}건")
        except Exception as exc:
            fails.append({"feed": name, "url": url, "reason": f"{type(exc).__name__}: {exc}"[:110]})
            print(f"  RSS {name:24s} 실패 {type(exc).__name__}")
        time.sleep(DELAY)
    return items, fails


def count_of(path: Path):
    """산출 파일의 항목 수. 셀 수 없으면 None."""
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(d, list):
        return len(d)
    for key in ("items", "products", "rows", "copies"):
        if isinstance(d.get(key), list):
            return len(d[key])
    return None


def build_steps():
    steps, done = [], 0
    for s in STEPS:
        status, evidence = "확인 불가", ""
        if s["check"]:
            p = DATA / s["check"]
            n = count_of(p) if p.exists() else None
            if n:
                status, evidence = "완료", f'data/{s["check"]} {n}건'
                done += 1
            elif p.exists():
                status, evidence = "대기", f'data/{s["check"]} 비어 있음'
            else:
                status, evidence = "대기", f'data/{s["check"]} 없음'
        else:
            # 저장소에서 확인할 산출물이 없는 단계는 사람이 스토어에서 해야 한다
            status, evidence = "대기", "스토어에서 진행 후 기록 필요"
        steps.append({**s, "status": status, "evidence": evidence})
    return steps, done


def main() -> int:
    refs, fails = collect_references()
    steps, done = build_steps()
    waiting = [s for s in steps if s["status"] != "완료"]
    payload = {
        "team": "디자인팀",
        "generated_at": now(),
        "scope": "Shopify 스토어 디자인 사양 관리 + 디자인 레퍼런스 수집",
        "checklist": {
            "total": len(steps),
            "done": done,
            "waiting": len(waiting),
            "steps": steps,
            "note": "각 단계 상태는 저장소 산출물 실재 여부로 판정한다. 근거 없이 완료로 적지 않는다.",
        },
        "reference_videos": VIDEOS,
        "references": {
            "count": len(refs),
            "feeds": len(FEEDS),
            "failures": fails,
            "items": refs,
        },
        "not_collected": NOT_COLLECTED,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n체크리스트 {done}/{len(steps)} 완료 · 레퍼런스 {len(refs)}건 -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
