"""Offline model-change preflight. Never calls providers or changes routing.

Input: {"cases": [{"id", "source", "holdout": true, "expected",
                   "baseline", "candidate", "baseline_ms", "candidate_ms",
                   "baseline_cost", "candidate_cost"}]}.
Use real, independently labelled cases; test fixtures are not business evidence.
"""
import argparse
import json
import math
from pathlib import Path


def equal(a, b):
    # JSON true and 1 must not compare equal in a typed decision contract.
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def evaluate(cases):
    if not isinstance(cases, list):
        raise ValueError("cases must be a list")
    errors, seen = [], set()
    for index, row in enumerate(cases):
        if not isinstance(row, dict):
            errors.append(f"row {index}: not an object")
            continue
        key = row.get("id")
        if not isinstance(key, str) or not key.strip() or key in seen:
            errors.append(f"row {index}: missing/duplicate id")
        else:
            seen.add(key)
        if not isinstance(row.get("source"), str) or not row["source"].strip():
            errors.append(f"row {index}: missing real-case source")
        if row.get("holdout") is not True:
            errors.append(f"row {index}: not held out from training")
        for field in ("expected", "baseline", "candidate"):
            if row.get(field) is None:
                errors.append(f"row {index}: missing {field}")
            else:
                try:
                    json.dumps(row[field], allow_nan=False)
                except (TypeError, ValueError):
                    errors.append(f"row {index}: invalid JSON {field}")
        for field in ("baseline_ms", "candidate_ms", "baseline_cost", "candidate_cost"):
            value = row.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                errors.append(f"row {index}: invalid {field}")
    if len(cases) < 30:
        errors.append("at least 30 real holdout cases required")
    result = {"cases": len(cases), "errors": errors, "eligible_for_review": False,
              "routing_changed": False, "provenance": "caller supplied; verify source labels independently"}
    if errors:
        return result
    n = len(cases)
    baseline = sum(equal(r["baseline"], r["expected"]) for r in cases) / n
    candidate = sum(equal(r["candidate"], r["expected"]) for r in cases) / n
    consistency = sum(equal(r["candidate"], r["baseline"]) for r in cases) / n
    result.update(baseline_accuracy=baseline, candidate_accuracy=candidate,
                  consistency=consistency,
                  regressions=[r["id"] for r in cases if equal(r["baseline"], r["expected"]) and not equal(r["candidate"], r["expected"])])
    for metric in ("ms", "cost"):
        before = sum(r[f"baseline_{metric}"] for r in cases)
        after = sum(r[f"candidate_{metric}"] for r in cases)
        result[f"baseline_total_{metric}"] = before
        result[f"candidate_total_{metric}"] = after
        result[f"{metric}_reduction_fraction"] = (before - after) / before if before else None
    # Video 3: stable identifiers and real-case comparison; video 4: same-input
    # output checks. Agreement with a wrong baseline is not sufficient.
    result["eligible_for_review"] = consistency == 1 and candidate == 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.input.read_text(encoding="utf-8-sig"))["cases"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["eligible_for_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
