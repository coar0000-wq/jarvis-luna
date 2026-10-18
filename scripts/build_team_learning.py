#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""팀별 YouTube 학습 보드 (2026-09-28).

모든 팀이 영상에서 배운 것을 한곳에 모은다.
  - 출처 한정 자막 검토 지시 (시각 미제공 명시, 과장 수치 기각)
  - 이번 주 적용 과제 (신뢰도 높은 항목 1개)
  - 팀에 들어온 영상 수와 이번 주 검토 대기 영상
대시보드 팀 카드와 팀 피드가 이 파일을 읽는다.
"""
from __future__ import annotations

import json
from document_handoffs import packets, write_specialist_handoff
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


def reviewed_datetime(value):
    """Parse only an item's review clock, never a capture/source freshness clock."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def insight_sort_key(ins):
    dt = reviewed_datetime(ins.get("reviewed_at"))
    age = -(dt - datetime.min.replace(tzinfo=timezone.utc)).total_seconds() if dt else float("inf")
    return (RANK.get(ins.get("confidence"), 3), age, str(ins.get("id") or ""))


def brief(ins, videos):
    ev = ins.get("evidence") or {}
    vid = ev.get("video_id")
    url = ev.get("url") or (videos.get(vid) or {}).get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
    evidence = {"url": url, "timestamp": ev.get("timestamp"), "summary": ev.get("summary")}
    for field in ("video_id", "timestamp_basis", "mapping_verified", "timestamp_status",
                  "chapter_hint", "source_type", "notebook_url"):
        if field in ev:
            evidence[field] = ev[field]
    return {"id": ins.get("id"), "tactic": ins.get("tactic"), "action": ins.get("action"),
            "confidence": ins.get("confidence"), "kpis": ins.get("kpis") or [],
            "prerequisites": ins.get("prerequisites") or [], "teams": ins.get("teams") or [],
            "reviewed_at": ins.get("reviewed_at"), "status": "shared-review-directive",
            "evidence": evidence}


def main() -> int:
    insights, videos = [], {}
    for f in (DATA / "manual" / "shopify_youtube_insights.json", DATA / "manual" / "team_youtube_insights.json"):
        doc = load(f, {})
        for v in doc.get("videos") or []:
            videos[v.get("video_id")] = v
        for ins in doc.get("insights") or []:
            insights.append({**ins, "_source": f.name})
    yc = load(DATA / "youtube_channels.json", {}).get("by_team") or {}
    ym = load(DATA / "youtube_manual.json", {}).get("videos") or []
    queue = load(DATA / "youtube_review_queue.json", {})
    ledger = load(DATA / "manual" / "notebook_reviews" / "ledger.json", {})

    teams = {}
    document_packets = packets(ROOT)
    for t in TEAMS:
        mine = sorted((i for i in insights if t in (i.get("teams") or [])),
                      key=insight_sort_key)
        n_videos = int(yc.get(t, 0)) + sum(1 for v in ym if t in (v.get("teams") or []))
        pending = [v for v in queue.get("videos") or [] if v.get("review_for") == t]

        status = ("학습 중" if mine else "영상 수집됨 · 자막 검토 대기" if n_videos else "영상 없음")
        teams[t] = {
            "document_handoffs": [p for p in document_packets if p["recipient"] == t],
            "status": status,
            "insights": len(mine),
            "this_week_action": brief(mine[0], videos) if mine else None,
            "items": [brief(i, videos) for i in mine[:10]],
            "videos_available": n_videos,
            "review_pending": [{"title": v.get("title"), "url": v.get("url")} for v in pending],
            "last_review": max((i for i in mine if reviewed_datetime(i.get("reviewed_at"))),
                               key=lambda i: reviewed_datetime(i["reviewed_at"]), default={}).get("reviewed_at"),
        }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_team_learning.py",
        "rule": "출처에 한정하고 과장 수치를 뺀 자막 검토 지시를 공유한다. 타임스탬프 미제공은 명시하며 실행·성과·사업 승인 증명이 아니다. 영상 목록만 있는 것은 학습이 아니다.",
        "total_insights": len(insights),
        "reviewed_videos": len(videos) + len(ledger.get("videos") or []),
        "teams_learning": sum(1 for v in teams.values() if v["insights"]),
        "teams_with_videos": sum(1 for v in teams.values() if v["videos_available"]),
        "teams": teams,
    }
    write_specialist_handoff(ROOT)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"학습 항목 {len(insights)}개 · 학습 중인 팀 {payload['teams_learning']}/11 · "
          f"영상 있는 팀 {payload['teams_with_videos']}/11")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
