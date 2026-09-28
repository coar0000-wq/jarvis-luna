#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS 팀 자기개선 루프 (2026-09-28).

측정 -> 후보 생성 -> 그림자 평가 -> 채택/보류 -> 사후 검증·자동 롤백 -> 장부.

원칙
  - 무료. 외부 API 를 부르지 않는다. 저장소에 있는 실측 데이터만 쓴다.
  - 코드를 고치지 않는다. data/self_improve/ 아래 정책 파일만 바꾼다.
    정책을 읽는 쪽 코드는 파일이 없거나 enabled 가 아니면 예전 그대로 동작한다.
  - 상품 공개·결제·법률·고시 값은 건드리지 않는다.
  - 채택 기준을 넘지 못하면 아무것도 바꾸지 않고 이유만 적는다.
  - 채택 뒤 실측이 나빠지면 스스로 되돌린다.

루프
  topics    지식 노트 '미분류' 줄이기 (expand_obsidian_graph.py 가 읽음)
  sourcing  다이소 받기 전 걸러내기 (scripts/daiso/collect_daiso.py 가 읽음)
  design    디자인 레퍼런스 품질 (scripts/build_design_team.py 가 읽음)
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SI = DATA / "self_improve"
TOPIC_POLICY = SI / "topic_keywords.json"
SOURCING_POLICY = SI / "sourcing_policy.json"
DESIGN_POLICY = SI / "design_policy.json"
STATUS = SI / "status.json"
LEDGER = SI / "ledger.json"
HISTORY = SI / "history.json"
LEDGER_MAX, HISTORY_MAX = 500, 120

sys.path.insert(0, str(ROOT))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def save(path: Path, value, dry: bool) -> None:
    if dry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ──────────────────────────────────────────────────────────────
# 1. topics : 미분류 줄이기
# ──────────────────────────────────────────────────────────────

TOPIC_MIN_SUPPORT = 8        # 이미 분류된 노트 중 이 낱말을 가진 수
TOPIC_MIN_PRECISION = 0.85   # 그중 같은 주제로 분류된 비율
TOPIC_MIN_SOURCE_FIT = 0.20  # 새로 분류될 노트의 대표 출처에서 그 주제가 나오는 비율
TOPIC_MIN_NEW = 3            # 새로 분류되는 미분류 노트 수
TOPIC_MAX_COLLATERAL = 0.20  # 이미 분류된 노트에 새 주제가 붙는 비율 상한
TOPIC_ROLLBACK_PRECISION = 0.70
TOPIC_MAX_ADD = 15
WORD_RE = re.compile(r"(?<![\w가-힣])([a-z][a-z0-9\-]{2,24}|[가-힣]{2,12})(?![\w가-힣])")
GENERIC = {
    "what", "which", "these", "those", "however", "through", "while", "often", "each",
    "previously", "better", "best", "free", "clear", "multi", "power", "time", "study",
    "propose", "proposed", "existing", "methods", "method", "paper", "model", "models",
    "system", "systems", "data", "count", "amazon", "basics", "essentials", "new", "more",
    "most", "also", "than", "then", "such", "when", "where", "into", "over", "under",
    "pack", "size", "oz", "fl", "ml", "set", "one", "two", "all", "can", "via", "not",
    "its", "they", "them", "been", "were", "will", "may", "use", "used", "show", "shows",
    "her", "his", "him", "she", "our", "you", "your", "trend", "trends", "top", "day",
    "daily", "best-selling", "guide", "tips", "news", "how", "why", "who",
}


def _graph_module():
    import expand_obsidian_graph as g  # noqa: WPS433 (로컬 모듈)
    return g


