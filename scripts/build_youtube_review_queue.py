#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주간 YouTube 자막 검토 대상 큐 (2026-09-28).

모든 팀이 영상으로 배우게 하려면 팀마다 새 영상이 검토되어야 한다.
여기서는 아직 검토하지 않은 영상을 팀마다 골라 data/youtube_review_queue.json 에
적는다. Aside 정기 루틴이 이 큐를 Gemini Notebook(NotebookLM)에 넣어 자막을
검토하고, scripts/ingest_notebook_review.py 가 결과를 검증해 합친다.

고르는 규칙
  - 이미 검토했거나(채택·기각 모두) AI 학습 금지 표시가 있는 영상은 뺀다.
  - 팀마다 최대 PER_TEAM 편, 전체 MAX_TOTAL 편.
  - 팀은 사람이 지정한 것 > 키워드 > MoE 팀 배정기(믿을 수 있는 팀만) 순.
  - 최신(제목 옆 게시 시점) 과 조회수로 순서를 정한다.
  - 후보가 모자란 팀은 검색어를 같이 적는다. 루틴이 YouTube 에서 찾아 보탠다.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "youtube_review_queue.json"
LEDGER = DATA / "manual" / "notebook_reviews" / "ledger.json"
PER_TEAM, MAX_TOTAL = 2, 20
TEAMS = ("sourcing", "institutions", "market", "listing", "pricing", "legal", "robotics",
         "design", "channels", "knowledge", "graph")
TEAM_KO = {"sourcing": "상품 소싱", "institutions": "기관 수집", "market": "마케팅 조사",
           "listing": "리스팅 제작", "pricing": "가격 정책", "legal": "법률·규제",
           "robotics": "로보틱스", "design": "디자인", "channels": "채널 운영",
           "knowledge": "지식 수집", "graph": "옵시디언 그래프"}
# 후보가 모자랄 때 루틴이 YouTube 검색에 쓰는 말. 우리 사업(다이소 K뷰티 -> 미국 Shopify) 기준.
SEARCH = {
    "sourcing": ["다이소 화장품 추천 2026", "Daiso Korea skincare haul"],
    "pricing": ["shopify pricing strategy landed cost", "US de minimis tariff ecommerce 2026"],
    "listing": ["shopify product page conversion 2026", "product description SEO shopify"],
    "legal": ["MoCRA cosmetics compliance small brand", "FDA cosmetic labeling requirements"],
    "design": ["shopify theme design 2026 beauty store", "ecommerce UX beauty brand"],
    "market": ["k-beauty US market trend 2026", "beauty brand tiktok marketing"],
    "channels": ["amazon seller beauty category 2026", "tiktok shop seller beauty"],
    "robotics": ["humanoid robot 2026 update"],
    "institutions": ["NVIDIA keynote AI 2026"],
    "knowledge": ["AI agents research explained 2026"],
    "graph": ["obsidian knowledge graph workflow"],
}
sys.path.insert(0, str(ROOT / "scripts"))

