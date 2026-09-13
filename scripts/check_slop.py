#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""생성된 글이 틀만 바꿔 끼운 글인지 잰다.

왜 만들었나 (2026-09-13)

  Taste Labs 영상을 검토하다 나왔다. 웹사이트 200만 개를 분석해서
  'AI 슬롭' 을 정량화한다는 내용인데, 슬롭의 세 가지 특징 중 첫째가
  반복성이다. 그건 의견이 아니라 기계로 잴 수 있다.

  재봤더니 그때 JARVIS 리스팅 카피 7건은 슬롭이 아니었다.

    문서 쌍 21개 평균 겹침   0.3%
    통째로 같은 문장          0개
    문서별 어휘 다양성        44~57%

  그런데 틀 자국은 이미 보였다.

    "ml discover the"            4/7 문서
    "your daily skincare routine" 3/7 문서
    "ml shop the"                 3/7 문서

  7건이라 티가 안 났을 뿐이다. Pinterest 는 알고리즘 노출을 유지하려면
  주 10핀이 최소선이고 Threads 는 하루 5~10회를 권한다. 그 양이 되면
  저 틀이 글의 주된 질감이 된다. 그래서 양이 늘기 전에 자를 둔다.

무엇을 재나

  겹침      문서끼리 4낱말 묶음이 얼마나 겹치는지 (Jaccard)
  중복문장  25자 넘는 문장이 두 문서 이상에 똑같이 나오는지
  틀자국    3낱말 묶음이 문서 절반 이상에 나오는지
  다양성    문서 안에서 서로 다른 낱말의 비율

기준값에 대해

  아래 숫자는 문서 7건을 한 번 재서 정한 잠정값이다. 근거가 얇다.
  그래서 FAIL 선은 넉넉하게 두고, 실제 값을 늘 같이 찍는다.
  Pinterest 핀이 쌓이면 그때 다시 재서 조인다.
  기준을 바꿀 때는 왜 바꿨는지 여기 적는다.

쓰는 법

  python scripts/check_slop.py              등록된 파일 전부 검사
  python scripts/check_slop.py --json       기계가 읽을 형태로
  preflight.py 가 배포 전에 부른다.

새 생성물을 붙일 때

  아래 SOURCES 에 한 줄 더한다. 파일이 없으면 조용히 건너뛴다.
  그래서 Pinterest·Threads 것을 미리 적어 둬도 된다.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 평균 겹침이 이 값을 넘으면 틀만 바꿔 끼운 글로 본다.
FAIL_OVERLAP = 0.20
WARN_OVERLAP = 0.08

# 같은 문장이 이만큼 많은 문서에 나오면 막는다.
FAIL_DUP_DOCS = 3
WARN_DUP_DOCS = 2

# 3낱말 묶음이 문서의 이 비율 이상에 나오면 틀 자국으로 센다.
SEAM_RATIO = 0.5
WARN_SEAMS = 12

# 문서가 이보다 적으면 재지 않는다. 둘 셋으로는 겹침이 의미가 없다.
MIN_DOCS = 3


# 검사 대상. 파일이 없으면 건너뛴다.
# 아직 안 만든 것도 미리 적어 둔다. 만들어지는 순간 검사가 켜진다.
SOURCES = [
    {
        "label": "Shopify 리스팅 카피",
        "path": "data/shopify_listing_copy.json",
        "array": "items",
        "nest": "copy",
        "fields": ["title", "description_html", "seo_title",
                   "seo_description"],
    },
    {
        "label": "Pinterest 핀",
        "path": "data/marketing/pinterest_pins.json",
        "array": "items",
        "nest": None,
        "fields": ["title", "description", "alt"],
    },
    {
        "label": "Threads 게시글",
        "path": "data/marketing/threads_posts.json",
        "array": "items",
        "nest": None,
        "fields": ["text"],
    },
    {
        "label": "Shopify 스토어 문구",
        "path": "data/shopify_store_copy.json",
        "array": "items",
        "nest": None,
        "fields": ["title", "body", "description"],
    },
]


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (s or "").lower())


def ngrams(ws: list[str], n: int) -> set[tuple]:
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "")


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def collect(spec: dict) -> list[dict]:
    """한 파일에서 검사할 글 묶음을 뽑는다."""
    payload = load(ROOT / spec["path"])
    if not isinstance(payload, dict):
        return []

    rows = payload.get(spec["array"]) or []
    if isinstance(rows, dict):
        rows = list(rows.values())

    docs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        body = row.get(spec["nest"]) if spec["nest"] else row
        if not isinstance(body, dict):
            continue
        text = strip_html(
            " ".join(str(body.get(f) or "") for f in spec["fields"])
        ).strip()
        if len(text) < 40:
            continue
        docs.append({
            "id": str(row.get("pd_no") or row.get("id") or len(docs)),
            "name": str(body.get("title") or body.get("text") or "")[:50],
            "text": text,
            "w": words(text),
        })
    return docs


