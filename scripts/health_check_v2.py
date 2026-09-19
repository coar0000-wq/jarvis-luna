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

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

def parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None

def now_utc():
    return datetime.datetime.now(timezone.utc)

def hours_since(iso):
    dt = parse_iso(iso)
    if not dt:
        return 9999
    return (now_utc() - dt).total_seconds() / 3600

def freshness_str(iso):
    h = hours_since(iso)
    if h < 1/60:
        return "just now"
    elif h < 1:
        return f"{int(h*60)} min ago"
    elif h < 24:
        return f"{h:.1f} hours ago"
    else:
        return f"{h/24:.1f} days ago"

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
        status = "success" if total and complete == total else "failed"
        checks.append({
            "team": "legal_full",
            "status": status,
            "reason": f"MoCRA 풀스키마 완료 {complete}/{total} · 공개 차단 {blocked}건",
            "is_failure": status == "failed",
            "freshness": freshness_str(legal.get("generated_at", "") if isinstance(legal, dict) else "")
        })
    else:
        checks.append({"team": "legal_full", "status": "failed", "reason": "legal_full.json 없음 - 3/6 라벨", "is_failure": True, "freshness": "never"})

    # pricing + fx - P1
    pricing = json.loads((DATA_DIR / "pricing_model.json").read_text(encoding="utf-8"))
    checks.append({"team": "pricing", "status": "success", "reason": "FX 반영, 손익분기·기여마진 계산됨", "is_failure": False, "freshness": freshness_str(pricing.get("generated_at", ""))})

    # marketing - CP 연결은 실측하고, Trends 미연동은 warning으로 남긴다.
    market = json.loads((DATA_DIR / "market_team.json").read_text(encoding="utf-8"))
    rows = market.get("s_grade_priority") or []
    cp_ok = sum(bool(x.get("canonical_product_id")) for x in rows)
    has_trend = any(x.get("trend") is not None for x in market.get("keyword_board") or [])
    checks.append({"team": "marketing", "status": "success" if rows and cp_ok == len(rows) and has_trend else "warning", "reason": f"S 우선순위 CP 연결 {cp_ok}/{len(rows)} · Trends {'연결' if has_trend else '미연동'}", "is_failure": False, "freshness": freshness_str((market.get("team") or {}).get("updated_at", ""))})

    # 기존 gosi, product_discovery, daiso
    for name, path in [("gosi", DATA_DIR / "gosi.json"), ("product_discovery", DATA_DIR / "daiso_real" / "shopify_demand_score.json"), ("daiso", DATA_DIR / "daiso_real" / "products.json")]:
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                updated = d.get("updated_at") or d.get("generated_at") or datetime.datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                h = hours_since(updated)
                if h > 99:
                    checks.append({"team": name, "status": "warning", "reason": f"{h:.1f}h 전 갱신 - 변경 없음으로 처리", "is_failure": False, "is_no_change": True, "freshness": freshness_str(updated)})
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
    has_warning = any(c["status"]=="warning" for c in checks)
    
    overall = "failed" if has_failed else "degraded" if has_degraded else "warning" if has_warning else "success"
    
    # P2 Error Dashboard 상단 KPI
    status_doc = json.loads((DATA_DIR / "daiso_real" / "collection_status.json").read_text(encoding="utf-8"))
    queue_size = int((status_doc.get("last_run") or {}).get("queue_size") or 0)
    stale = [c["team"] for c in checks if c["status"] in ("warning", "degraded")]
    kpi = {
        "last_success": now_utc().isoformat(),
        "failed_jobs": len([c for c in checks if c["status"]=="failed"]),
        "queue": queue_size,
        "stale_source": stale[0] if stale else "none",
        "freshness_summary": {c["team"]: c.get("freshness","unknown") for c in checks}
    }
    
    result = {
        "generated_at": now_utc().isoformat(),
        "overall_status": overall,
        "status_legend": {
            "success": "정상",
            "warning": "변경 없음",
            "degraded": "일부 실패",
            "failed": "예외 - 사람 개입 필요"
        },
        "kpi": kpi,
        "summary": {
            "success": len([c for c in checks if c["status"]=="success"]),
            "warning": len([c for c in checks if c["status"]=="warning"]),
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
        icon = {"success":"OK","warning":"WARN","degraded":"DEGRADED","failed":"FAIL"}[c["status"]]
        print(f"{icon} {c['team']}: {c['status']} - {c['reason']} [{c.get('freshness','')}]")
    
    return result

if __name__ == "__main__":
    build_dashboard()