def topic_loop(dry: bool) -> dict:
    g = _graph_module()
    rows = g.load_records()
    policy = load(TOPIC_POLICY, {"version": 0, "topics": {}})
    learned: dict[str, list[str]] = {k: list(v) for k, v in (policy.get("topics") or {}).items()}

    # 기준 분류(학습 키워드 없이)와 현재 분류(학습 키워드 포함)를 따로 잰다.
    # 학습 키워드의 정확도는 기준 분류로만 잰다. 스스로 붙인 주제로 자기를
    # 채점하면 틀려도 계속 맞다고 나온다.
    g._LEARNED = []
    base = [g.topic_names(r) for r in rows]
    g._LEARNED = None
    current = [g.topic_names(r) for r in rows]
    blobs = [(r.get("title", "") + " " + r.get("text", "")).lower() for r in rows]
    words = [set(WORD_RE.findall(b)) for b in blobs]
    n = len(rows)
    unc_now = sum(1 for t in current if t == ["미분류"])

    def stats(word: str, topic: str):
        classified = [i for i in range(n) if base[i] != ["미분류"] and word in words[i]]
        hit = sum(1 for i in classified if topic in base[i])
        return len(classified), (hit / len(classified) if classified else 0.0), len(classified) - hit

    decisions = []
    # 사후 검증: 채택했던 낱말이 지금도 정확한가
    for topic, kws in list(learned.items()):
        for w in list(kws):
            sup, prec, _ = stats(w, topic)
            if sup >= TOPIC_MIN_SUPPORT and prec < TOPIC_ROLLBACK_PRECISION:
                kws.remove(w)
                decisions.append({"loop": "topics", "action": "rollback", "keyword": w, "topic": topic,
                                  "reason": f"정확도 {prec:.2f} < {TOPIC_ROLLBACK_PRECISION} (표본 {sup})"})
        if not kws:
            learned.pop(topic)

    known = {w for kws in learned.values() for w in kws}
    unc_idx = [i for i in range(n) if current[i] == ["미분류"]]
    freq = collections.Counter(w for i in unc_idx for w in words[i])
    candidates = []
    for w, c in freq.most_common(400):
        if c < TOPIC_MIN_NEW or w in GENERIC or w in g.STOP or w in known:
            continue
        cls = [i for i in range(n) if base[i] != ["미분류"] and w in words[i]]
        if len(cls) < TOPIC_MIN_SUPPORT:
            continue
        tc = collections.Counter(t for i in cls for t in base[i])
        topic, hit = tc.most_common(1)[0]
        prec = hit / len(cls)
        collateral = (len(cls) - hit) / len(cls)
        # 출처 궁합: 새로 분류될 노트가 주로 온 출처에서 이 주제가 실제로 나오는가.
        # (예: 미국 뷰티 상품에 LLM 주제를 붙이는 일을 막는다)
        src = collections.Counter(rows[i].get("source") for i in unc_idx if w in words[i]).most_common(1)[0][0]
        src_rows = [i for i in range(n) if rows[i].get("source") == src and base[i] != ["미분류"]]
        fit = (sum(1 for i in src_rows if topic in base[i]) / len(src_rows)) if src_rows else 0.0
        if prec >= TOPIC_MIN_PRECISION and collateral <= TOPIC_MAX_COLLATERAL and fit >= TOPIC_MIN_SOURCE_FIT:
            candidates.append({"keyword": w, "topic": topic, "precision": round(prec, 3),
                               "support": len(cls), "uncategorized_hits": c,
                               "source": src, "source_fit": round(fit, 3)})

    covered: set[int] = set()
    adopted = []
    for cand in sorted(candidates, key=lambda x: (-x["uncategorized_hits"], -x["precision"])):
        if len(adopted) >= TOPIC_MAX_ADD:
            break
        gain = [i for i in unc_idx if i not in covered and cand["keyword"] in words[i]]
        if len(gain) < TOPIC_MIN_NEW:
            continue
        covered.update(gain)
        cand["newly_classified"] = len(gain)
        adopted.append(cand)

    shadow_unc = unc_now - len(covered)
    if adopted:
        for c in adopted:
            learned.setdefault(c["topic"], []).append(c["keyword"])
            decisions.append({"loop": "topics", "action": "adopt", **c})
    changed = bool(adopted) or any(d["action"] == "rollback" for d in decisions)
    if changed:
        save(TOPIC_POLICY, {
            "version": int(policy.get("version") or 0) + 1,
            "updated_at": now(),
            "generator": "scripts/self_improve.py",
            "rule": (f"미분류 노트에 {TOPIC_MIN_NEW}번 이상 나오고, 이미 분류된 노트 {TOPIC_MIN_SUPPORT}개 이상에서 "
                     f"같은 주제 비율 {TOPIC_MIN_PRECISION:.0%} 이상인 낱말만 채택. 정확도가 "
                     f"{TOPIC_ROLLBACK_PRECISION:.0%} 아래로 떨어지면 자동 해제."),
            "topics": {k: sorted(set(v)) for k, v in sorted(learned.items())},
        }, dry)
    return {
        "metric": "uncategorized_rate",
        "records": n,
        "base_uncategorized": sum(1 for t in base if t == ["미분류"]),
        "before": round(unc_now / n, 4) if n else None,
        "after_shadow": round(shadow_unc / n, 4) if n else None,
        "uncategorized_before": unc_now,
        "uncategorized_after_shadow": shadow_unc,
        "adopted": len(adopted),
        "learned_keywords": sum(len(v) for v in learned.values()),
        "decisions": decisions,
        "status": "adopted" if adopted else "no_change",
    }


