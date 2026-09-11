#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS Chief of Staff + Safe Auto-Fix Agent
============================================

역할
----
이 파일은 JARVIS의 운영 조정 계층이다.

1. 현재 데이터 상태를 읽는다.
2. 비서실장(Chief of Staff)이 전체 상황을 종합 판단한다.
3. P0~P4 우선순위를 결정한다.
4. 안전하게 실행 가능한 작업만 승인한다.
5. 승인된 Safe Auto-Fix만 실행한다.
6. 결과를 다시 검증한다.
7. 판단 결과를 data/agents/chief_of_staff.json 에 기록한다.
8. 자동수정 결과를 data/agents/autofix_report.json 에 기록한다.

중요
----
비서실장은 "무엇을 해야 하는가"를 결정한다.
실제 변경은 whitelist가 있는 Safe Auto-Fix 함수만 수행한다.

자동 수정 허용
--------------
A. Daiso 실패 SKU의 blacklist 동기화
B. Obsidian wikilink 정규화
C. Obsidian graph rebuild
D. dashboard_runtime 재생성
E. 비서실장 판단/운영 보고 JSON 생성

자동 수정 금지
--------------
- Python 코드 수정
- GitHub Actions YAML 수정
- collection_status.json 직접 수정
- 가격 임의 생성
- 점수 임의 생성
- Shopify Admin 실제 등록
- Shopify 상품 발행
- 광고 집행
- 결제 설정 변경
- 법률/세관 외부 제출
- secrets 변경
- force push
- 외부 계정 변경

비서실장 판단 원칙
------------------
P0 = 시스템/데이터 무결성 위협
P1 = 현재 파이프라인을 막는 핵심 장애
P2 = 수집/채널/점수 품질 저하
P3 = 운영 개선
P4 = 일반 제안

자동 실행 원칙
--------------
1. 데이터 근거가 존재해야 한다.
2. 허용된 파일/스크립트 범위 안에서만 실행한다.
3. 애매한 데이터는 HOLD한다.
4. 실행 결과를 기록한다.
5. 성공 여부를 return code로 검증한다.

이번 수정의 핵심
----------------
- dashboard_runtime의 graph 값을 무조건 신뢰하지 않는다.
- Obsidian/JARVIS_LUNA 원본을 직접 검사하는 Truth Guard를 사용한다.
- "nodes=0인데 links>0" 같은 명백한 메타데이터 모순도 문제로 판정한다.
- 실제 dangling generated link가 존재하면 P1 NORMALIZE_AND_REBUILD_GRAPH를 승인한다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

AGENTS_DIR = ROOT / "data" / "agents"
DAISO_DIR = ROOT / "data" / "daiso_real"
COLLECTION_STATUS = DAISO_DIR / "collection_status.json"
BEAUTY_QUEUE = DAISO_DIR / "beauty_queue.json"
RUNTIME = ROOT / "data" / "dashboard_runtime.json"

OBSIDIAN_VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
NORMALIZE_SCRIPT = ROOT / "scripts" / "normalize_obsidian_links.py"
RUNTIME_SCRIPT = ROOT / "scripts" / "generate_dashboard_runtime.py"

GRAPH_SCRIPT_CANDIDATES = [
    ROOT / "scripts" / "rebuild_obsidian_graph.py",
    ROOT / "scripts" / "rebuild_graph.py",
    ROOT / "scripts" / "rebuild_obsidian.py",
]

ORGANIZE_GRAPH_SCRIPT = ROOT / "organize_obsidian_graph.py"
EXPAND_GRAPH_SCRIPT = ROOT / "expand_obsidian_graph.py"
TEAM_HUB_SCRIPT = ROOT / "scripts" / "build_team_hubs.py"

