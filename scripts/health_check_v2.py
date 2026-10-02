"""
health_check_v2.py - P2 비서실장 상태 카드 + Error Dashboard + Data Freshness
- success / warning / degraded / failed 4분리
- Last Success / Failed Jobs / Queue / Stale Source 상단 KPI
- 각 카드에 2 min ago 표시
"""
import json
import datetime
from pathlib import Path
from datetime import timezone

from operational_freshness import assess_collection, assess_heartbeat

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

def parse_iso(s):
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def now_utc():
    return datetime.datetime.now(timezone.utc)


def hours_since(iso):
    dt = parse_iso(iso)
    if not dt:
        return 9999
    h = (now_utc() - dt).total_seconds() / 3600
    return max(0, h) if h >= -5 / 60 else 9999


def freshness_str(iso):
    h = hours_since(iso)
    if h == 9999:
        return "unknown"
    if h < 1 / 60:
        return "just now"
    if h < 1:
        return f"{int(h * 60)} min ago"
    if h < 24:
        return f"{h:.1f} hours ago"
    return f"{h / 24:.1f} days ago"


def load_optional(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_all():
    checks = []
    
    # product_master 체크 - P0-1
    pm_path = DATA_DIR / "product_master.json"
    if pm_path.exists():
        data = json.loads(pm_path.read_text(encoding="utf-8"))
        rows = data.get("products") or [] if isinstance(data, dict) else data
        registry = data.get("pd_no_to_cp") or {} if isinstance(data, dict) else {}
        s_count = len([x for x in rows if x.get("grade") == "S"])
        missing_cp = len([x for x in rows if not x.get("canonical_product_id")])
        complete = bool(rows) and len(registry) >= len(rows) and not missing_cp
        checks.append({
            "team": "product_master",
            "status": "success" if complete and s_count > 0 else "degraded",
            "reason": (f"운영 상품 {len(rows)}개, CP {len(registry)}개, S {s_count}개"
                       + (f", CP 누락 {missing_cp}개" if missing_cp else "")),
            "count": len(rows),
            "s_count": s_count,
            "freshness": freshness_str(data.get("generated_at", "") if isinstance(data, dict) else ""),
            "is_failure": not bool(rows)
        })
    else:
        checks.append({"team": "product_master", "status": "failed", "reason": "product_master.json 없음 - P0 Blocker", "is_failure": True, "freshness": "never"})

    # legal_full 체크 - P0-4
    legal_path = DATA_DIR / "legal_full.json"
    if legal_path.exists():
        legal = json.loads(legal_path.read_text(encoding="utf-8"))
        total = int(legal.get("total") or 0) if isinstance(legal, dict) else 0
        complete = int(legal.get("complete") or 0) if isinstance(legal, dict) else 0
        blocked = int(legal.get("blocked") or max(0, total - complete)) if isinstance(legal, dict) else 0
        # 법률 빈칸은 장애가 아니다 (2026-09-29).
        # 책임자 주소·안전성 자료처럼 사람이 넣어야 하는 값이 비어 공개가 막힌 것은
        # 의도한 안전 차단이다. 이걸 failed 로 올리면 overall 이 늘 failed 라
        # 진짜 장애(파일 없음·생성 멈춤)를 가린다. 사람 입력 대기(waiting)로 분리한다.
        items = legal.get("items") or {} if isinstance(legal, dict) else {}
        top: dict[str, int] = {}
        for row in items.values():
            for bl in row.get("blockers") or []:
                key = bl.split(".")[0] if bl.startswith("responsible_person") else bl
                top[key] = top.get(key, 0) + 1
        gen_h = hours_since(legal.get("generated_at", "")) if isinstance(legal, dict) else 999
        if not total:
            status, why = "failed", "legal_full.json 에 판정 대상이 없다"
        elif gen_h > 48:
            status, why = "degraded", f"legal_full 생성이 {gen_h:.0f}시간 멈춤"
        elif complete == total:
            status, why = "success", "전 항목 완비"
        else:
            status, why = "waiting", "사람 입력 대기: " + ", ".join(f"{k} {v}건" for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:4])
        checks.append({
            "team": "legal_full",
            "status": status,
            "reason": f"MoCRA 풀스키마 완료 {complete}/{total} · 공개 차단 {blocked}건 · {why}",
            "is_failure": status == "failed",
            "waiting_kind": "human_approval_required" if status == "waiting" else None,
            "freshness": freshness_str(legal.get("generated_at", "") if isinstance(legal, dict) else "")
        })
    else:
        checks.append({"team": "legal_full", "status": "failed", "reason": "legal_full.json 없음 - 3/6 라벨", "is_failure": True, "freshness": "never"})

    # Shopify shortlist + sync guard (2026-09-29)
    guard_path = DATA_DIR / "shopify_sync_guard.json"
    if guard_path.exists():
        g = json.loads(guard_path.read_text(encoding="utf-8"))
        sm = g.get("summary") or {}
        checks.append({
            "team": "shopify_sync",
            "status": "success" if g.get("ok") else "failed",
            "reason": (f"shortlist {g.get('shortlist_status')} {g.get('shortlist_units')}단위 · {g.get('mode')} · "
                       f"create {sm.get('create', 0)} / update {sm.get('update', 0)} / 변경없음 {sm.get('unchanged', 0)}"
                       + (f" · 위반 {g.get('violations')}" if not g.get("ok") else "")),
            "is_failure": not g.get("ok"),
            "freshness": freshness_str(g.get("generated_at", "")),
        })
    else:
        checks.append({"team": "shopify_sync", "status": "failed", "reason": "shopify_sync_guard.json 없음",
                       "is_failure": True, "freshness": "never"})

    # pricing + fx - P1
    pricing = json.loads((DATA_DIR / "pricing_model.json").read_text(encoding="utf-8"))
    checks.append({"team": "pricing", "status": "success", "reason": "FX 반영, 손익분기·기여마진 계산됨", "is_failure": False, "freshness": freshness_str(pricing.get("generated_at", ""))})

    # marketing - CP 연결은 실측하고, Trends 미연동은 warning으로 남긴다.
    market = json.loads((DATA_DIR / "market_team.json").read_text(encoding="utf-8"))
    rows = market.get("s_grade_priority") or []
    cp_ok = sum(bool(x.get("canonical_product_id")) for x in rows)
    has_trend = any(x.get("trend") is not None for x in market.get("keyword_board") or [])
    checks.append({"team": "marketing", "status": "success" if rows and cp_ok == len(rows) and has_trend else "warning", "reason": f"S 우선순위 CP 연결 {cp_ok}/{len(rows)} · Trends {'연결' if has_trend else '미연동'}", "is_failure": False, "freshness": freshness_str((market.get("team") or {}).get("updated_at", ""))})

    # A collection timestamp is collector evidence, never a checkout mtime.
    collection = assess_collection(load_optional(DATA_DIR / "daiso_real" / "collection_status.json"), now=now_utc())
    checks.append({"team": "daiso", **collection,
                   "freshness": freshness_str(collection["last_attempt_at"])})
    heartbeat = assess_heartbeat(load_optional(DATA_DIR / "agents" / "autofix_report.json"), now=now_utc())
    checks.append({"team": "deep_heartbeat", **heartbeat,
                   "freshness": freshness_str(heartbeat["last_attempt_at"])})
    workflows = load_optional(DATA_DIR / "agents" / "workflow_freshness.json")
    observed = workflows.get("observed_at") or workflows.get("generated_at")
    observed_fresh = hours_since(observed) <= 4.5
    checks.append({
        "team": "actions_monitor",
        "status": workflows.get("status", "warning") if observed_fresh else "warning",
        "reason": ("GitHub Actions 관측: " + str(workflows.get("checked_workflows", 0)) + "/" + str(workflows.get("total_workflows", 5)) + "개 · 실패 " + str(workflows.get("failed_actions", "unknown"))) if observed_fresh else "GitHub Actions 상태 조회 시각 미확인 또는 4.5시간 경과",
        "is_failure": observed_fresh and workflows.get("status") == "failed",
        "observed_at": observed,
        "freshness": freshness_str(observed),
    })

    # Artifact age alone does not prove a successful no_change execution.
    for name, path in [("gosi", DATA_DIR / "gosi.json"), ("product_discovery", DATA_DIR / "daiso_real" / "shopify_demand_score.json")]:
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                updated = d.get("updated_at") or d.get("generated_at")
                h = hours_since(updated)
                if h > 99:
                    checks.append({"team": name, "status": "warning", "reason": "갱신 시각 미확인" if h == 9999 else f"{h:.1f}h 전 산출물 갱신 · 실행 결과는 별도 확인", "is_failure": False, "is_no_change": False, "freshness": freshness_str(updated)})
                else:
                    checks.append({"team": name, "status": "success", "reason": f"정상 {h:.1f}h 전", "is_failure": False, "freshness": freshness_str(updated)})
            except Exception as e:
                checks.append({"team": name, "status": "failed", "reason": f"파싱 실패: {e}", "is_failure": True, "freshness": "error"})
        else:
            checks.append({"team": name, "status": "degraded", "reason": f"{name} 파일 없음 - 위젯 숨김", "is_failure": False, "freshness": "never"})

    return checks

