#!/usr/bin/env python3
"""Prepare a transparent training corpus from real collected source records.

This script never fabricates samples and never claims model training occurred.
It produces JSONL suitable for a downstream trainer and a status manifest that
separates data preparation from weight updates.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "knowledge" / "real_sources.json"
OUT = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
STATUS = ROOT / "data" / "knowledge" / "training_status.json"


def load_existing() -> dict:
    """이미 쌓인 코퍼스를 URL 기준으로 읽어들인다."""
    existing: dict = {}
    if not OUT.exists():
        return existing
    for line in OUT.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = str(rec.get("url", "")).strip()
        if url:
            existing[url] = rec
    return existing


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing real source file: {SOURCE}")
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    collected_at = payload.get("collected_at")

    # 코퍼스는 누적한다. 매 실행마다 덮어쓰면 30분 주기로 수집해도
    # 레코드 수가 늘지 않는다. URL을 키로 중복만 제거한다.
    records = load_existing()
    before = len(records)
    added = 0

    for source_name, source in payload.get("sources", {}).items():
        if source.get("status") != "ok":
            continue
        for item in source.get("items", []):
            title = str(item.get("title", "")).strip()
            # collect_robotics / collect_institutions 는 본문을 "text" 로 넘긴다.
            # 이 키를 빠뜨리면 본문이 통째로 비어 주제 분류 정확도가 떨어진다.
            body = str(item.get("summary") or item.get("snippet")
                       or item.get("text") or "").strip()
            url = str(item.get("url", "")).strip()
            if not title or not url:
                continue
            prev = records.get(url)
            records[url] = {
                "source": source_name,
                "title": title,
                "text": f"{title}\n{body}".strip(),
                "url": url,
                "first_seen_at": (prev or {}).get("first_seen_at")
                                 or (prev or {}).get("collected_at") or collected_at,
                "collected_at": collected_at,
                # 기관 수집분은 소속·분야·종류를 그대로 실어 보낸다.
                # 옵시디언 그래프가 키워드 추측 없이 기관 노드를 만들 수 있다.
                "org": str(item.get("org") or ""),
                "category": str(item.get("category") or ""),
                "kind": str(item.get("kind") or ""),
                "venue": str(item.get("venue") or ""),
            }
            if prev is None:
                added += 1

    ordered = sorted(records.values(),
                     key=lambda r: (r.get("first_seen_at") or "", r.get("url") or ""))
    with OUT.open("w", encoding="utf-8") as handle:
        for record in ordered:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "real_records": len(ordered),
        "records_before": before,
        "records_added": added,
        "source_status": {name: value.get("status") for name, value in payload.get("sources", {}).items()},
        "corpus_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "note": "실제 수집 데이터 누적 코퍼스. URL 기준 중복 제거하며 기존 레코드는 보존한다. 가중치 갱신은 학습기가 별도로 수행한다.",
        "corpus": str(OUT.relative_to(ROOT)),
    }
    # 이 파일은 나 혼자 쓰는 게 아니다. train_real_knowledge.py 와
    # tune_real_knowledge_moe.py 도 같은 파일에 학습 결과를 적는다.
    #
    # 예전에는 여기서 통째로 덮어썼다. 그래서 09-09 09:06 에 튜닝이 끝나
    # training_performed=true 로 적혔는데, 10:36 에 이 스크립트가 돌면서
    # false 로 되돌렸다. 대시보드는 training_performed 와 weights_updated 를
    # 보고 학습 상태를 정하므로 화면에는 "학습 안 됨" 으로 떴다.
    # 실제로는 학습도 승격도 끝나 있었다.
    #
    # 이제 합친다. 그리고 false 로 되돌리는 것은 말뭉치가 실제로 바뀌어
    # 지금 가중치가 낡았을 때만 한다. 그때는 되돌리는 게 맞다.
    prev = {}
    if STATUS.exists():
        try:
            prev = json.loads(STATUS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            prev = {}
    if not isinstance(prev, dict):
        prev = {}

    merged = dict(prev)
    merged.update(status)
    trained_on = prev.get("trained_corpus_sha256")
    if trained_on and trained_on == status.get("corpus_sha256"):
        # 지금 가중치가 바로 이 말뭉치로 학습한 것이다. 그대로 둔다.
        for k in ("training_performed", "weights_updated"):
            merged[k] = prev.get(k, False)
        merged["말뭉치"] = "변화 없음. 기존 가중치가 이 말뭉치 기준이라 학습 상태를 유지한다."
    else:
        merged["training_performed"] = False
        merged["weights_updated"] = False
        merged["말뭉치"] = ("바뀌었다. 지금 가중치는 이 말뭉치로 학습한 것이 아니다. "
                         "학습기가 돌아야 다시 참이 된다.")

    STATUS.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(merged, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