REPORT = AGENTS_DIR / "autofix_report.json"
CHIEF_REPORT = AGENTS_DIR / "chief_of_staff.json"

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] JSON load failed: {path} :: {exc}")
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def env_true(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def normalize_pd_no(value: Any) -> str:
    return "" if value is None else str(value).strip()


def get_collection_last_run(collection_status: dict) -> dict:
    value = collection_status.get("last_run")
    return value if isinstance(value, dict) else {}


def extract_failed_products(collection_status: dict) -> list[dict]:
    samples = get_collection_last_run(collection_status).get("parse_fail_samples")
    if not isinstance(samples, list):
        return []
    return [x for x in samples if isinstance(x, dict)]


# ============================================================================
# DAISO SAFETY
# ============================================================================

def is_safe_daiso_blacklist_candidate(sample: dict) -> bool:
    pd_no = normalize_pd_no(sample.get("pd_no"))
    if not pd_no:
        return False

    reason = str(sample.get("reason") or "").strip()
    if "가격" not in reason:
        return False

    og_title = str(sample.get("og_title") or "").strip()
    if og_title not in {"", "다이소몰", "Daiso", "DAISO", "daiso"}:
        return False

    if sample.get("sold_out") is True:
        return False

    return True


def get_blacklist(queue: dict) -> tuple[list[Any], str]:
    for field in ("blacklist_pd_nos", "blacklist"):
        value = queue.get(field)
        if isinstance(value, list):
            return value, field
    queue["blacklist"] = []
    return queue["blacklist"], "blacklist"


def get_priority_pd_nos(queue: dict) -> tuple[list[Any] | None, str | None]:
    for field in ("priority_pd_nos", "priority", "pd_nos", "priority_products"):
        value = queue.get(field)
        if isinstance(value, list):
            return value, field
    return None, None


def remove_pd_from_priority_list(queue: dict, pd_no: str) -> tuple[bool, str | None]:
    priority_list, field = get_priority_pd_nos(queue)
    if priority_list is None or field is None:
        return False, None
    filtered = [value for value in priority_list if normalize_pd_no(value) != pd_no]
    changed = filtered != priority_list
    if changed:
        queue[field] = filtered
    return changed, field


def maybe_remove_from_url_list(queue: dict, pd_no: str) -> tuple[bool, str | None]:
    urls = queue.get("urls")
    if not isinstance(urls, list):
        return False, None
    filtered = [value for value in urls if pd_no not in str(value)]
    changed = filtered != urls
    if changed:
        queue["urls"] = filtered
    return changed, "urls" if changed else None


def repair_daiso_queue(collection_status: dict, queue: dict) -> dict:
    report = {
        "action": "repair_daiso_queue",
        "started_at": now_iso(),
        "enabled": True,
        "changed": False,
        "added_to_blacklist": [],
        "already_blacklisted": [],
        "removed_from_priority": [],
        "removed_from_urls": [],
        "candidate_count": 0,
        "reason": None,
    }

    candidates = [x for x in extract_failed_products(collection_status) if is_safe_daiso_blacklist_candidate(x)]
    report["candidate_count"] = len(candidates)
    if not candidates:
        report["reason"] = "safe_blacklist_candidate=0"
        report["finished_at"] = now_iso()
        return report

    blacklist, blacklist_field = get_blacklist(queue)
    existing = {normalize_pd_no(value) for value in blacklist if normalize_pd_no(value)}

    for sample in candidates:
        pd_no = normalize_pd_no(sample.get("pd_no"))
        if not pd_no:
            continue

        if pd_no in existing:
            report["already_blacklisted"].append(pd_no)
        else:
            blacklist.append(pd_no)
            existing.add(pd_no)
            report["added_to_blacklist"].append(pd_no)
            report["changed"] = True

        priority_changed, priority_field = remove_pd_from_priority_list(queue, pd_no)
        if priority_changed:
            report["removed_from_priority"].append({"pd_no": pd_no, "field": priority_field})
            report["changed"] = True

        url_changed, url_field = maybe_remove_from_url_list(queue, pd_no)
        if url_changed:
            report["removed_from_urls"].append({"pd_no": pd_no, "field": url_field})
            report["changed"] = True

    queue[blacklist_field] = blacklist
    report["blacklist_field"] = blacklist_field
    report["finished_at"] = now_iso()
    return report


# ============================================================================
# OBSIDIAN TRUTH GUARD
# ============================================================================

def normalize_note_target(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value)).strip().replace("\\", "/")
    normalized = normalized.rsplit("/", 1)[-1]
    if normalized.lower().endswith(".md"):
        normalized = normalized[:-3]
    return normalized.lower()


