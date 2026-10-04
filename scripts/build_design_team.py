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
import gzip, html, json, re, time, urllib.request, urllib.error
import xml.etree.ElementTree as ET
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



def observation_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_attempt(url, error="", code=None, http_status=None, parse_status=None):
    if http_status is None and error.startswith("HTTP "):
        try:
            http_status = int(error.split()[1])
        except (ValueError, IndexError):
            pass
    return {"status": "failed" if error else "ok",
            "code": code or ("http_error" if http_status and http_status != 200 else
                              "transport_error" if error else "success"),
            "attempted_at": observation_time(), "source_url": url,
            "http_status": http_status, "parse_status": parse_status or "not_attempted",
            "error": error}


def captured_rows(rows, key, url):
    # This clock is sampled only after a successful HTTP response and usable parse.
    captured = observation_time()
    for row in rows:
        row.update(captured_at=captured, observed_at=captured, collected_at=captured,
                   provenance={"source_key": key, "source_url": url,
                               "http_status": 200, "parse_status": "ok"})
    return captured


def source_result(attempt, captured=None, previous=None):
    result = {"status": attempt["status"], "last_attempt": attempt}
    for field in ("captured_at", "observed_at", "collected_at"):
        value = captured or (previous or {}).get(field)
        if value:
            result[field] = value
    if attempt["status"] != "ok":
        result["retained"] = bool(previous)
    return result


def pool_result(items, results, errors):
    successful = sum(r["status"] == "ok" for r in results.values())
    result = {"status": "ok" if successful == len(results) and successful else
              "partial" if successful else "failed", "items": items,
              "source_results": results, "errors": errors,
              "reason": "; ".join(str(e) for e in errors)}
    # A pool's clock is the oldest actual item observation, never its write time.
    clocks = [r.get("captured_at") for r in items if r.get("captured_at")]
    if clocks and len(clocks) == len(items):
        captured = min(clocks)
        result.update(captured_at=captured, observed_at=captured, collected_at=captured)
    return result