# Gemini Notebook 에 그대로 붙여 넣는 질문. 답은 ingest_notebook_review.py 입력 형식 그대로다.
NOTEBOOK_PROMPT = """너는 JARVIS(다이소 K뷰티 상품을 미국 Shopify 에서 파는 사업)의 검토자다.
이 노트북의 영상 자막만 근거로, 각 영상이 지정된 팀({team_list})에 실제로 적용할 수 있는 실행 항목을 뽑아라.
규칙:
1) 자막에 있는 내용만. 각 항목에 영상 ID 와 타임스탬프(mm:ss-mm:ss)를 반드시 단다.
2) 영상 제작자의 매출·ROAS·전환 '몇 배' 같은 수치는 근거로 쓰지 말고 rejected_claims 에 적는다.
3) 우리 사업에 쓸 수 없는 영상은 verdict 를 no_actionable 로 두고 항목을 만들지 않는다.
4) 법률·규제·의약품 효능 주장은 만들지 않는다. 규제 내용은 원문 확인이 필요하다고 prerequisites 에 적는다.
5) 아래 JSON 하나만 답한다. 다른 문장은 쓰지 않는다.
{{"videos":[{{"video_id":"...","verdict":"adopted|no_actionable|unavailable","note":"한 줄"}}],
 "insights":[{{"pillar":"cro|content|ads|retention|pricing|compliance|design|operations|research",
   "tactic":"짧은 이름","action":"우리 팀이 할 일을 한두 문장",
   "evidence":{{"video_id":"...","timestamp":"mm:ss-mm:ss","summary":"자막 근거 요약"}},
   "prerequisites":["..."],"kpis":["..."],"teams":["팀코드"],"applicability":"어디에 쓰나",
   "confidence":"high|medium|low"}}],
 "rejected_claims":["..."]}}
팀 코드: sourcing, institutions, market, listing, pricing, legal, robotics, design, channels, knowledge, graph
영상별 담당 팀:
{video_lines}"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


def recency(text: str) -> float:
    t = (text or "").lower()
    for pat, score in ((r"(hour|minute|시간|분) ", 3.0), (r"(day|일) ", 2.5), (r"(week|주) ", 2.0),
                       (r"(month|개월|달) ", 1.0)):
        if re.search(pat, t + " "):
            return score
    return 0.0


def reviewed_ids() -> set[str]:
    ids: set[str] = set()
    for f in (DATA / "manual" / "shopify_youtube_insights.json", DATA / "manual" / "team_youtube_insights.json"):
        for v in load(f, {}).get("videos") or []:
            ids.add(v.get("video_id") or video_id(v.get("url", "")))
    for row in load(LEDGER, {}).get("videos") or []:
        ids.add(row.get("video_id"))
    ids.discard(None)
    ids.discard("")
    return ids


def candidates() -> list[dict]:
    out: dict[str, dict] = {}
    blocked = set()
    ym = load(DATA / "youtube_manual.json", {})
    for v in ym.get("videos") or []:
        vid = video_id(v.get("url", ""))
        if v.get("ai_training_allowed") is False:
            blocked.add(vid)
            continue
        if vid and v.get("title") and not v.get("error"):
            out[vid] = {"video_id": vid, "url": v.get("url"), "title": v["title"], "channel": v.get("channel"),
                        "teams": v.get("teams") or [], "team_source": v.get("team_source") or "",
                        "score": 5.0 + math.log10(1 + (v.get("views") or 0)), "origin": "사람이 넣은 링크"}
    yc = load(DATA / "youtube_channels.json", {})
    for ch in yc.get("items") or []:
        hint = bool(str(ch.get("team_hint") or "").strip())
        for v in ch.get("videos") or []:
            vid = v.get("video_id") or video_id(v.get("url", ""))
            if not vid or vid in out or vid in blocked or not v.get("title"):
                continue
            out[vid] = {"video_id": vid, "url": v.get("url") or f"https://www.youtube.com/watch?v={vid}",
                        "title": v["title"], "channel": v.get("channel") or ch.get("channel_name"),
                        "teams": v.get("teams") or [], "team_source": "사람 지정 채널" if hint else "자동 분류",
                        "score": recency(v.get("published_text")) + math.log10(1 + (v.get("views") or 0)) / 2,
                        "origin": "지정 채널"}
    return list(out.values())


def main() -> int:
    done = reviewed_ids()
    pool = [c for c in candidates() if c["video_id"] not in done]
    # 팀을 못 정해 knowledge 로 떨어진 자동 분류 영상은 MoE 팀 배정기에 다시 묻는다
    try:
        from team_router_moe import predict
        need = [c for c in pool if c["team_source"] == "자동 분류" and c["teams"] in ([], ["knowledge"])]
        for c, p in zip(need, predict([c["title"] for c in need])):
            if p.get("usable"):
                c["teams"], c["team_source"] = [p["team"]], f"MoE {p['prob']:.2f}"
    except Exception as exc:  # 모델이 없어도 큐는 만든다
        print(f"MoE 팀 배정 생략: {type(exc).__name__}")

    picked: list[dict] = []
    per_team: dict[str, list] = {t: [] for t in TEAMS}
    for c in sorted(pool, key=lambda x: -x["score"]):
        for t in c["teams"]:
            if t in per_team and len(per_team[t]) < PER_TEAM and c not in picked and len(picked) < MAX_TOTAL:
                per_team[t].append(c["video_id"])
                picked.append({**c, "review_for": t})
                break
    thin = {t: SEARCH.get(t, []) for t in TEAMS if len(per_team[t]) < PER_TEAM}
    payload = {
        "generated_at": now(),
        "generator": "scripts/build_youtube_review_queue.py",
        "purpose": "Gemini Notebook(NotebookLM) 주간 자막 검토 대상. 검토 결과는 ingest_notebook_review.py 로만 합친다.",
        "already_reviewed": len(done),
        "candidates_unreviewed": len(pool),
        "videos": [{k: c[k] for k in ("video_id", "url", "title", "channel", "teams", "team_source", "review_for", "origin")}
                   for c in picked],
        "per_team": {t: len(v) for t, v in per_team.items()},
        "thin_teams_search": thin,
        "team_names": TEAM_KO,
        "output_file": "data/manual/notebook_reviews/<YYYY-MM-DD>.json",
    }
    payload["notebook_prompt"] = NOTEBOOK_PROMPT.format(
        team_list=", ".join(sorted({c["review_for"] for c in picked})) or "없음",
        video_lines="\n".join(f'- {c["video_id"]} -> {c["review_for"]} ({c["title"][:60]})' for c in picked))
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"검토 큐 {len(picked)}편 · 팀별 {payload['per_team']} · 부족한 팀 {list(thin)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