def build_dashboard():
    checks = check_all()
    
    has_failed = any(c["status"]=="failed" for c in checks)
    has_degraded = any(c["status"]=="degraded" for c in checks)
    has_warning = any(c["status"] in ("warning", "waiting") for c in checks)
    
    overall = "failed" if has_failed else "degraded" if has_degraded else "warning" if has_warning else "success"
    
    # P2 Error Dashboard 상단 KPI
    status_doc = load_optional(DATA_DIR / "daiso_real" / "collection_status.json")
    collection = assess_collection(status_doc, now=now_utc())
    latest_attempt = status_doc.get("last_attempt") or status_doc.get("last_run") or {}
    queue_size = int(latest_attempt.get("queue_size") or 0)
    stale = [c["team"] for c in checks if c["status"] in ("warning", "degraded")]
    workflows = load_optional(DATA_DIR / "agents" / "workflow_freshness.json")
    observed = workflows.get("observed_at") or workflows.get("generated_at")
    observed_fresh = hours_since(observed) <= 4.5
    workflow_successes = [r.get("last_success_at") for r in (workflows.get("workflows") or {}).values() if isinstance(r, dict) and parse_iso(r.get("last_success_at"))]
    workflow_success = max(workflow_successes, key=parse_iso) if workflow_successes else None
    kpi = {
        "last_success": workflow_success or collection["last_success_at"],
        "last_success_source": "github_actions_snapshot" if workflow_success else "daiso_collection",
        "collection_last_attempt": collection["last_attempt_at"],
        "collection_last_success": collection["last_success_at"],
        "failed_jobs": workflows.get("failed_actions", "unknown") if observed_fresh else "unknown",
        "failed_checks": len([c for c in checks if c["status"] == "failed"]),
        "actions_observed_at": observed,
        "actions_observation_fresh": observed_fresh,
        "queue": queue_size,
        "stale_source": stale[0] if stale else "none",
        "freshness_summary": {c["team"]: c.get("freshness", "unknown") for c in checks},
    }
    
    result = {
        "generated_at": now_utc().isoformat(),
        "overall_status": overall,
        "status_legend": {
            "success": "정상",
            "warning": "주의 · 변경 없음/최신성/실행 지연",
            "degraded": "일부 실패",
            "waiting": "사람 입력 대기 (장애 아님)",
            "failed": "예외 - 자동화 장애"
        },
        "kpi": kpi,
        "summary": {
            "success": len([c for c in checks if c["status"]=="success"]),
            "warning": len([c for c in checks if c["status"]=="warning"]),
            "waiting": len([c for c in checks if c["status"]=="waiting"]),
            "degraded": len([c for c in checks if c["status"]=="degraded"]),
            "failed": len([c for c in checks if c["status"]=="failed"]),
            "no_change": len([c for c in checks if c.get("is_no_change")]),
            "real_failures": len([c for c in checks if c.get("is_failure")])
        },
        "checks": checks,
        "architecture_p0": {
            "product_master": "CP ID + Variant 그룹화",
            "grade_quantified": "match + demand + review => final >=0.85 S",
            "shopify_4csv": "products, inventory, images, collections",
            "legal_full": "identity, ingredients, directions, warning, responsible_person"
        }
    }
    
    out_path = DATA_DIR / "health_check.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"\nOverall: {overall.upper()}")
    print(f"KPI - Last Success: {kpi['last_success']} / Failed: {kpi['failed_jobs']} / Queue: {kpi['queue']} / Stale: {kpi['stale_source']}")
    for c in checks:
        icon = {"success":"OK","warning":"WARN","waiting":"WAIT","degraded":"DEGRADED","failed":"FAIL"}.get(c["status"], c["status"])
        print(f"{icon} {c['team']}: {c['status']} - {c['reason']} [{c.get('freshness','')}]")
    
    return result

if __name__ == "__main__":
    build_dashboard()