def inspect_obsidian_truth(runtime_graph: dict | None = None) -> dict:
    """실제 Obsidian 파일을 직접 검사해 runtime graph보다 우선하는 진실값을 만든다."""
    runtime_graph = runtime_graph if isinstance(runtime_graph, dict) else {}

    notes = sorted(OBSIDIAN_VAULT.rglob("*.md")) if OBSIDIAN_VAULT.exists() else []
    stems = {normalize_note_target(note.stem) for note in notes}
    links = 0
    generated_targets: list[str] = []
    personal_targets: list[str] = []
    broken_generated: list[dict] = []
    broken_personal: list[dict] = []

    for note in notes:
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        found = WIKILINK_RE.findall(text)
        links += len(found)

        try:
            rel_parts = note.relative_to(OBSIDIAN_VAULT).parts
            top = rel_parts[0] if rel_parts else ""
        except ValueError:
            top = ""

        is_personal = top == "Personal"
        bucket = personal_targets if is_personal else generated_targets
        broken_bucket = broken_personal if is_personal else broken_generated

        for target in found:
            target_norm = normalize_note_target(target)
            if not target_norm:
                continue
            bucket.append(target_norm)
            if target_norm not in stems:
                broken_bucket.append({"source": str(note.relative_to(OBSIDIAN_VAULT)), "target": target_norm})

    runtime_nodes = int(runtime_graph.get("nodes") or runtime_graph.get("notes") or 0)
    runtime_links = int(runtime_graph.get("links") or 0)
    runtime_dangling = int(runtime_graph.get("dangling_generated") or runtime_graph.get("dangling_links") or runtime_graph.get("dangling") or 0)

    anomaly_reasons: list[str] = []
    if not OBSIDIAN_VAULT.exists():
        anomaly_reasons.append("obsidian_vault_missing")
    if notes and runtime_nodes == 0 and runtime_links > 0:
        anomaly_reasons.append("runtime_graph_nodes_zero_but_links_positive")
    if notes and runtime_nodes not in {0, len(notes)}:
        anomaly_reasons.append(f"runtime_nodes_mismatch:runtime={runtime_nodes},actual={len(notes)}")
    if runtime_dangling > 0 and not broken_generated:
        anomaly_reasons.append("runtime_reports_dangling_but_direct_scan_found_none")
    if broken_generated:
        anomaly_reasons.append(f"actual_generated_dangling={len(broken_generated)}")

    return {
        "vault": str(OBSIDIAN_VAULT.relative_to(ROOT)) if OBSIDIAN_VAULT.exists() else str(OBSIDIAN_VAULT),
        "actual_nodes": len(notes),
        "actual_links": links,
        "actual_dangling_generated": len(broken_generated),
        "actual_dangling_personal": len(broken_personal),
        "generated_dangling_samples": broken_generated[:50],
        "personal_dangling_samples": broken_personal[:20],
        "runtime_nodes": runtime_nodes,
        "runtime_links": runtime_links,
        "runtime_dangling_generated": runtime_dangling,
        "runtime_consistent": not anomaly_reasons,
        "anomaly": bool(anomaly_reasons),
        "anomaly_reasons": anomaly_reasons,
    }


# ============================================================================
# COMMANDS
# ============================================================================

def run_command(command: list[str], label: str, timeout: int = 180) -> dict:
    result = {
        "label": label,
        "command": command,
        "started_at": now_iso(),
        "returncode": None,
        "ok": False,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
    }
    print(f"[RUN] {label}")

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        result["returncode"] = completed.returncode
        result["stdout"] = (completed.stdout or "")[-10000:]
        result["stderr"] = (completed.stderr or "")[-10000:]
        result["ok"] = completed.returncode == 0
    except subprocess.TimeoutExpired as exc:
        result["timed_out"] = True
        result["stdout"] = str(getattr(exc, "stdout", "") or "")[-10000:]
        result["stderr"] = str(getattr(exc, "stderr", "") or "")[-10000:]
    except Exception as exc:
        result["stderr"] = f"{type(exc).__name__}: {exc}"

    result["finished_at"] = now_iso()
    print(f"[{'OK' if result['ok'] else 'FAIL'}] {label} returncode={result['returncode']}")
    return result


def run_obsidian_normalizer() -> dict:
    if not NORMALIZE_SCRIPT.exists():
        return {"label": "normalize_obsidian_links", "ok": False, "skipped": True, "reason": "script_not_found"}
    return run_command([sys.executable, str(NORMALIZE_SCRIPT)], "normalize_obsidian_links", 300)


