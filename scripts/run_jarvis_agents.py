#!/usr/bin/env python3
"""JARVIS multi-agent plane (진단·우선순위·승인 초안만).

데이터 플레인(수집·채점·CSV·커밋)은 건드리지 않는다.
읽기: collection_status, products, S등급, runtime, CSV
쓰기: data/agents/*.json 만

LLM 없이 규칙 기반으로 동작 (토큰 0, Actions 안정).
필요 시 나중에 Gemini 호출 훅만 붙이면 된다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "data" / "agents"
DAISO = ROOT / "data" / "daiso_real"
RUNTIME = ROOT / "data" / "dashboard_runtime.json"


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def save(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def channel_live_count(runtime: dict) -> tuple[int, int, list[dict]]:
    st = runtime.get("global_channels_status") or {}
    gc = runtime.get("global_channels") or {}
    keys = list(st.keys()) or list(gc.keys())
    live = []
    stale = []
    for k in keys:
        meta = st.get(k) or {}
        n = meta.get("count")
        if n is None:
            n = len(gc.get(k) or [])
        status = (meta.get("status") or "").lower()
        if status in ("disabled", "failed"):
            continue
        if int(n or 0) > 0:
            live.append(k)
        # stale hint
        src = meta.get("source") or meta.get("note") or ""
        if "수동" in str(src) or "fallback" in str(src).lower() or status == "empty":
            stale.append({"channel": k, "count": n, "status": status or "unknown", "note": str(src)[:120]})
    return len(live), len(keys) or 12, stale


def agent_collector(coll: dict, queue: dict) -> dict:
    lr = coll.get("last_run") or {}
    pf = int(lr.get("parse_failed") or 0)
    ok = int(lr.get("ok") or 0)
    req = int(lr.get("requested") or 0)
    samples = lr.get("parse_fail_samples") or []
    reasons = lr.get("parse_fail_reasons") or {}
    types = []
    for s in samples:
        og = (s.get("og_title") or "").strip()
        reason = s.get("reason") or ""
        if og in ("다이소몰", "Daiso", "") and "가격" in reason:
            types.append({"pd_no": s.get("pd_no"), "type": "og_title_only_no_price", "og_title": og, "sold_out": s.get("sold_out")})
        elif s.get("sold_out"):
            types.append({"pd_no": s.get("pd_no"), "type": "sold_out", "og_title": og})
        else:
            types.append({"pd_no": s.get("pd_no"), "type": "parse_other", "reason": reason, "og_title": og})
    bl = []
    if isinstance(queue, dict):
        bl = queue.get("blacklist") or queue.get("blacklist_pd_nos") or []
        if not bl and isinstance(queue.get("urls"), list):
            pass
    suggestions = []
    if pf > 0:
        suggestions.append({
            "action": "keep_blacklist_and_prefer_category",
            "detail": "가격없음/og_title만 잡히는 pd_no는 beauty_queue 블랙리스트 유지. 로션/오일/미스트 등 대체 카테고리 URL 우선.",
            "category_url": "https://www.daisomall.co.kr/ds/exhCtgr/C208/CTGR_01050/CTGR_01061/CTGR_01114",
        })
        suggestions.append({
            "action": "do_not_retry_failed_pd_nos",
            "pd_nos": [t.get("pd_no") for t in types if t.get("pd_no")],
        })
    totals = (coll.get("totals") or {}).get("products")
    return {
        "agent": "Collector-Audit",
        "generated_at": now_iso(),
        "last_run": {
            "requested": req,
            "ok": ok,
            "parse_failed": pf,
            "reasons": reasons,
            "finished_at": lr.get("finished_at"),
        },
        "failure_types": types,
        "products_total": totals,
        "blacklist_hint": bl[:20] if isinstance(bl, list) else bl,
        "suggestions": suggestions,
        "severity": pf > 0,
    }


def agent_signal(runtime: dict) -> dict:
    live, total, stale = channel_live_count(runtime)
    st = runtime.get("global_channels_status") or {}
    empty = []
    for k, meta in st.items():
        n = int((meta or {}).get("count") or 0)
        status = ((meta or {}).get("status") or "").lower()
        if n == 0 or status in ("empty", "failed"):
            empty.append({"channel": k, "count": n, "status": status or "empty"})
    return {
        "agent": "Signal-Audit",
        "generated_at": now_iso(),
        "live_channels": live,
        "total_channels": total,
        "empty_or_failed": empty,
        "stale_or_manual": stale[:12],
        "severity": live < 8 or len(empty) > 0,
        "suggestions": (
            [{"action": "refresh_stale_channels", "channels": [s["channel"] for s in stale[:5]]}]
            if stale else []
        )
        + ([{"action": "investigate_empty_channels", "channels": [e["channel"] for e in empty[:5]]}] if empty else []),
    }


def agent_score(srec: dict, demand: dict | None = None) -> dict:
    recs = srec.get("recommendations") or []
    lines = []
    for r in recs[:12]:
        m = r.get("matched_global") or r.get("best_global_match") or {}
        tokens = m.get("matched_tokens") or []
        lines.append({
            "pd_no": r.get("pd_no"),
            "name": r.get("name"),
            "score": r.get("shopify_score"),
            "why": r.get("recommend_reason") or "",
            "global": m.get("global_product"),
            "channel": m.get("channel"),
            "tokens": tokens,
        })
    gaps = []
    if not recs:
        gaps.append("S등급 0건 — score_shopify_demand 재실행 또는 글로벌 시그널·다이소 매칭 점검")
    return {
        "agent": "Score-Explain",
        "generated_at": now_iso(),
        "s_count": srec.get("count", len(recs)),
        "rule": srec.get("rule"),
        "items": lines,
        "gaps": gaps,
        "severity": len(recs) == 0,
    }


def agent_listing(srec: dict, runtime: dict) -> dict:
    recs = srec.get("recommendations") or []
    # legal blocks from teams if present
    blocked = []
    for t in runtime.get("teams") or []:
        if t.get("id") == "legal" or "법률" in str(t.get("name") or ""):
            act = t.get("action") or ""
            if act:
                blocked.append(act[:200])
    notes = []
    for r in recs:
        notes.append({
            "pd_no": r.get("pd_no"),
            "name": r.get("name"),
            "csv": "data/daiso_real/shopify_s_products_import.csv",
            "status_suggest": "draft",
            "note": "Variant Price 비움 — 원가 모델 확인 후 입력. Cost per item·image·pd_no는 CSV에 있음.",
        })
    return {
        "agent": "Listing-Draft",
        "generated_at": now_iso(),
        "s_count": len(recs),
        "csv_path": "data/daiso_real/shopify_s_products_import.csv",
        "items": notes,
        "legal_blocks": blocked,
        "suggestions": [
            {
                "action": "import_csv_as_draft",
                "detail": f"S등급 {len(recs)}건 CSV → Shopify Admin Products Import (Published=false)",
            }
        ]
        + ([{"action": "resolve_legal_blocks", "detail": b} for b in blocked[:3]]),
    }


def agent_ops(collector: dict, signal: dict, score: dict, listing: dict, runtime: dict) -> dict:
    tasks = []
    risk = "low"

    if collector.get("severity"):
        risk = "high"
        pf = (collector.get("last_run") or {}).get("parse_failed") or 0
        tasks.append({
            "priority": 1,
            "title": f"수집 파싱실패 {pf}건 처리",
            "detail": "블랙리스트 유지 · 대체 카테고리 우선 · 실패 pd_no 재시도 금지",
            "refs": ["data/agents/collector_audit.json", "data/daiso_real/collection_status.json"],
            "approve": "사람: beauty_queue/수집 범위 확인 후 다음 daiso-real-collection",
        })

    if signal.get("severity"):
        if risk != "high":
            risk = "medium"
        live = signal.get("live_channels")
        total = signal.get("total_channels")
        tasks.append({
            "priority": 2,
            "title": f"채널 시그널 점검 ({live}/{total} 라이브)",
            "detail": "empty/수동·낡은 채널 갱신",
            "refs": ["data/agents/signal_audit.json"],
            "approve": "사람: 해당 채널 수집기 또는 수동 JSON 갱신",
        })

    if score.get("severity"):
        risk = "high"
        tasks.append({
            "priority": 1,
            "title": "S등급 0건 — 점수 파이프 점검",
            "detail": "score_shopify_demand · 글로벌 매칭 · products.json",
            "refs": ["data/agents/score_explain.json"],
            "approve": "사람: Deep Analysis 재실행",
        })
    elif (score.get("s_count") or 0) > 0:
        tasks.append({
            "priority": 3,
            "title": f"S등급 {score.get('s_count')}건 Shopify draft 등록",
            "detail": "CSV Import · legal 차단 SKU 제외 · Variant Price는 원가 모델 후 입력",
            "refs": ["data/daiso_real/shopify_s_products_import.csv", "data/agents/listing_notes.json"],
            "approve": "사람: Admin Import + 가격·재고",
        })

    # team actions from runtime
    for t in runtime.get("teams") or []:
        act = (t.get("action") or "").strip()
        if not act:
            continue
        tasks.append({
            "priority": 4,
            "title": f"팀 조치 · {t.get('name') or t.get('id')}",
            "detail": act[:180],
            "refs": ["data/dashboard_runtime.json"],
            "approve": "사람: 팀 카드 조치 확인",
        })

    # dedupe by title, sort, cap 5
    seen = set()
    uniq = []
    for t in sorted(tasks, key=lambda x: x.get("priority", 99)):
        k = t["title"]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
        if len(uniq) >= 5:
            break

    return {
        "agent": "Ops-Prioritizer",
        "generated_at": now_iso(),
        "risk": risk,
        "task_count": len(uniq),
        "tasks": uniq,
        "note": "제안만 수행. 데이터 플레인 JSON은 수정하지 않음. 승인 후 기존 스크립트/수동 작업.",
        "dashboard": {
            "title": "에이전트 제안",
            "items": [{"n": i + 1, "text": t["title"] + " — " + t["detail"][:80]} for i, t in enumerate(uniq)],
        },
    }


def should_run(force: bool, coll: dict, srec: dict, runtime: dict) -> tuple[bool, str]:
    if force or os.environ.get("JARVIS_AGENTS_FORCE") == "1":
        return True, "force"
    pf = int(((coll.get("last_run") or {}).get("parse_failed") or 0))
    if pf >= 1:
        return True, f"parse_failed={pf}"
    s_count = int(srec.get("count") or len(srec.get("recommendations") or []))
    if s_count == 0:
        return True, "s_count=0"
    live, total, _ = channel_live_count(runtime)
    if total and live < 8:
        return True, f"live_channels={live}<8"
    # also run lightly if team actions exist
    acts = sum(1 for t in (runtime.get("teams") or []) if t.get("action"))
    if acts >= 3:
        return True, f"team_actions={acts}"
    return False, "skip_healthy"


def main() -> int:
    force = os.environ.get("JARVIS_AGENTS_FORCE") == "1" or "--force" in os.sys.argv
    coll = load(DAISO / "collection_status.json", {})
    queue = load(DAISO / "beauty_queue.json", {})
    srec = load(DAISO / "shopify_s_recommendations.json", {})
    runtime = load(RUNTIME, {})

    run, reason = should_run(force, coll, srec, runtime)
    AGENTS.mkdir(parents=True, exist_ok=True)

    if not run:
        payload = {
            "generated_at": now_iso(),
            "ran": False,
            "trigger": reason,
            "note": "이상 없음 — 에이전트 스킵 (비용·시간 절약)",
        }
        save(AGENTS / "last_run.json", payload)
        print("SKIP agents:", reason)
        return 0

    collector = agent_collector(coll, queue)
    signal = agent_signal(runtime)
    score = agent_score(srec)
    listing = agent_listing(srec, runtime)
    ops = agent_ops(collector, signal, score, listing, runtime)

    save(AGENTS / "collector_audit.json", collector)
    save(AGENTS / "signal_audit.json", signal)
    save(AGENTS / "score_explain.json", score)
    save(AGENTS / "listing_notes.json", listing)
    save(AGENTS / "ops_plan.json", ops)
    save(AGENTS / "last_run.json", {
        "generated_at": now_iso(),
        "ran": True,
        "trigger": reason,
        "risk": ops.get("risk"),
        "task_count": ops.get("task_count"),
    })

    # patch runtime commit_summary (optional, non-fatal)
    if RUNTIME.exists():
        try:
            rt = load(RUNTIME, {})
            line = f"agents: 조치후보 {ops.get('task_count', 0)}건 · risk {ops.get('risk')} · {reason}"
            prev = rt.get("commit_summary")
            if isinstance(prev, dict):
                prev["agents_line"] = line
                rt["commit_summary"] = prev
            else:
                rt["commit_summary"] = {"line": prev or line, "agents_line": line}
            rt["agents_ops"] = {
                "risk": ops.get("risk"),
                "task_count": ops.get("task_count"),
                "at": now_iso(),
            }
            save(RUNTIME, rt)
        except Exception as e:
            print("runtime patch skip:", e)

    print(f"OK agents trigger={reason} risk={ops.get('risk')} tasks={ops.get('task_count')}")
    for t in ops.get("tasks") or []:
        print(f"  P{t.get('priority')}: {t.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
