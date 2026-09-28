#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini Notebook(NotebookLM) 주간 자막 검토 결과를 검증해 합친다 (2026-09-28).

  python scripts/ingest_notebook_review.py data/manual/notebook_reviews/2026-10-05.json

입력 형식 (루틴이 NotebookLM 답을 옮겨 적는다)
  {
    "reviewed_at": "2026-10-05",
    "notebook_url": "https://notebook.google.com/notebook/...",
    "videos": [{"video_id": "...", "verdict": "adopted|no_actionable|unavailable", "note": "..."}],
    "insights": [{"pillar": "...", "tactic": "...", "action": "...",
                  "evidence": {"video_id": "...", "timestamp": "03:10-04:05", "summary": "..."},
                  "prerequisites": [...], "kpis": [...], "teams": ["legal"],
                  "applicability": "...", "confidence": "high|medium|low"}],
    "rejected_claims": ["..."]
  }

검증 (하나라도 어기면 그 항목은 버리고 사유를 남긴다)
  - 근거 영상이 이번 주 검토 큐에 있어야 한다 (지어낸 영상 금지)
  - 타임스탬프 형식 mm:ss 또는 mm:ss-mm:ss
  - 팀은 11개 팀 이름 중에서만
  - 실행 문장(action) 15자 이상
  - 매출·ROAS·전환 '몇 배' 같은 영상 제작자 수치는 근거로 쓰지 않는다 -> 기각
  - 기존 항목과 같은 내용이면 합치지 않는다
결과는 data/manual/team_youtube_insights.json 에 누적하고, 검토한 영상은
ledger.json 에 적어 다음 주 큐에서 빠지게 한다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TARGET = DATA / "manual" / "team_youtube_insights.json"
SHOPIFY = DATA / "manual" / "shopify_youtube_insights.json"
LEDGER = DATA / "manual" / "notebook_reviews" / "ledger.json"
QUEUE = DATA / "youtube_review_queue.json"
TEAMS = {"sourcing", "institutions", "market", "listing", "pricing", "legal", "robotics",
         "design", "channels", "knowledge", "graph"}
TS_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\s*-\s*\d{1,2}:\d{2}(:\d{2})?)?$")
HYPE_RE = re.compile(r"(\d+(\.\d+)?\s*(배|x|X)\b.*(매출|수익|전환|roas|revenue|sales))|"
                     r"((매출|수익|revenue|sales|roas).{0,20}\d+(\.\d+)?\s*(배|x|X)\b)", re.I)
PREFIX = {"sourcing": "SRC", "institutions": "INS", "market": "MKT", "listing": "LST", "pricing": "PRC",
          "legal": "LEG", "robotics": "ROB", "design": "DSN", "channels": "CHN", "knowledge": "KNW",
          "graph": "GRP"}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def norm(text: str) -> set[str]:
    return set(re.findall(r"[\w가-힣]{2,}", (text or "").lower()))


def similar(a: str, b: str) -> bool:
    x, y = norm(a), norm(b)
    return bool(x and y) and len(x & y) / len(x | y) >= 0.8


def validate(ins: dict, queue_ids: set[str]) -> str:
    ev = ins.get("evidence") or {}
    if ev.get("video_id") not in queue_ids:
        return "근거 영상이 이번 검토 큐에 없음"
    if not TS_RE.match(str(ev.get("timestamp") or "").strip()):
        return "타임스탬프 형식 오류"
    teams = ins.get("teams") or []
    if not teams or any(t not in TEAMS for t in teams):
        return "팀 이름 오류"
    if len(str(ins.get("action") or "").strip()) < 15 or not str(ins.get("tactic") or "").strip():
        return "실행 문장 부족"
    if ins.get("confidence") not in ("high", "medium", "low"):
        return "confidence 값 오류"
    if HYPE_RE.search(f"{ins.get('action', '')} {ins.get('tactic', '')}"):
        return "영상 제작자의 매출·전환 배수 주장"
    return ""


def ingest(path: Path, dry: bool = False) -> dict:
    review = load(path, None)
    if not isinstance(review, dict):
        raise SystemExit(f"검토 파일을 읽지 못했다: {path}")
    queue = load(QUEUE, {})
    queue_videos = {v["video_id"]: v for v in queue.get("videos") or []}
    queue_ids = set(queue_videos)
    target = load(TARGET, {}) or {}
    target.setdefault("schema_version", 1)
    target.setdefault("method", "Gemini Notebook(NotebookLM)으로 자막을 검토하고 타임스탬프 근거가 있는 실행 항목만 채택")
    target.setdefault("policy", "영상의 매출·전환 과장 수치는 근거로 쓰지 않는다. 제품 사실·법률 게이트·자사 측정값을 우선한다.")
    for key in ("videos", "insights", "rejected_claims", "rejected_items"):
        target.setdefault(key, [])
    existing = (load(SHOPIFY, {}).get("insights") or []) + target["insights"]
    stamp = str(review.get("reviewed_at") or datetime.now(timezone.utc).date().isoformat())
    day = stamp.replace("-", "")[:8]

    adopted, rejected = [], []
    counter: dict[str, int] = {}
    for ins in review.get("insights") or []:
        why = validate(ins, queue_ids)
        if not why and any(similar(ins.get("action", ""), e.get("action", "")) for e in existing + adopted):
            why = "기존 항목과 같은 내용"
        if why:
            rejected.append({"reason": why, "tactic": str(ins.get("tactic") or "")[:120],
                             "video_id": (ins.get("evidence") or {}).get("video_id"), "reviewed_at": stamp})
            continue
        lead = ins["teams"][0]
        counter[lead] = counter.get(lead, 0) + 1
        item = {k: ins.get(k) for k in ("pillar", "tactic", "action", "evidence", "prerequisites", "kpis",
                                         "teams", "applicability", "confidence")}
        item["id"] = f"{PREFIX[lead]}-{day}-{counter[lead]:02d}"
        item["reviewed_at"] = stamp
        item["notebook_url"] = review.get("notebook_url")
        adopted.append(item)

    known = {v.get("video_id") for v in target["videos"]}
    for vid in {i["evidence"]["video_id"] for i in adopted}:
        if vid not in known and vid in queue_videos:
            q = queue_videos[vid]
            target["videos"].append({"video_id": vid, "title": q.get("title"), "channel": q.get("channel"),
                                     "url": q.get("url"), "reviewed_at": stamp, "role": f"{q.get('review_for')} 팀 검토"})
    target["insights"].extend(adopted)
    target["rejected_claims"].extend(str(c) for c in review.get("rejected_claims") or [] if str(c).strip())
    target["rejected_items"].extend(rejected)
    target["updated_at"] = datetime.now(timezone.utc).isoformat()

    ledger = load(LEDGER, {"videos": []})
    seen = {r.get("video_id") for r in ledger["videos"]}
    for v in review.get("videos") or []:
        if v.get("video_id") in queue_ids and v.get("video_id") not in seen:
            ledger["videos"].append({"video_id": v["video_id"], "verdict": v.get("verdict"),
                                     "note": str(v.get("note") or "")[:200], "reviewed_at": stamp})
    ledger["updated_at"] = target["updated_at"]
    if not dry:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"adopted": len(adopted), "rejected": len(rejected), "reasons": [r["reason"] for r in rejected],
              "videos_logged": len(review.get("videos") or []), "total_team_insights": len(target["insights"])}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("사용법: python scripts/ingest_notebook_review.py <검토파일.json> [--dry-run]")
    ingest(Path(sys.argv[1]), dry="--dry-run" in sys.argv)
