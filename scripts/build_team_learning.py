#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""팀별 YouTube 학습 보드 (2026-09-28).

모든 팀이 영상에서 배운 것을 한곳에 모은다.
  - 검증된 학습 항목 (자막 타임스탬프 근거, 과장 수치 기각)
  - 이번 주 적용 과제 (신뢰도 높은 항목 1개)
  - 팀에 들어온 영상 수와 이번 주 검토 대기 영상
대시보드 팀 카드와 팀 피드가 이 파일을 읽는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "team_learning.json"
TEAMS = ("sourcing", "institutions", "market", "listing", "pricing", "legal", "robotics",
         "design", "channels", "knowledge", "graph")
RANK = {"high": 0, "medium": 1, "low": 2}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def main() -> int:
    insights, videos = [], {}
    for f in (DATA / "manual" / "shopify_youtube_insights.json", DATA / "manual" / "team_youtube_insights.json"):
        doc = load(f, {})
        for v in doc.get("videos") or []:
            videos[v.get("video_id")] = v
        for ins in doc.get("insights") or []:
            insights.append({**ins, "_source": f.name, "_date": ins.get("reviewed_at") or str(doc.get("updated_at") or "")[:10]})
    yc = load(DATA / "youtube_channels.json", {}).get("by_team") or {}
    ym = load(DATA / "youtube_manual.json", {}).get("videos") or []
    queue = load(DATA / "youtube_review_queue.json", {})
    ledger = load(DATA / "manual" / "notebook_reviews" / "ledger.json", {})

    teams = {}
    for t in TEAMS:
        mine = sorted((i for i in insights if t in (i.get("teams") or [])),
                      key=lambda i: (RANK.get(i.get("confidence"), 3), str(i.get("id"))))
        n_videos = int(yc.get(t, 0)) + sum(1 for v in ym if t in (v.get("teams") or []))
        pending = [v for v in queue.get("videos") or [] if v.get("review_for") == t]

        def brief(i):
            ev = i.get("evidence") or {}
            vid = ev.get("video_id")
            url = (videos.get(vid) or {}).get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
            return {"id": i.get("id"), "tactic": i.get("tactic"), "action": i.get("action"),
                    "confidence": i.get("confidence"), "kpis": i.get("kpis") or [],
                    "prerequisites": i.get("prerequisites") or [],
                    "evidence": {"url": url, "timestamp": ev.get("timestamp"), "summary": ev.get("summary")}}
        status = ("학습 중" if mine else "영상 수집됨 · 자막 검토 대기" if n_videos else "영상 없음")
        teams[t] = {
            "status": status,
            "insights": len(mine),
            "this_week_action": brief(mine[0]) if mine else None,
            "items": [brief(i) for i in mine[:10]],
            "videos_available": n_videos,
            "review_pending": [{"title": v.get("title"), "url": v.get("url")} for v in pending],
            "last_review": max((i["_date"] for i in mine), default=None),
        }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_team_learning.py",
        "rule": "자막 타임스탬프 근거가 있고 과장 수치를 뺀 항목만 학습으로 센다. 영상 목록만 있는 것은 학습이 아니다.",
        "total_insights": len(insights),
        "reviewed_videos": len(videos) + len(ledger.get("videos") or []),
        "teams_learning": sum(1 for v in teams.values() if v["insights"]),
        "teams_with_videos": sum(1 for v in teams.values() if v["videos_available"]),
        "teams": teams,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"학습 항목 {len(insights)}개 · 학습 중인 팀 {payload['teams_learning']}/11 · "
          f"영상 있는 팀 {payload['teams_with_videos']}/11")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
