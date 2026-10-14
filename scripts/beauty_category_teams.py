#!/usr/bin/env python3
"""Local analysis of dedicated category subteams. No research/human work is claimed.

Queues are proposals, never handoffs, approvals, or publication receipts.
Canonical teams and canonical demand grades are preserved unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import brain_plane
from datetime import datetime, timezone
from pathlib import Path

try:
    import gate_signature
except ModuleNotFoundError:
    from . import gate_signature

CANONICAL_TEAM_IDS = ("sourcing", "institutions", "market", "listing", "pricing",
                      "legal", "robotics", "design", "channels", "knowledge", "graph")
ROLES = ("sourcing", "market", "pricing", "listing", "legal", "design",
         "channels", "knowledge", "graph")
CATEGORIES = ("skincare", "makeup", "body")
INPUT_PATHS = {
    "category_config": "config/daiso_commerce_strategy.json",
    "demand_score": "data/daiso_real/shopify_demand_score.json",
    "registry": "data/shopify_daily_registry.json",
    "listing_gate": "data/listing_gate.json",
    "candidate_comparison": "data/daiso_real/candidate_comparison.json",
    "beauty_strategy": "data/beauty_price_strategy.json",
}


def _read(root, relative):
    if brain_plane.brain.current_execution(root) is not None:
        value = brain_plane.read_json(root / relative, root, None)
        return (value, None) if isinstance(value, dict) else ({}, "missing_or_unreadable")
    try:
        value = json.loads((root / relative).read_text(encoding="utf-8-sig"))
        return (value, None) if isinstance(value, dict) else ({}, "invalid_document")
    except (OSError, UnicodeError, ValueError):
        return {}, "missing_or_unreadable"


def _pd(row):
    value = row.get("pd_no")
    return str(value).strip() if value is not None else ""


def _rows(doc, key):
    value = doc.get(key, [])
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def _clock(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _gate_module(root):
    # Isolated root-bound copy; no mutation of shared gate_signature globals.
    spec = importlib.util.spec_from_file_location("_beauty_root_gate", gate_signature.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, value in vars(gate_signature).items():
        if isinstance(value, Path):
            try:
                setattr(mod, name, root / value.relative_to(gate_signature.ROOT))
            except ValueError:
                pass
    return mod


def _gate_freshness(root, gate, as_of):
    try:
        reason = _gate_module(root).stale_reason(gate)
        if reason:
            return False, reason
        age = (datetime.fromisoformat(as_of.replace("Z", "+00:00")) -
               datetime.fromisoformat(_clock(gate.get("generated_at")).replace("Z", "+00:00"))).total_seconds()
        if age < 0 or age > 86400:
            return False, "gate_timestamp_future_or_older_than_24h"
        return True, None
    except Exception as exc:
        return False, "gate_signature_or_timestamp_unavailable:" + type(exc).__name__


def _registry_ids(value):
    """History, deleted entries and in-doubt attempts all prevent duplicates."""
    result = set()
    if isinstance(value, dict):
        if _pd(value):
            result.add(_pd(value))
        for key, child in value.items():
            if isinstance(child, dict) and str(key).isdigit():
                result.add(str(key))
            if isinstance(child, (dict, list)):
                result.update(_registry_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_registry_ids(child))
    return result


def _index(rows):
    result = {}
    for row in rows:
        if _pd(row):
            result.setdefault(_pd(row), []).append(row)
    return result


def _task(tag, pd, role, kind, requirement):
    return {"task_id": f"beauty:{tag}:{pd}:{kind}", "pd_no": pd,
            "category_tag": tag, "owner_team_id": role, "kind": kind,
            "status": "source_research_required", "requirement": requirement,
            "executed_at": None, "handoff_receipt": None, "approval_receipt": None}


def build(root, as_of):
    """Deterministic read-only payload; as_of is the caller's analysis execution clock."""
    root = Path(root).resolve()
    executed = _clock(as_of)
    docs, coverage = {}, {}
    for key, relative in INPUT_PATHS.items():
        docs[key], error = _read(root, relative)
        coverage[key] = {"path": relative, "loaded": error is None, "error": error,
                         "source_observed_at": docs[key].get("source_observed_at"),
                         "document_generated_at": docs[key].get("generated_at") or docs[key].get("as_of"),
                         "semantic_sha256": hashlib.sha256(json.dumps(docs[key], sort_keys=True, ensure_ascii=False,
                                                                      separators=(",", ":")).encode("utf-8")).hexdigest() if error is None else None}
    mapping = {}
    for entry in _rows(docs["category_config"], "categories"):
        tag = entry.get("tag")
        if tag in CATEGORIES:
            for bucket in entry.get("score_buckets", []):
                mapping.setdefault(str(bucket), set()).add(tag)
            mapping.setdefault(tag, set()).add(tag)

    def category(row):
        # Official desk membership is authoritative; a broad legacy bucket
        # must not reroute makeup/body into skincare or fill an unknown desk.
        if "desk" in row:
            return row["desk"] if row["desk"] in CATEGORIES else None
        # No name guessing or advisory strategy/comparison grade promotion.
        key = row.get("bucket") or row.get("category_tag") or row.get("category") or ""
        tags = mapping.get(str(key), set())
        return next(iter(tags)) if len(tags) == 1 else None

    registry = _registry_ids(docs["registry"])
    canonical = _index(_rows(docs["demand_score"], "all_scored"))
    candidates = _index(_rows(docs["candidate_comparison"], "items"))
    strategies = _index(_rows(docs["beauty_strategy"], "products"))
    gates = _index(_rows(docs["listing_gate"], "items"))
    fresh, reason = _gate_freshness(root, docs["listing_gate"], executed)
    teams = {tag: {"subteam_id": "beauty_" + tag, "category_tag": tag,
                   "status": "analysis_complete", "analysis_executed_at": executed,
                   "work_status": "source_research_required", "S_only": True,
                   "allowed_grades": ["S"], "lower_grade_fallback": False,
                   "owned_pd_nos": [], "role_assignments": {r: r for r in ROLES},
                   "secretary_oversight": {"role": "secretary", "status": "oversight_required",
                                            "reviewed_at": None, "receipt": None},
                   "registration_queue": [], "source_research_queue": [],
                   "evidence_tasks": [], "skipped_registered_pd_nos": [],
                   "canonical_s_count": 0} for tag in CATEGORIES}
    rejected = []
    for pd in sorted(set(canonical) | set(candidates)):
        rows, comparison = canonical.get(pd, []), candidates.get(pd, [])
        row = rows[0] if rows else comparison[0]
        tag = category(row)
        if tag is None:
            rejected.append({"pd_no": pd, "reason": "category_missing_ambiguous_or_out_of_scope"})
            continue
        team = teams[tag]
        conflict = bool(rows and any(category(r) != tag or r.get("grade") != row.get("grade") for r in rows))
        is_s = bool(rows and row.get("grade") == "S" and not conflict)
        if is_s:
            team["canonical_s_count"] += 1
        if pd in registry:
            team["skipped_registered_pd_nos"].append(pd)
            continue
        team["owned_pd_nos"].append(pd)
        strategy = strategies.get(pd, [{}])[0]
        gate_rows = gates.get(pd, [])
        gate = gate_rows[0] if len(gate_rows) == 1 else {}
        blockers = []
        if not coverage["registry"]["loaded"]:
            blockers.append("registry_unavailable")
        if not fresh:
            blockers.append("fresh_gate_required")
        if not gate:
            blockers.append("unique_product_gate_required")
        if gate.get("ready") is not True or gate.get("public_ready") is not True:
            blockers.append("listing_gate_not_ready")
        for key in ("blocked_by", "agent_blocked_by", "public_blocked_by"):
            blockers.extend(str(x) for x in (gate.get(key) or []))
        if (gate.get("legal") or {}).get("hard_block") is True:
            blockers.append("legal_hard_block")
        try:
            safety = gate_signature.manufacturer_safety.public_view(
                gate_signature.manufacturer_safety.manufacturer_safety_record(pd, root))
        except Exception:
            safety = {"covered": False, "reason": "current_safety_evidence_unavailable"}
        if (gate.get("manufacturer_safety_record") or {}).get("covered") is not True or safety.get("covered") is not True:
            blockers.append("manufacturer_safety_record_required")
        if gate.get("legal_full_complete") is not True:
            blockers.append("legal_full_required")
        if (gate.get("price") or {}).get("price_evidence_ok") is not True:
            blockers.append("price_evidence_required")
        if (gate.get("price") or {}).get("register_blocked") is True:
            blockers.append("price_evidence_blocked")
        if conflict:
            blockers.append("conflicting_canonical_rows")
        if not is_s:
            blockers.append("canonical_S_required")
        blockers = sorted(set(blockers))
        item = {"pd_no": pd, "category_tag": tag,
                "canonical_grade": row.get("grade") if rows else None,
                "canonical_source": INPUT_PATHS["demand_score"] if rows else None,
                "comparison_grade": (comparison[0].get("score") or {}).get("grade") if comparison else None,
                "S_only": True, "eligible_for_registration": is_s and not blockers,
                "requires_live_revalidation": True, "blockers": blockers,
                "analysis_executed_at": executed,
                "source_observed_at": row.get("source_observed_at") or row.get("collected_at"),
                "source_url": row.get("url") or row.get("source_url"),
                "registration_executed_at": None, "publish_executed_at": None,
                "actual_sales": {"status": "UNKNOWN", "orders": None, "units": None,
                                 "reason": "No product-level transaction evidence consumed by this analysis"},
                "price_position": strategy.get("price_position") or {"status": "unknown"},
                "profitability_warnings": strategy.get("profitability_risk") or {},
                "manufacturer_safety": {"status": "not_verified_by_this_analysis",
                                        "gate_record_covered": (gate.get("manufacturer_safety_record") or {}).get("covered"),
                                        "current_record_covered": safety.get("covered"),
                                        "current_record_reason": safety.get("reason")}}
        team["registration_queue" if is_s else "source_research_queue"].append(item)
        tasks = team["evidence_tasks"]
        if not is_s:
            tasks.append(_task(tag, pd, "sourcing", "canonical_source_research",
                               "Collect exact product demand evidence; comparison/A/B/C never substitutes for canonical S."))
        if not fresh or not gate:
            tasks.append(_task(tag, pd, "listing", "fresh_gate",
                               "Rebuild listing_gate from current signed inputs and revalidate before registration."))
        for blocker in blockers:
            if blocker in {"fresh_gate_required", "unique_product_gate_required", "canonical_S_required"}:
                continue
            role = "legal" if any(x in blocker for x in ("legal", "label", "gosi", "manufacturer", "claims")) else "pricing" if "price" in blocker else "listing"
            tasks.append(_task(tag, pd, role, "resolve_" + blocker, "Resolve exact product evidence blocker: " + blocker))
        if (strategy.get("price_position") or {}).get("verified") is not True:
            tasks.append(_task(tag, pd, "pricing", "comparable_price_evidence",
                               "Collect dated exact-item, same-volume seller price and shipping evidence; unknown is not lowest."))
        tasks.append(_task(tag, pd, "market", "actual_sales_evidence",
                           "Obtain product-level orders/units and observation window; reviews, similarity and registry do not prove sales."))
        if is_s:
            tasks.append(_task(tag, pd, "sourcing", "stock_and_identity_evidence",
                               "Recheck exact PD identity and current stock before registration; analysis is not a live stock observation."))
        tasks.append(_task(tag, pd, "design", "image_evidence",
                           "Record exact-product image source, usage permission and actual listing asset inspection; do not claim review execution."))
        tasks.append(_task(tag, pd, "channels", "publication_evidence",
                           "After authorized execution, obtain Shopify ID and channel/publication receipt; proposed listing is not published."))
        tasks.append(_task(tag, pd, "knowledge", "source_provenance",
                           "Link source timestamp and URL separately from local analysis and publication receipts."))
        tasks.append(_task(tag, pd, "graph", "category_evidence_links",
                           "Link this PD to its dedicated category, evidence tasks and canonical shared-role owners."))
    for team in teams.values():
        team["eligible_pd_nos"] = [x["pd_no"] for x in team["registration_queue"] if x["eligible_for_registration"]]
        team["s_zero"] = team["canonical_s_count"] == 0
        team["counts"] = {"registration": len(team["registration_queue"]), "eligible": len(team["eligible_pd_nos"]),
                          "source_research": len(team["source_research_queue"]), "evidence_tasks": len(team["evidence_tasks"])}
        team["analysis_proof"] = {"operation": "local_category_queue_analysis", "executed_at": executed,
                                  "clock_source": "caller_supplied_as_of", "analyzed_pd_nos": team["owned_pd_nos"],
                                  "skipped_registered_pd_nos": team["skipped_registered_pd_nos"],
                                  "input_sha256": {k: v["semantic_sha256"] for k, v in coverage.items()},
                                  "research_executed": False, "human_activity_verified": False,
                                  "output_counts": dict(team["counts"])}
    return {"schema_version": 1, "generator": "scripts/beauty_category_teams.py",
            "status": "analysis_complete", "analysis_executed_at": executed,
            "canonical_team_ids": list(CANONICAL_TEAM_IDS), "subteams": teams,
            "input_coverage": coverage, "fresh_gate_required": True,
            "gate_freshness": {"current": fresh, "reason": reason}, "excluded": rejected,
            "policy": {"network_calls": False, "paid_api_called": False, "human_work_claimed": False,
                       "handoffs_executed": False, "approvals_granted": False,
                       "registration_executed": False, "publication_executed": False, "grade_changes": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--write", action="store_true", help="Write only data/agents/beauty_category_teams.json")
    args = parser.parse_args(argv)
    payload = build(args.root, args.as_of or datetime.now(timezone.utc).isoformat())
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.write:
        destination = args.root / "data/agents/beauty_category_teams.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