def run_graph_rebuild() -> list[dict]:
    results: list[dict] = []

    if ORGANIZE_GRAPH_SCRIPT.exists():
        results.append(run_command([sys.executable, str(ORGANIZE_GRAPH_SCRIPT)], "organize_obsidian_graph", 300))

    if EXPAND_GRAPH_SCRIPT.exists():
        results.append(run_command([sys.executable, str(EXPAND_GRAPH_SCRIPT)], "expand_obsidian_graph", 300))

    graph_script = next((p for p in GRAPH_SCRIPT_CANDIDATES if p.exists()), None)
    if graph_script is not None and graph_script not in {ORGANIZE_GRAPH_SCRIPT, EXPAND_GRAPH_SCRIPT}:
        results.append(run_command([sys.executable, str(graph_script)], "graph_rebuild", 300))

    if TEAM_HUB_SCRIPT.exists():
        results.append(run_command([sys.executable, str(TEAM_HUB_SCRIPT)], "build_team_hubs", 180))

    if not results:
        results.append({"label": "graph_rebuild", "ok": True, "skipped": True, "reason": "no_graph_script_found"})

    return results


def run_runtime_generation() -> dict:
    if not RUNTIME_SCRIPT.exists():
        return {"label": "generate_dashboard_runtime", "ok": False, "skipped": True, "reason": "script_not_found"}
    return run_command([sys.executable, str(RUNTIME_SCRIPT)], "generate_dashboard_runtime", 300)


# ============================================================================
# VALIDATION / SNAPSHOT
# ============================================================================

def validate_queue_after_fix(queue: dict) -> dict:
    valid = isinstance(queue, dict)
    blacklist, blacklist_field = get_blacklist(queue)
    checks = {
        "queue_is_dict": valid,
        "blacklist_is_list": isinstance(blacklist, list),
        "blacklist_field": blacklist_field,
    }
    checks["ok"] = bool(checks["queue_is_dict"] and checks["blacklist_is_list"])
    return checks


def validate_runtime() -> dict:
    result = {"exists": RUNTIME.exists(), "valid_json": False, "has_channels": False, "has_graph": False, "ok": False}
    if not RUNTIME.exists():
        return result
    runtime = load_json(RUNTIME, {})
    if not isinstance(runtime, dict):
        return result
    result["valid_json"] = True
    result["has_channels"] = "global_channels" in runtime and "global_channels_status" in runtime
    result["has_graph"] = "graph" in runtime
    result["ok"] = bool(result["valid_json"] and result["has_channels"])
    return result


def get_source_snapshot() -> dict:
    collection = load_json(COLLECTION_STATUS, {})
    queue = load_json(BEAUTY_QUEUE, {})
    runtime = load_json(RUNTIME, {})
    if not isinstance(collection, dict):
        collection = {}
    if not isinstance(queue, dict):
        queue = {}
    if not isinstance(runtime, dict):
        runtime = {}

    last_run = get_collection_last_run(collection)
    parse_failed = int(last_run.get("parse_failed") or 0)
    requested = int(last_run.get("requested") or 0)
    ok_count = int(last_run.get("ok") or 0)

    live_channels = 0
    total_channels = 0
    empty_channels: list[dict] = []
    channel_status = runtime.get("global_channels_status") or {}
    if isinstance(channel_status, dict):
        total_channels = len(channel_status)
        for name, meta in channel_status.items():
            if not isinstance(meta, dict):
                continue
            count = int(meta.get("count") or 0)
            status = str(meta.get("status") or "").lower()
            if count > 0 and status not in {"failed", "disabled"}:
                live_channels += 1
            if count == 0 or status in {"empty", "failed"}:
                empty_channels.append({
                    "channel": name,
                    "count": count,
                    "status": status or "empty",
                    "reason": meta.get("reason"),
                })

    runtime_graph = runtime.get("graph") or {}
    if not isinstance(runtime_graph, dict):
        runtime_graph = {}

    graph_truth = inspect_obsidian_truth(runtime_graph)

    s_count = 0
    for path in [
        DAISO_DIR / "shopify_s_recommendations.json",
        ROOT / "data" / "shopify_s_recommendations.json",
    ]:
        if not path.exists():
            continue
        score_data = load_json(path, {})
        if isinstance(score_data, dict):
            recommendations = score_data.get("recommendations") or score_data.get("items") or []
            if isinstance(recommendations, list):
                s_count = len(recommendations)
            elif isinstance(score_data.get("count"), int):
                s_count = int(score_data["count"])
            break
        if isinstance(score_data, list):
            s_count = len(score_data)
            break

    return {
        "collection": {
            "requested": requested,
            "ok": ok_count,
            "parse_failed": parse_failed,
            "finished_at": last_run.get("finished_at"),
        },
        "channels": {"live": live_channels, "total": total_channels, "empty": empty_channels},
        "graph": {
            # Chief가 사용할 graph 값은 실제 볼트 스캔 값을 우선한다.
            "nodes": graph_truth["actual_nodes"],
            "links": graph_truth["actual_links"],
            "dangling_generated": graph_truth["actual_dangling_generated"],
            "runtime_nodes": graph_truth["runtime_nodes"],
            "runtime_links": graph_truth["runtime_links"],
            "runtime_dangling_generated": graph_truth["runtime_dangling_generated"],
            "truth_guard": graph_truth,
        },
        "shopify": {"s_count": s_count},
        "queue": {"blacklist_count": len(get_blacklist(queue)[0])},
    }


