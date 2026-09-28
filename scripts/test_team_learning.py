#!/usr/bin/env python3
"""팀 YouTube 학습·NotebookLM 병합·팀 배정 회귀 테스트. 네트워크 없음, numpy 불필요."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ingest_notebook_review as ing  # noqa: E402
import team_router_moe as router  # noqa: E402
import team_routing  # noqa: E402

# 1) 사람이 지정한 새 팀 이름을 받아들인다
assert team_routing.route("x", "graph") == ["graph"]
assert team_routing.route("x", ["institutions", "robotics"]) == ["institutions", "robotics"]
assert team_routing.route("Atlas humanoid robots") == ["robotics"]
assert "channels" in team_routing.route("Amazon FBA fee changes for sellers")

# 2) 모델 파일이 없으면 MoE 는 조용히 빠지고 예전처럼 knowledge 로 둔다
router.MODEL = Path(tempfile.gettempdir()) / "no_such_team_router.npz"
router._CACHE = None
assert router.predict(["anything"]) == []
assert team_routing.route("zzqq unmatched words") == ["knowledge"]

# 3) NotebookLM 검토 병합: 지어낸 영상·형식 오류·과장 수치·중복은 버린다
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    ing.TARGET = tmp / "team.json"
    ing.SHOPIFY = tmp / "shop.json"
    ing.LEDGER = tmp / "ledger.json"
    ing.QUEUE = tmp / "queue.json"
    ing.QUEUE.write_text(json.dumps({"videos": [
        {"video_id": "AAAAAAAAAAA", "title": "FDA cosmetics", "url": "u1", "review_for": "legal"},
        {"video_id": "BBBBBBBBBBB", "title": "Robots", "url": "u2", "review_for": "robotics"}]}), encoding="utf-8")
    ing.SHOPIFY.write_text(json.dumps({"insights": [{"action": "광고 훅과 피부 고민마다 별도 랜딩페이지를 만들고 가치제안을 배치한다"}]}),
                           encoding="utf-8")
    good = {"pillar": "compliance", "tactic": "MoCRA 제품 리스팅 준비", "action": "미국 판매 전 책임자·시설 등록 여부를 체크리스트로 확인한다",
            "evidence": {"video_id": "AAAAAAAAAAA", "timestamp": "03:10-04:05", "summary": "등록 절차 설명"},
            "prerequisites": ["원문 확인"], "kpis": ["checklist_done"], "teams": ["legal"],
            "applicability": "미국 출시 전", "confidence": "high"}
    review = {"reviewed_at": "2026-10-05", "notebook_url": "https://notebook.google.com/notebook/x",
              "videos": [{"video_id": "AAAAAAAAAAA", "verdict": "adopted"}, {"video_id": "BBBBBBBBBBB", "verdict": "no_actionable"},
                         {"video_id": "ZZZZZZZZZZZ", "verdict": "adopted"}],
              "insights": [
                  good,
                  {**good, "evidence": {**good["evidence"], "video_id": "ZZZZZZZZZZZ"}},        # 큐에 없는 영상
                  {**good, "tactic": "t2", "evidence": {**good["evidence"], "timestamp": "약 3분"}},  # 타임스탬프
                  {**good, "tactic": "t3", "action": "이 방법으로 매출이 10배 늘었다고 하니 그대로 따라 한다"},  # 과장
                  {**good, "tactic": "t4", "teams": ["accounting"]},                              # 팀 이름
                  {**good, "tactic": "t5", "action": "광고 훅과 피부 고민마다 별도 랜딩페이지를 만들고 가치제안을 배치한다"},  # 중복
              ],
              "rejected_claims": ["ROAS 8배"]}
    path = tmp / "2026-10-05.json"
    path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    out = ing.ingest(path)
    assert out["adopted"] == 1 and out["rejected"] == 5, out
    assert sorted(out["reasons"]) == sorted(["근거 영상이 이번 검토 큐에 없음", "타임스탬프 형식 오류",
                                             "영상 제작자의 매출·전환 배수 주장", "팀 이름 오류", "기존 항목과 같은 내용"]), out
    saved = json.loads(ing.TARGET.read_text(encoding="utf-8"))
    assert saved["insights"][0]["id"] == "LEG-20261005-01"
    assert saved["videos"][0]["video_id"] == "AAAAAAAAAAA"
    ledger = json.loads(ing.LEDGER.read_text(encoding="utf-8"))
    assert {r["video_id"] for r in ledger["videos"]} == {"AAAAAAAAAAA", "BBBBBBBBBBB"}  # 큐 밖 영상은 기록 안 함
    # 같은 파일을 다시 넣어도 늘지 않는다
    again = ing.ingest(path)
    assert again["adopted"] == 0 and again["total_team_insights"] == 1

print("TEAM_LEARNING_OK")
