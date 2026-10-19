"""Exact archival evidence for a team's regenerated learning projections.

History is not a task queue, adoption record, measured result, or approval.
The current action/items remain faithful projections of the reviewed sources.
"""
from copy import deepcopy
import hashlib
import json

MEANING = "historical_review_projection_not_current_goal_or_approval"
FIELDS = ("this_week_action", "items")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def projections(team):
    action, items = team.get("this_week_action"), team.get("items", [])
    if action is not None and not isinstance(action, dict):
        raise ValueError("team learning action must be an object or null")
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise ValueError("team learning items must be a list of objects")
    return ([action] if action is not None else []) + items


def history_rows(team):
    rows = team.get("projection_history", [])
    if not isinstance(rows, list):
        raise ValueError("team learning projection history must be a list")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"id", "meaning", "snapshot"}
                or row["meaning"] != MEANING or not isinstance(row["snapshot"], dict)
                or row["id"] != fingerprint(row["snapshot"]) or row["id"] in seen):
            raise ValueError("invalid team learning historical projection")
        seen.add(row["id"])
    return rows


def preserve(previous, current):
    """Archive exact old and current projections once, without modifying either."""
    rows = deepcopy(history_rows(previous))
    seen = {row["id"] for row in rows}
    for snapshot in projections(previous) + projections(current):
        key = fingerprint(snapshot)
        if key not in seen:
            rows.append({"id": key, "meaning": MEANING, "snapshot": deepcopy(snapshot)})
            seen.add(key)
    return rows


def verify(previous, current):
    """Reject loss, mutation, malformed evidence, or missing prior projections."""
    old_rows, rows = history_rows(previous), history_rows(current)
    # Preserve insertion order as well as every byte-equivalent JSON value.
    if fingerprint(rows[:len(old_rows)]) != fingerprint(old_rows):
        raise ValueError("team learning projection history is not append-only")
    archived = {row["id"]: row["snapshot"] for row in rows}
    for snapshot in projections(previous) + projections(current):
        if fingerprint(archived.get(fingerprint(snapshot))) != fingerprint(snapshot):
            raise ValueError("team learning projection missing exact historical snapshot")

    if fingerprint(rows) != fingerprint(preserve(previous, current)):
        raise ValueError("team learning history contains ungrounded snapshots")


def verify_document(previous, current, expected=None):
    old_teams, teams = previous.get("teams"), current.get("teams")
    if (not isinstance(old_teams, dict) or not isinstance(teams, dict)
            or set(old_teams) != set(teams)):
        raise ValueError("team learning team set changed")
    for team in old_teams:
        if not isinstance(old_teams[team], dict) or not isinstance(teams[team], dict):
            raise ValueError("team learning team must remain an object")
        verify(old_teams[team], teams[team])
        if expected is not None and (team not in expected or any(
                k not in teams[team] or fingerprint(teams[team][k]) != fingerprint(v) for k, v in expected[team].items())):
            raise ValueError("team learning projection differs from reviewed sources")