# ============================================================================
# CHIEF OF STAFF JUDGMENT
# ============================================================================

def chief_priority_sort_key(item: dict) -> tuple[int, int]:
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
    return order.get(item.get("priority", "P4"), 4), -int(item.get("severity_score") or 0)


def build_chief_of_staff_decision(snapshot: dict) -> dict:
    collection = snapshot["collection"]
    channels = snapshot["channels"]
    graph = snapshot["graph"]
    shopify = snapshot["shopify"]
    decisions: list[dict] = []

    parse_failed = int(collection.get("parse_failed") or 0)
    live_channels = int(channels.get("live") or 0)
    total_channels = int(channels.get("total") or 0)
    empty_channels = channels.get("empty") or []
    dangling_generated = int(graph.get("dangling_generated") or 0)
    s_count = int(shopify.get("s_count") or 0)
    truth_guard = graph.get("truth_guard") or {}

    # P0 - 명백한 메타데이터/상태 모순
    if (
        graph.get("nodes", 0) < 0
        or graph.get("links", 0) < 0
        or truth_guard.get("anomaly_reasons")
        and any("nodes_zero_but_links_positive" in str(x) for x in truth_guard.get("anomaly_reasons", []))
    ):
        reasons = truth_guard.get("anomaly_reasons") or []
        decisions.append({
            "priority": "P0",
            "severity_score": 100,
            "area": "graph",
            "action": "HOLD_AND_INVESTIGATE",
            "reason": "그래프 메타데이터/실제 볼트 상태에 명백한 무결성 모순이 있다: " + "; ".join(map(str, reasons)),
            "auto_execute": False,
        })

    # P1 - 실제 생성 영역 dangling 또는 runtime/실제 볼트 불일치
    truth_issue = bool(truth_guard.get("anomaly"))
    if dangling_generated > 0 or truth_issue:
        actual_dangling = max(dangling_generated, int(truth_guard.get("actual_dangling_generated") or 0))
        reason_parts = []
        if actual_dangling:
            reason_parts.append(f"생성된 dangling 링크가 실제 검사에서 {actual_dangling}건 존재한다")
        if truth_guard.get("anomaly_reasons"):
            reason_parts.append("Truth Guard: " + "; ".join(map(str, truth_guard["anomaly_reasons"])))
        decisions.append({
            "priority": "P1",
            "severity_score": min(99, 60 + min(max(actual_dangling, 1), 39)),
            "area": "obsidian",
            "action": "NORMALIZE_AND_REBUILD_GRAPH",
            "reason": " / ".join(reason_parts) or "Obsidian 상태 이상이 감지되었다.",
            "auto_execute": True,
        })

    # P1 - Daiso
    if parse_failed > 0:
        decisions.append({
            "priority": "P1",
            "severity_score": min(98, 65 + min(parse_failed, 33)),
            "area": "daiso",
            "action": "SAFE_BLACKLIST_SYNC",
            "reason": f"다이소 수집 parse_failed가 {parse_failed}건 존재한다.",
            "auto_execute": True,
        })

    # P2
    if total_channels > 0 and live_channels < 8:
        decisions.append({
            "priority": "P2",
            "severity_score": 80,
            "area": "signals",
            "action": "REFRESH_LOW_SIGNAL_CHANNELS",
            "reason": f"활성 채널 {live_channels}/{total_channels}로 낮다.",
            "auto_execute": False,
        })

    if empty_channels:
        decisions.append({
            "priority": "P2",
            "severity_score": 72,
            "area": "signals",
            "action": "INVESTIGATE_EMPTY_CHANNELS",
            "reason": f"비어 있거나 실패 상태인 채널이 {len(empty_channels)}개 존재한다.",
            "channels": [x.get("channel") for x in empty_channels[:8]],
            "auto_execute": False,
        })

    if s_count == 0:
        decisions.append({
            "priority": "P2",
            "severity_score": 78,
            "area": "shopify_score",
            "action": "REVIEW_SCORE_PIPELINE",
            "reason": "Shopify S등급 추천이 0건이다.",
            "auto_execute": False,
        })

    # P3
    blacklist_count = int(snapshot["queue"].get("blacklist_count") or 0)
    if blacklist_count > 0:
        decisions.append({
            "priority": "P3",
            "severity_score": 45,
            "area": "daiso_queue",
            "action": "MONITOR_BLACKLIST",
            "reason": f"현재 blacklist가 {blacklist_count}건이다.",
            "auto_execute": False,
        })

    if not decisions:
        decisions.append({
            "priority": "P4",
            "severity_score": 10,
            "area": "system",
            "action": "MONITOR",
            "reason": "즉시 자동수정이 필요한 핵심 장애가 없다.",
            "auto_execute": False,
        })

    decisions.sort(key=chief_priority_sort_key)
    top = decisions[0]
    auto_actions = [x for x in decisions if x.get("auto_execute")]
    hold_actions = [x for x in decisions if not x.get("auto_execute")]

    risk = {"P0": "critical", "P1": "high", "P2": "medium"}.get(top.get("priority"), "low")

    return {
        "agent": "Chief-of-Staff",
        "role": "전체 JARVIS 운영상태를 종합하여 우선순위와 Safe Auto-Fix 실행 여부를 결정",
        "generated_at": now_iso(),
        "risk": risk,
        "overall_priority": top.get("priority"),
        "overall_action": top.get("action"),
        "overall_reason": top.get("reason"),
        "decisions": decisions,
        "approved_auto_actions": auto_actions,
        "human_review_actions": hold_actions,
        "policy": {
            "may_modify_data": True,
            "may_modify_code": False,
            "may_modify_workflows": False,
            "may_register_shopify": False,
            "may_run_ads": False,
            "may_change_secrets": False,
            "may_force_push": False,
        },
        "snapshot": snapshot,
    }