def measure(docs: list[dict]) -> dict:
    pairs = []
    for a, b in combinations(docs, 2):
        pairs.append((jaccard(ngrams(a["w"], 4), ngrams(b["w"], 4)), a, b))
    pairs.sort(reverse=True, key=lambda x: x[0])

    avg = sum(p[0] for p in pairs) / len(pairs) if pairs else 0.0
    worst = pairs[0] if pairs else None

    sent = Counter()
    for d in docs:
        for s in re.split(r"(?<=[.!?])\s+", d["text"]):
            s = s.strip()
            if len(s) > 25:
                sent[s] += 1
    dups = sorted(((n, s) for s, n in sent.items() if n > 1), reverse=True)

    need = max(2, int(len(docs) * SEAM_RATIO))
    tri = Counter()
    for d in docs:
        for g in ngrams(d["w"], 3):
            tri[g] += 1
    seams = sorted(((n, " ".join(g)) for g, n in tri.items() if n >= need),
                   reverse=True)

    diversity = [
        (len(set(d["w"])) / max(1, len(d["w"])), d["name"]) for d in docs
    ]
    diversity.sort()

    return {
        "docs": len(docs),
        "avg_overlap": avg,
        "worst_overlap": worst[0] if worst else 0.0,
        "worst_pair": ([worst[1]["name"], worst[2]["name"]] if worst else []),
        "dup_sentences": [{"docs": n, "text": s[:120]} for n, s in dups[:8]],
        "max_dup_docs": dups[0][0] if dups else 0,
        "seams": [{"docs": n, "phrase": p} for n, p in seams[:12]],
        "seam_count": len(seams),
        "min_diversity": diversity[0][0] if diversity else 1.0,
    }


def judge(m: dict) -> tuple[list[str], list[str]]:
    fails, warns = [], []

    if m["avg_overlap"] >= FAIL_OVERLAP:
        fails.append(
            f"문서끼리 평균 {m['avg_overlap'] * 100:.1f}% 겹친다 "
            f"(기준 {FAIL_OVERLAP * 100:.0f}%). 틀만 바꿔 끼운 글이다"
        )
    elif m["avg_overlap"] >= WARN_OVERLAP:
        warns.append(
            f"문서끼리 평균 {m['avg_overlap'] * 100:.1f}% 겹친다 "
            f"(주의선 {WARN_OVERLAP * 100:.0f}%)"
        )

    if m["max_dup_docs"] >= FAIL_DUP_DOCS:
        fails.append(
            f"같은 문장이 문서 {m['max_dup_docs']}개에 똑같이 들어 있다"
        )
    elif m["max_dup_docs"] >= WARN_DUP_DOCS:
        warns.append(
            f"같은 문장이 문서 {m['max_dup_docs']}개에 들어 있다"
        )

    if m["seam_count"] >= WARN_SEAMS:
        warns.append(
            f"문서 절반 이상에 나오는 표현이 {m['seam_count']}개다. "
            "틀 자국이 굳어지고 있다"
        )

    return fails, warns


def run() -> tuple[int, list[dict]]:
    results = []
    worst_rc = 0

    for spec in SOURCES:
        path = ROOT / spec["path"]
        if not path.exists():
            results.append({"label": spec["label"], "path": spec["path"],
                            "status": "아직 없음"})
            continue

        docs = collect(spec)
        if len(docs) < MIN_DOCS:
            results.append({"label": spec["label"], "path": spec["path"],
                            "status": f"글 {len(docs)}건 — {MIN_DOCS}건부터 잰다"})
            continue

        m = measure(docs)
        fails, warns = judge(m)
        results.append({
            "label": spec["label"], "path": spec["path"],
            "status": "FAIL" if fails else ("WARN" if warns else "OK"),
            "metrics": m, "fails": fails, "warns": warns,
        })
        if fails:
            worst_rc = 1
        elif warns and worst_rc == 0:
            worst_rc = 2

    return worst_rc, results


def main() -> int:
    rc, results = run()

    if "--json" in sys.argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return rc

    for r in results:
        print(f"\n── {r['label']}  ({r['path']})")
        if "metrics" not in r:
            print(f"   {r['status']}")
            continue
        m = r["metrics"]
        print(f"   글 {m['docs']}건 · 평균 겹침 {m['avg_overlap'] * 100:.1f}%"
              f" · 최대 겹침 {m['worst_overlap'] * 100:.1f}%"
              f" · 틀 자국 {m['seam_count']}개")
        if m["worst_pair"]:
            print(f"   가장 닮은 둘: {m['worst_pair'][0][:34]} / "
                  f"{m['worst_pair'][1][:34]}")
        for s in m["seams"][:5]:
            print(f"     틀 {s['docs']}/{m['docs']}문서  \"{s['phrase']}\"")
        for d in m["dup_sentences"][:3]:
            print(f"     중복 {d['docs']}문서  {d['text'][:70]}")
        for f in r["fails"]:
            print(f"   FAIL {f}")
        for w in r["warns"]:
            print(f"   WARN {w}")
        if not r["fails"] and not r["warns"]:
            print("   OK")

    print(f"\n종료코드 {rc}  (0 통과 · 1 실패 · 2 경고)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
