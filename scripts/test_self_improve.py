#!/usr/bin/env python3
"""자기개선 루프 회귀 테스트. 네트워크·외부 API 호출 없음."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import expand_obsidian_graph as g  # noqa: E402
import build_design_team as design  # noqa: E402
import self_improve as si  # noqa: E402

# 1) 짧은 키워드가 다른 낱말 안에서 걸리지 않는다
g._LEARNED = []
fragrance = {"title": "Vanilla fragrance body mist", "text": "flawless average draws"}
assert "LLM·언어모델" not in g.topic_names(fragrance), g.topic_names(fragrance)
assert "법률·규제" not in g.topic_names(fragrance)
assert "인프라·클라우드" not in g.topic_names(fragrance)
assert "LLM·언어모델" in g.topic_names({"title": "RAG pipelines for LLM agents", "text": ""})

# 2) 학습 키워드는 낱말 경계로만 붙는다
g._LEARNED = [("뷰티·스킨케어", __import__("re").compile(r"(?<![\w가-힣])(?:spf)(?![\w가-힣])"))]
assert "뷰티·스킨케어" in g.topic_names({"title": "Kids SPF 30 lotion", "text": ""})
assert "뷰티·스킨케어" not in g.topic_names({"title": "spfx framework release", "text": ""})
g._LEARNED = None

# 3) 소싱 정책: 목표를 채운 버킷은 받기 전에 빠지고, 빈 버킷이 앞선다
spec = importlib.util.spec_from_file_location("cd", ROOT / "scripts" / "daiso" / "collect_daiso.py")
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cd.SOURCING_POLICY = tmp / "policy.json"
    cd.QUEUE = tmp / "queue.json"
    cd.QUEUE.write_text(json.dumps({"items": [
        {"pdNo": "1", "예상버킷": "메이크업"}, {"pdNo": "2", "예상버킷": ""},
        {"pdNo": "3", "예상버킷": "클렌징"}]}, ensure_ascii=False), encoding="utf-8")
    items = [("1", "u1"), ("2", "u2"), ("3", "u3")]
    full = [{"bucket": "메이크업"}] * cd.BUCKET_TARGETS["메이크업"]
    same, info = cd.apply_sourcing_policy(items, full)
    assert same == items and info == {"applied": False}, "정책 파일이 없으면 기존 동작"
    cd.SOURCING_POLICY.write_text(json.dumps({"enabled": True, "skip_full_expected_bucket": True,
                                              "open_buckets_first": True}), encoding="utf-8")
    ordered, info = cd.apply_sourcing_policy(items, full)
    assert [x[0] for x in ordered] == ["3", "2"], ordered
    assert info["skipped_expected_full"] == 1

# 4) 디자인 정책: 관련 글은 남기고 상한 밖만 줄인다. 꺼져 있으면 그대로다
refs = [{"feed": "A", "title": f"t{i}", "summary": ""} for i in range(5)]
refs.append({"feed": "A", "title": "Shopify theme typography", "summary": ""})
with tempfile.TemporaryDirectory() as tmp:
    design.DESIGN_POLICY = Path(tmp) / "p.json"
    kept, info = design.apply_design_policy([dict(r) for r in refs])
    assert len(kept) == 6 and not info["applied"]
    design.DESIGN_POLICY.write_text(json.dumps({"enabled": True, "feed_caps": {"A": 3}}), encoding="utf-8")
    kept, info = design.apply_design_policy([dict(r) for r in refs])
    assert len(kept) == 3 and kept[0]["title"] == "Shopify theme typography", kept
    assert info["dropped"] == 3

# 5) 디자인 루프: 관련 비율이 3회 연속 낮을 때만 상한을 둔다
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    si.DATA = tmp
    si.DESIGN_POLICY = tmp / "design_policy.json"
    board = {"generated_at": "x", "checklist": {}, "references": {"quality": {
        "per_feed": {"web.dev": {"items": 10, "relevant": 1}, "Shopify": {"items": 15, "relevant": 9}}}}}
    history: dict = {}
    for k in range(3):
        board["generated_at"] = f"run{k}"
        (tmp / "design_team.json").write_text(json.dumps(board), encoding="utf-8")
        out = si.design_loop(history, dry=False)
    assert out["feed_caps"] == {"web.dev": 3}, out
    policy = json.loads(si.DESIGN_POLICY.read_text(encoding="utf-8"))
    assert policy["enabled"] and "Shopify" not in policy["feed_caps"]
    # 관련 글이 상한에 닿으면 자동 해제
    board["generated_at"] = "run3"
    board["references"]["quality"]["per_feed"]["web.dev"] = {"items": 3, "relevant": 3}
    (tmp / "design_team.json").write_text(json.dumps(board), encoding="utf-8")
    out = si.design_loop(history, dry=False)
    assert "web.dev" not in out["feed_caps"] and out["decisions"][0]["action"] == "rollback", out

print("SELF_IMPROVE_OK")