# ──────────────────────────────────────────────────────────────
# 2. sourcing : 받기 전 걸러내기
# ──────────────────────────────────────────────────────────────

SOURCING_MIN_PRECISION = 0.80
SOURCING_MIN_GAIN = 1.20
SOURCING_BATCH = 110


def _daiso_module():
    path = ROOT / "scripts" / "daiso" / "collect_daiso.py"
    spec = importlib.util.spec_from_file_location("collect_daiso_si", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _expected_useful(order, expected, dist_by_pred, slots) -> float:
    mass: dict[str, float] = collections.defaultdict(float)
    for pid in order[:SOURCING_BATCH]:
        for bucket, p in dist_by_pred.get(expected.get(pid, ""), {}).items():
            mass[bucket] += p
    return sum(min(m, slots.get(b, 0)) for b, m in mass.items())


def sourcing_loop(dry: bool) -> dict:
    queue = load(DATA / "daiso_real" / "beauty_queue.json", {})
    products = load(DATA / "daiso_real" / "products.json", {})
    if isinstance(products, dict):
        products = products.get("products") or products.get("items") or []
    state = load(DATA / "daiso_real" / "crawl_state.json", {})
    status = (load(DATA / "daiso_real" / "collection_status.json", {}) or {}).get("last_run") or {}
    targets = _daiso_module().BUCKET_TARGETS
    policy = load(SOURCING_POLICY, {})
    decisions = []

    items = [x for x in queue.get("items") or [] if isinstance(x, dict) and x.get("pdNo")]
    expected = {str(x["pdNo"]): str(x.get("예상버킷") or "") for x in items}
    visited = set(state.get("visited") or [])
    kept = {str(p.get("pd_no")): p.get("bucket") for p in products if isinstance(p, dict)}

    counts = collections.Counter(b for b in kept.values() if b)
    slots = {b: max(0, t - counts.get(b, 0)) for b, t in targets.items()}
    open_slots = sum(slots.values())

    # 예측 정확도: 큐에서 받아 실제로 남은 상품의 예상버킷 vs 실제 버킷
    confusion: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for pid, actual in kept.items():
        if pid in expected and actual:
            confusion[expected[pid]][actual] += 1
    named = [(p, c) for p, c in confusion.items() if p]
    total_named = sum(sum(c.values()) for _, c in named)
    match = sum(c.get(p, 0) for p, c in named)
    precision = match / total_named if total_named else 0.0

    # 이름으로 못 가린 상품이 실제로 뷰티로 남은 비율
    none_visited = [p for p in expected if expected[p] == "" and p in visited]
    none_kept = sum(1 for p in none_visited if p in kept)
    p_none = none_kept / len(none_visited) if none_visited else 0.0
    dist_by_pred: dict[str, dict[str, float]] = {}
    for pred, c in confusion.items():
        tot = sum(c.values())
        scale = p_none if pred == "" else 1.0
        dist_by_pred[pred] = {b: scale * v / tot for b, v in c.items()}

    fresh = [str(x["pdNo"]) for x in items if str(x["pdNo"]) not in visited]
    open_b = {b for b, s in slots.items() if s > 0}
    policy_order = ([p for p in fresh if expected.get(p) in open_b]
                    + [p for p in fresh if not expected.get(p)])
    base_e = _expected_useful(fresh, expected, dist_by_pred, slots)
    cand_e = _expected_useful(policy_order, expected, dist_by_pred, slots)
    skip_n = len(fresh) - len(policy_order)

    evidence = {
        "prediction_precision": round(precision, 3),
        "prediction_samples": total_named,
        "unknown_bucket_beauty_rate": round(p_none, 3),
        "open_slots": {b: s for b, s in slots.items() if s},
        "fresh_queue": len(fresh),
        "expected_useful_baseline": round(base_e, 2),
        "expected_useful_policy": round(cand_e, 2),
        "would_skip_expected_full": skip_n,
        "batch": SOURCING_BATCH,
    }

    # 사후 검증: 정책이 적용된 실제 실행 결과를 본다
    last_policy = status.get("prefetch_policy") or {}
    if policy.get("enabled") and last_policy.get("applied") and status.get("started_at", "") > policy.get("adopted_at", "~"):
        req = int(status.get("requested") or 0)
        ok = int(status.get("ok") or 0)
        wasted = int(status.get("skipped_bucket_full") or 0) + int(status.get("skipped_not_beauty") or 0)
        rate = ok / req if req else None
        obs = policy.setdefault("observations", [])
        if not obs or obs[-1].get("started_at") != status.get("started_at"):
            obs.append({"started_at": status.get("started_at"), "requested": req, "ok": ok,
                        "wasted": wasted, "useful_rate": rate})
        base_rate = (policy.get("baseline") or {}).get("useful_rate")
        worse = [o for o in obs[-2:] if base_rate is not None and o.get("useful_rate") is not None
                 and o["useful_rate"] <= base_rate and o.get("requested")]
        if len(obs) >= 2 and len(worse) == 2:
            policy["enabled"] = False
            policy["disabled_at"] = now()
            policy["disabled_reason"] = "채택 뒤 두 번 연속 기존보다 나아지지 않았다"
            decisions.append({"loop": "sourcing", "action": "rollback", "reason": policy["disabled_reason"]})
        save(SOURCING_POLICY, policy, dry)

    if not policy.get("enabled") and not policy.get("disabled_at"):
        gain_ok = cand_e >= base_e * SOURCING_MIN_GAIN and cand_e >= base_e + 1
        if open_slots == 0:
            reason = "모든 카테고리 목표를 채웠다. 받을 칸이 없어 정책을 켤 이유가 없다."
        elif precision < SOURCING_MIN_PRECISION:
            reason = f"이름 예측 정확도 {precision:.0%} < {SOURCING_MIN_PRECISION:.0%}"
        elif not gain_ok:
            reason = f"예상 효과 {cand_e:.1f}건 vs 기존 {base_e:.1f}건. 기준(1.2배, +1건) 미달"
        else:
            reason = ""
        if reason:
            decisions.append({"loop": "sourcing", "action": "hold", "reason": reason})
        else:
            req = int(status.get("requested") or 0)
            policy = {
                "enabled": True,
                "version": int(policy.get("version") or 0) + 1,
                "adopted_at": now(),
                "generator": "scripts/self_improve.py",
                "skip_full_expected_bucket": True,
                "open_buckets_first": True,
                "why": "목표를 채운 카테고리를 받아 버리는 낭비를 받기 전에 막는다.",
                "baseline": {"started_at": status.get("started_at"), "requested": req,
                             "ok": int(status.get("ok") or 0),
                             "useful_rate": (int(status.get("ok") or 0) / req) if req else None},
                "evidence": evidence,
                "observations": [],
                "rollback_rule": "적용된 실제 실행 2회 연속 기존 적중률 이하면 자동 해제",
            }
            save(SOURCING_POLICY, policy, dry)
            decisions.append({"loop": "sourcing", "action": "adopt", **evidence})
    return {
        "metric": "useful_fetch_rate",
        "before": (int(status.get("ok") or 0) / int(status.get("requested") or 1)) if status.get("requested") else None,
        "policy_enabled": bool(policy.get("enabled")),
        "evidence": evidence,
        "decisions": decisions,
        "status": decisions[-1]["action"] if decisions else ("active" if policy.get("enabled") else "no_change"),
    }


# ──────────────────────────────────────────────────────────────
# 3. design : 레퍼런스 품질 + 스토어 없이 할 수 있는 단계
# ──────────────────────────────────────────────────────────────

DESIGN_LOW = 0.30
DESIGN_OBS = 3
DESIGN_MIN_ITEMS = 5


def design_loop(history: dict, dry: bool) -> dict:
    board = load(DATA / "design_team.json", {})
    refs = board.get("references") or {}
    quality = refs.get("quality") or {}
    per_feed = quality.get("per_feed") or {}
    checklist = board.get("checklist") or {}
    policy = load(DESIGN_POLICY, {"enabled": False, "feed_caps": {}})
    caps: dict[str, int] = dict(policy.get("feed_caps") or {})
    decisions = []

    obs = history.setdefault("design_feeds", {})
    stamp = board.get("generated_at")
    for feed, s in per_feed.items():
        rows = obs.setdefault(feed, [])
        if s.get("items") and (not rows or rows[-1].get("at") != stamp):
            rows.append({"at": stamp, "items": s["items"], "relevant": s["relevant"],
                         "capped": feed in caps})
            del rows[:-12]

    # 사후 검증: 상한을 둔 피드에서 관련 있는 글이 상한에 닿으면 상한을 푼다
    for feed in list(caps):
        s = per_feed.get(feed) or {}
        if s.get("relevant", 0) >= caps[feed]:
            decisions.append({"loop": "design", "action": "rollback", "feed": feed,
                              "reason": f"관련 글 {s.get('relevant')}건이 상한 {caps[feed]}건에 닿았다"})
            caps.pop(feed)

    for feed, rows in obs.items():
        if feed in caps:
            continue
        recent = [r for r in rows[-DESIGN_OBS:] if not r.get("capped")]
        if len(recent) < DESIGN_OBS:
            continue
        items = sum(r["items"] for r in recent)
        rel = sum(r["relevant"] for r in recent)
        ratio = rel / items if items else 1.0
        if ratio < DESIGN_LOW and recent[-1]["items"] >= DESIGN_MIN_ITEMS:
            cap = max(3, max(r["relevant"] for r in recent))
            caps[feed] = cap
            decisions.append({"loop": "design", "action": "adopt", "feed": feed, "cap": cap,
                              "reason": f"최근 {DESIGN_OBS}회 관련 비율 {ratio:.0%} < {DESIGN_LOW:.0%}. "
                                        "관련 글은 모두 남기고 나머지만 줄인다."})

    if decisions:
        save(DESIGN_POLICY, {
            "enabled": bool(caps),
            "version": int(policy.get("version") or 0) + 1,
            "updated_at": now(),
            "generator": "scripts/self_improve.py",
            "rule": (f"피드 관련 비율이 {DESIGN_OBS}회 연속 {DESIGN_LOW:.0%} 미만이면 관련 높은 순으로 "
                     "상한을 둔다. 관련 글이 상한에 닿으면 자동 해제."),
            "feed_caps": caps,
        }, dry)
    return {
        "metric": "reference_relevant_ratio",
        "before": quality.get("relevant_ratio"),
        "relevant": quality.get("relevant"),
        "items": quality.get("items"),
        "feed_caps": caps,
        "offline_drafts": checklist.get("draft_done"),
        "store_done": checklist.get("done"),
        "steps_total": checklist.get("total"),
        "decisions": decisions,
        "status": decisions[-1]["action"] if decisions else ("active" if caps else "no_change"),
    }


# ──────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="정책 파일을 쓰지 않고 판단만 출력")
    ap.add_argument("--only", choices=["topics", "sourcing", "design"])
    args = ap.parse_args()
    dry = args.dry_run

    history = load(HISTORY, {})
    loops = {}
    runners = {"topics": lambda: topic_loop(dry), "sourcing": lambda: sourcing_loop(dry),
               "design": lambda: design_loop(history, dry)}
    for name, fn in runners.items():
        if args.only and name != args.only:
            continue
        try:
            loops[name] = fn()
        except Exception as exc:  # 한 루프가 죽어도 다른 루프는 돈다. 조용히 넘기지 않고 적는다.
            loops[name] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300], "decisions": []}

    at = now()
    runs = history.setdefault("runs", [])
    runs.append({"at": at, **{k: {"status": v.get("status"), "before": v.get("before")}
                                for k, v in loops.items()}})
    del runs[:-HISTORY_MAX]
    ledger = load(LEDGER, [])
    for v in loops.values():
        for d in v.get("decisions", []):
            ledger.append({"at": at, **d})
    del ledger[:-LEDGER_MAX]

    status = {
        "generated_at": at,
        "generator": "scripts/self_improve.py",
        "principle": "무료·설정만 변경·그림자 평가 후 채택·실측 악화 시 자동 롤백",
        "loops": loops,
        "decisions_total": len(ledger),
    }
    save(STATUS, status, dry)
    save(LEDGER, ledger, dry)
    save(HISTORY, history, dry)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "decisions"} | {
        "decisions": [(d.get("action"), d.get("keyword") or d.get("feed") or d.get("reason", "")[:60])
                      for d in v.get("decisions", [])][:20]} for k, v in loops.items()},
        ensure_ascii=False, indent=1))
    return 1 if any(v.get("status") == "error" for v in loops.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