def previous_payload(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

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
    with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(url, response.status, "unexpected HTTP status", response.headers, None)
        raw = response.read(3_000_000)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def collect_references(previous=None, source_results=None):
    previous = previous or {}
    source_results = source_results if source_results is not None else {}
    items, fails = [], []
    for name, url in FEEDS:
        try:
            text = fetch(url)
            ET.fromstring(text)
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
                raise ValueError("no usable reference items")
            captured = captured_rows(rows, name, url)
            source_results[name] = source_result(source_attempt(url, http_status=200, parse_status="ok"), captured)
            items += rows
            print(f"  RSS {name:24s} {len(rows):3d}건")
        except Exception as exc:
            is_parse = isinstance(exc, (ValueError, ET.ParseError))
            attempt = source_attempt(url, f"{type(exc).__name__}: {exc}"[:110],
                                     "parse_error" if is_parse else "http_error" if isinstance(exc, urllib.error.HTTPError) else "transport_error",
                                     200 if is_parse else getattr(exc, "code", None),
                                     "failed" if is_parse else "not_attempted")
            fails.append({"feed": name, "url": url, "reason": attempt["error"], "last_attempt": attempt})
            source_results[name] = source_result(attempt, previous=(previous.get("source_results") or {}).get(name))
            items.extend(dict(r) for r in previous.get("items", []) if r.get("feed") == name)
            print(f"  RSS {name:24s} 실패 {type(exc).__name__}")
        time.sleep(DELAY)
    return items, fails


# ── 스토어 없이 할 수 있는 단계 (2026-09-28) ───────────────────────────
# 디자인팀은 17회차 동안 '스토어에서 진행 후 기록 필요' 로 멈춰 있었다.
# 그런데 색·글꼴은 brand_kit.json 에 이미 있고, SEO 문구는 리스팅 카피에
# 이미 있다. 확인하는 사람이 없었을 뿐이다. 여기서는 스토어 없이 검증할 수
# 있는 것만 '초안 완료' 로 올린다. 스토어에 적용한 것은 아니므로 '완료' 와 구분한다.
PACK = DATA / "design" / "offline_pack.json"
SEO_TITLE_MAX, SEO_DESC_MIN, SEO_DESC_MAX = 60, 70, 160

# 레퍼런스가 스토어 디자인에 쓸모 있는지 판단하는 낱말. 추측이 아니라 포함 여부로만 본다.
RELEVANCE_TERMS = (
    "shopify", "theme", "storefront", "e-commerce", "ecommerce", "checkout", "cart",
    "product page", "conversion", "typograph", "font", "color", "colour", "layout",
    "css", "accessib", "a11y", "ux", "ui ", "design system", "image", "performance",
    "web vitals", "seo", "mobile", "responsive", "navigation", "beauty", "liquid",
)
DESIGN_POLICY = DATA / "self_improve" / "design_policy.json"


def relevance(item: dict) -> int:
    blob = f" {item.get('title', '')} {item.get('summary', '')} ".lower()
    return sum(1 for t in RELEVANCE_TERMS if t in blob)


def apply_design_policy(refs: list[dict]) -> tuple[list[dict], dict]:
    """self_improve.py 가 채택한 피드별 상한만 적용한다. 관련 높은 것부터 남긴다."""
    for r in refs:
        r["relevance"] = relevance(r)
    try:
        policy = json.loads(DESIGN_POLICY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        policy = {}
    caps = (policy.get("feed_caps") or {}) if policy.get("enabled") else {}
    if not caps:
        return refs, {"applied": False}
    kept, dropped = [], 0
    by_feed: dict[str, list] = {}
    for r in refs:
        by_feed.setdefault(r["feed"], []).append(r)
    for feed, rows in by_feed.items():
        cap = caps.get(feed)
        if cap is None:
            kept += rows
            continue
        rows = sorted(rows, key=lambda x: -x["relevance"])
        kept += rows[:cap]
        dropped += max(0, len(rows) - cap)
    return kept, {"applied": True, "feed_caps": caps, "dropped": dropped,
                  "policy_version": policy.get("version")}


def reference_stats(refs: list[dict]) -> dict:
    per: dict[str, dict] = {}
    for r in refs:
        s = per.setdefault(r["feed"], {"items": 0, "relevant": 0})
        s["items"] += 1
        s["relevant"] += 1 if r.get("relevance", 0) > 0 else 0
    total = sum(s["items"] for s in per.values())
    rel = sum(s["relevant"] for s in per.values())
    return {"items": total, "relevant": rel,
            "relevant_ratio": round(rel / total, 3) if total else None,
            "per_feed": per}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def build_offline_pack() -> dict:
    brand = load(DATA / "brand_kit.json", {})
    recs = load(DATA / "daiso_real" / "shopify_s_recommendations.json", {}).get("recommendations") or []
    copies = load(DATA / "shopify_listing_copy.json", {}).get("items") or []

    colors, fonts = brand.get("colors") or {}, brand.get("fonts") or {}
    ds_ok = colors.get("status") == "ok" and fonts.get("status") == "ok"
    design_system = {
        "status": "초안 완료" if ds_ok else "대기",
        "source": "data/brand_kit.json",
        "colors": {k: v.get("hex") for k, v in colors.items() if isinstance(v, dict) and v.get("hex")},
        "fonts": {k: (v.get("후보") or [None])[0] for k, v in fonts.items() if isinstance(v, dict)},
        "spacing_px": [4, 8, 12, 16, 24, 32, 48, 64],
        "note": "간격은 4px 배수 규칙. 로고는 만들지 않는다 (brand_kit 의 만들지_않는_것).",
    }

    buckets: dict[str, list] = {}
    for r in sorted(recs, key=lambda x: x.get("rank") or 99):
        buckets.setdefault(r.get("bucket") or "기타", []).append(r.get("pd_no"))
    image_spec = brand.get("image_spec") or {}
    sections = {
        "status": "초안 완료" if recs else "대기",
        "source": "S등급 추천 + brand_kit.image_spec",
        "home": [
            {"section": "hero", "image": image_spec.get("히어로 배너", {}).get("권장"),
             "content": "브랜드 한 줄 + 대표 컬렉션 버튼"},
            *[{"section": "featured-collection", "collection": b, "products": ids[:4]}
              for b, ids in buckets.items()],
            {"section": "shipping-notice", "content": "한국 발송·예상 소요일·관세 부담 (배송 정책 확정 후)"},
        ],
        "product_page": ["gallery (정사각 " + str(image_spec.get("상품 이미지", {}).get("권장")) + ")",
                         "title·price", "description", "ingredients (INCI)·US label",
                         "shipping·duties", "related products"],
    }

    audit, passed, eligible = [], 0, 0
    for c in copies:
        cp = c.get("copy") or {}
        if not cp:
            continue
        eligible += 1
        t, d = cp.get("seo_title") or "", cp.get("seo_description") or ""
        issues = []
        if not t or len(t) > SEO_TITLE_MAX:
            issues.append(f"seo_title {len(t)}자 (최대 {SEO_TITLE_MAX})")
        if not (SEO_DESC_MIN <= len(d) <= SEO_DESC_MAX):
            issues.append(f"seo_description {len(d)}자 ({SEO_DESC_MIN}~{SEO_DESC_MAX})")
        passed += 0 if issues else 1
        audit.append({"pd_no": c.get("pd_no"), "ok": not issues, "issues": issues})
    seo = {
        "status": "초안 완료" if eligible and passed == eligible else ("보완 필요" if eligible else "대기"),
        "source": "data/shopify_listing_copy.json",
        "rule": f"seo_title ≤{SEO_TITLE_MAX}자, seo_description {SEO_DESC_MIN}~{SEO_DESC_MAX}자",
        "passed": passed, "eligible": eligible, "items": audit,
    }
    with_image = sum(1 for r in recs if r.get("image_url"))
    assets = {
        "status": "대기",
        "source": "S등급 추천 image_url",
        "original_images": with_image,
        "processed_square_white": 0,
        "note": "원본 이미지는 있으나 흰 배경 정사각 가공은 아직 없다. 가공본이 생기면 완료로 올린다.",
    }
    return {"generated_at": now(), "generator": "scripts/build_design_team.py",
            "scope": "스토어 없이 만들고 검증할 수 있는 디자인 준비물. 스토어에 적용된 것은 아니다.",
            "design_system": design_system, "sections": sections, "seo": seo, "assets": assets}


OFFLINE_STEPS = {"design-system": "design_system", "sections": "sections", "seo": "seo", "assets": "assets"}


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


def build_steps(pack: dict | None = None):
    steps, done = [], 0
    pack = pack or {}
    for s in STEPS:
        status, evidence = "확인 불가", ""
        part = pack.get(OFFLINE_STEPS.get(s["id"], ""), {}) if not s["check"] else {}
        if part:
            status = part.get("status", "대기")
            if s["id"] == "seo":
                evidence = f'data/design/offline_pack.json seo {part.get("passed")}/{part.get("eligible")} 통과'
            elif s["id"] == "assets":
                evidence = f'원본 이미지 {part.get("original_images")}건 · 정사각 가공 {part.get("processed_square_white")}건'
            else:
                evidence = f'data/design/offline_pack.json · 근거 {part.get("source")}'
        elif s["check"]:
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
    source_results = {}
    previous = previous_payload(OUT).get("references") or {}
    refs, fails = collect_references(previous, source_results)
    refs, policy_info = apply_design_policy(refs)
    pack = build_offline_pack()
    PACK.parent.mkdir(parents=True, exist_ok=True)
    PACK.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    steps, done = build_steps(pack)
    drafts = sum(1 for s in steps if s["status"] == "초안 완료")
    waiting = [s for s in steps if s["status"] not in ("완료", "초안 완료")]
    payload = {
        "team": "디자인팀",
        "generated_at": now(),
        "scope": "Shopify 스토어 디자인 사양 관리 + 디자인 레퍼런스 수집",
        "checklist": {
            "total": len(steps),
            "done": done,
            "draft_done": drafts,
            "waiting": len(waiting),
            "steps": steps,
            "note": "각 단계 상태는 저장소 산출물 실재 여부로 판정한다. 근거 없이 완료로 적지 않는다.",
        },
        "reference_videos": VIDEOS,
        "references": {
            **{k: v for k, v in pool_result(refs, source_results, fails).items() if k != "items"},
            "count": len(refs),
            "feeds": len(FEEDS),
            "failures": fails,
            "quality": reference_stats(refs),
            "policy": policy_info,
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