def approved_action_names(chief: dict) -> set[str]:
    return {
        str(item.get("action") or "")
        for item in (chief.get("approved_auto_actions") or [])
        if isinstance(item, dict) and item.get("action")
    }


def should_run_queue_autofix(chief: dict) -> bool:
    return "SAFE_BLACKLIST_SYNC" in approved_action_names(chief)


def should_run_obsidian_autofix(chief: dict) -> bool:
    return "NORMALIZE_AND_REBUILD_GRAPH" in approved_action_names(chief)


# ============================================================================
# MAIN SAFE AUTOFIX
# ============================================================================

def safe_policy() -> dict:
    return {
        "allow_code_autofix": False,
        "allow_workflow_autofix": False,
        "allow_collection_status_edit": False,
        "allow_shopify_write": False,
        "allow_external_account_write": False,
        "allow_force_push": False,
        "allow_deterministic_data_repair": True,
    }


def main() -> int:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 80)
    print("JARVIS CHIEF OF STAFF + SAFE AUTO-FIX")
    print("=" * 80)

    collection_status = load_json(COLLECTION_STATUS, {})
    queue = load_json(BEAUTY_QUEUE, {})
    if not isinstance(collection_status, dict):
        collection_status = {}
    if not isinstance(queue, dict):
        queue = {}

    snapshot = get_source_snapshot()
    print("[STATE]")
    print("  Daiso parse_failed:", snapshot["collection"]["parse_failed"])
    print("  Global channels:", f"{snapshot['channels']['live']}/{snapshot['channels']['total']}")
    print("  Graph nodes:", snapshot["graph"]["nodes"])
    print("  Graph links:", snapshot["graph"]["links"])
    print("  Graph dangling:", snapshot["graph"]["dangling_generated"])
    print("  Shopify S:", snapshot["shopify"]["s_count"])

    chief = build_chief_of_staff_decision(snapshot)
    save_json(CHIEF_REPORT, chief)

    print("[CHIEF]", chief["overall_priority"], chief["overall_action"])
    print("[CHIEF REASON]", chief["overall_reason"])
    for decision in chief["decisions"]:
        print(f"[{decision.get('priority')}] {decision.get('action')} auto={decision.get('auto_execute')}")

    autofix_enabled = env_true("JARVIS_AUTOFIX", True)
    autofix_force = env_true("JARVIS_AUTOFIX_FORCE", False)

    if autofix_force:
        print("[INFO] JARVIS_AUTOFIX_FORCE detected. Force only bypasses trigger gating; it does not bypass Safe Auto-Fix policy.")

    if not autofix_enabled:
        report = {
            "agent": "Safe-Auto-Fix",
            "generated_at": now_iso(),
            "status": "disabled",
            "enabled": False,
            "chief_of_staff": chief,
            "changes": [],
            "policy": safe_policy(),
        }
        save_json(REPORT, report)
        print("SAFE AUTO-FIX disabled.")
        return 0

    changes: list[dict] = []

    # A. Daiso queue
    queue_report: dict = {
        "action": "repair_daiso_queue",
        "changed": False,
        "skipped": True,
        "reason": "Chief of Staff did not approve SAFE_BLACKLIST_SYNC",
    }

    if should_run_queue_autofix(chief) or autofix_force:
        queue_report = repair_daiso_queue(collection_status, queue)
        if queue_report.get("changed"):
            save_json(BEAUTY_QUEUE, queue)
            print("[WRITE]", BEAUTY_QUEUE)
        else:
            print("[NO CHANGE]", BEAUTY_QUEUE)
    changes.append(queue_report)

    # B. Queue validation
    queue_validation = validate_queue_after_fix(queue)
    if not queue_validation.get("ok"):
        failure_report = {
            "agent": "Safe-Auto-Fix",
            "generated_at": now_iso(),
            "status": "failed",
            "chief_of_staff": chief,
            "queue": queue_report,
            "queue_validation": queue_validation,
            "changes": changes,
            "policy": safe_policy(),
        }
        save_json(REPORT, failure_report)
        print("[ERROR] beauty_queue validation failed")
        return 1

    # C. Obsidian
    obsidian_report: dict = {
        "action": "normalize_obsidian_links",
        "changed": False,
        "skipped": True,
        "reason": "Chief of Staff did not approve NORMALIZE_AND_REBUILD_GRAPH",
    }
    graph_reports: list[dict] = []

    # 더 이상 불필요한 'autofix_force and False' 우회식은 사용하지 않는다.
    # force는 whitelist 정책을 우회하지 않으며, Obsidian 강제 실행을 원하면
    # 기존의 명시적 JARVIS_AUTOFIX_OBSIDIAN 환경변수만 허용한다.
    run_obsidian = (
        should_run_obsidian_autofix(chief)
        or env_true("JARVIS_AUTOFIX_OBSIDIAN", False)
    )

    if run_obsidian:
        obsidian_report = run_obsidian_normalizer()
        if obsidian_report.get("ok"):
            graph_reports = run_graph_rebuild()

    changes.append(obsidian_report)
    if graph_reports:
        changes.append({
            "action": "graph_rebuild",
            "results": graph_reports,
            "ok": all(item.get("ok") for item in graph_reports),
        })

    # D. Runtime refresh
    runtime_should_refresh = bool(
        queue_report.get("changed")
        or graph_reports
        or env_true("JARVIS_AUTOFIX_RUNTIME", False)
    )

    runtime_report: dict = {
        "action": "runtime_refresh",
        "changed": False,
        "skipped": True,
        "reason": "no safe autofix output changed and runtime refresh not explicitly enabled",
    }

    if runtime_should_refresh:
        runtime_report = run_runtime_generation()
    changes.append(runtime_report)

    # E. Final validation
    runtime_validation = validate_runtime()
    all_command_results: list[dict] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        if "returncode" in change:
            all_command_results.append(change)
        nested = change.get("results")
        if isinstance(nested, list):
            all_command_results.extend(x for x in nested if isinstance(x, dict) and "returncode" in x)

    command_failures = [x for x in all_command_results if not x.get("ok")]
    final_status = "success" if not command_failures else "warning"

    if not runtime_validation["ok"] and runtime_report.get("changed"):
        final_status = "warning"

    # F. After snapshot
    after_snapshot = get_source_snapshot()
    improvement = {
        "graph_dangling_before": snapshot["graph"]["dangling_generated"],
        "graph_dangling_after": after_snapshot["graph"]["dangling_generated"],
        "graph_nodes_before": snapshot["graph"]["nodes"],
        "graph_nodes_after": after_snapshot["graph"]["nodes"],
        "graph_links_before": snapshot["graph"]["links"],
        "graph_links_after": after_snapshot["graph"]["links"],
        "parse_failed_before": snapshot["collection"]["parse_failed"],
        "parse_failed_after": after_snapshot["collection"]["parse_failed"],
        "s_count_before": snapshot["shopify"]["s_count"],
        "s_count_after": after_snapshot["shopify"]["s_count"],
        "channels_live_before": snapshot["channels"]["live"],
        "channels_live_after": after_snapshot["channels"]["live"],
        "obsidian_truth_before": snapshot["graph"].get("truth_guard"),
        "obsidian_truth_after": after_snapshot["graph"].get("truth_guard"),
    }

    # G. Report
    report = {
        "agent": "Safe-Auto-Fix",
        "generated_at": now_iso(),
        "status": final_status,
        "enabled": True,
        "chief_of_staff": {
            "report_path": str(CHIEF_REPORT.relative_to(ROOT)),
            "overall_priority": chief.get("overall_priority"),
            "overall_action": chief.get("overall_action"),
            "risk": chief.get("risk"),
        },
        "snapshot_before": snapshot,
        "snapshot_after": after_snapshot,
        "improvement": improvement,
        "changes": changes,
        "queue": queue_report,
        "queue_validation": queue_validation,
        "runtime_validation": runtime_validation,
        "command_failures": command_failures,
        "policy": safe_policy(),
        "safe_scope": [
            "data/daiso_real/beauty_queue.json",
            "obsidian/",
            "data/dashboard_runtime.json",
            "data/agents/chief_of_staff.json",
            "data/agents/autofix_report.json",
        ],
        "never_modified": [
            "Python source code",
            "GitHub Actions YAML",
            "data/daiso_real/collection_status.json",
            "Shopify Admin",
            "Shopify product publication",
            "ad accounts",
            "payment settings",
            "legal submissions",
            "secrets",
            "external accounts",
        ],
    }
    save_json(REPORT, report)

    # H. Console summary
    print("=" * 80)
    print("CHIEF OF STAFF:", chief.get("overall_priority"), chief.get("overall_action"))
    print("RISK:", chief.get("risk"))
    print("STATUS:", final_status)
    print("GRAPH:", improvement["graph_dangling_before"], "->", improvement["graph_dangling_after"])
    print("GRAPH NODES:", improvement["graph_nodes_before"], "->", improvement["graph_nodes_after"])
    print("GRAPH LINKS:", improvement["graph_links_before"], "->", improvement["graph_links_after"])
    print("DAISO parse_failed:", improvement["parse_failed_before"], "->", improvement["parse_failed_after"])
    print("SHOPIFY S:", improvement["s_count_before"], "->", improvement["s_count_after"])
    print("CHANNELS:", improvement["channels_live_before"], "->", improvement["channels_live_after"])
    if queue_report.get("added_to_blacklist"):
        print("BLACKLIST ADDED:", queue_report["added_to_blacklist"])
    if queue_report.get("already_blacklisted"):
        print("ALREADY BLACKLISTED:", queue_report["already_blacklisted"])
    print("CHIEF REPORT:", CHIEF_REPORT)
    print("AUTOFIX REPORT:", REPORT)
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
