#!/usr/bin/env python3
"""Pure offline freshness assessments. No filesystem/network/persistence effects.

All timestamp arithmetic is UTC. Offset-aware ISO timestamps are normalized;
legacy naive timestamps (including naive now) mean UTC, never local time.
Date-only strings, invalid times and observations >5 minutes in the future
cannot prove freshness. Smaller clock skew is accepted with age zero.
Returned times are verified UTC ISO strings, never synthesized from mtimes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re

UTC = timezone.utc
_FUTURE_SKEW = timedelta(minutes=5)
_PROTECTED = {"disabled", "error", "failed", "blocked"}
_FAILURE = {"failed", "error", "blocked"}
_OLD_PREFIX = re.compile(r"^(?:\d{4}-\d{2}-\d{2} 이후 갱신 없음 \([0-9]+(?:\.[0-9]+)?일\)\.\s*)+")


def _parse(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if "T" not in text and " " not in text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError):
            return None
    else:
        return None
    try:
        return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _clock(now):
    if now is None:
        return datetime.now(UTC)
    parsed = _parse(now)
    if parsed is None:
        raise ValueError("now must be a datetime or an ISO timestamp")
    return parsed


def _limit(value, name):
    if isinstance(value, bool):
        raise ValueError(name + " must be a finite non-negative number")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(name + " must be a finite non-negative number") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(name + " must be a finite non-negative number")
    return number


def _observation(value, now):
    parsed = _parse(value)
    if parsed is None:
        return None, None, "missing" if value is None or value == "" else "invalid"
    if parsed - now > _FUTURE_SKEW:
        return None, None, "future"
    return parsed, max(0.0, (now - parsed).total_seconds() / 3600), None


def _iso(value):
    return value.isoformat() if value is not None else None


def _age(value):
    return round(value, 3) if value is not None else None


def _status(record):
    return str(record.get("status") or "").strip().lower()


def _source_reason(value):
    return _OLD_PREFIX.sub("", str(value or "").strip()).strip()


def age_channels(gcs, now=None, stale_hours=48):
    """Return an independent map with idempotent, reversible freshness overlays.

    source_* fields preserve the original state and are authoritative. A writer
    updating an already aged row should update source_* with collected_at.
    Legacy stale/unverified states without source_* cannot be safely inferred;
    those remain their own source states until a writer supplies a new state.
    Missing/invalid time cannot retain verified trust; failures stay visible.
    """
    clock, limit = _clock(now), _limit(stale_hours, "stale_hours")
    if not isinstance(gcs, dict):
        return deepcopy(gcs)
    out = deepcopy(gcs)
    for meta in out.values():
        if not isinstance(meta, dict):
            continue
        source_status = meta.get("source_status", meta.get("status"))
        source_trust = meta.get("source_trust", meta.get("trust"))
        source_reason = _source_reason(meta.get("source_reason", meta.get("reason")))
        meta.update(source_status=source_status, source_trust=source_trust,
                    source_reason=source_reason)
        collected, age, problem = _observation(meta.get("collected_at"), clock)
        meta["age_hours"] = _age(age)
        meta["stale"] = age > limit if age is not None else None
        protected = str(source_status or "").lower() in _PROTECTED
        if problem:
            meta["status"] = source_status if protected else "unverified"
            meta["trust"] = "unverified"
            freshness = "collected_at " + problem + ": 최신성 검증 불가."
        elif age > limit:
            meta["status"] = source_status if protected else "stale"
            meta["trust"] = "stale" if source_trust == "verified" else source_trust
            freshness = f"{collected.date().isoformat()} 이후 갱신 없음 ({age / 24:.1f}일)."
        else:
            meta["status"], meta["trust"] = source_status, source_trust
            freshness = ""
        meta["freshness_reason"] = freshness
        meta["reason"] = " ".join(part for part in (freshness, source_reason) if part)
    return out


def _record_time(record):
    # An invalid completion cannot be rescued by a valid start time.
    # A start-only legacy record is still an actual attempt.
    for key in ("finished_at", "completed_at", "started_at", "at", "timestamp"):
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _positive_ok(record):
    value = record.get("ok")
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def _zero_ok(record):
    value = record.get("ok")
    if isinstance(value, bool) or value is None:
        return False
    try:
        return float(value) == 0
    except (TypeError, ValueError, OverflowError):
        return False


def _is_success(record):
    return _status(record) == "ok" and _positive_ok(record) and not record.get("is_no_change")


def _record(doc, primary, fallback=None):
    # Explicit malformed/empty new fields do not silently borrow legacy data.
    value = doc.get(primary) if primary in doc else doc.get(fallback)
    return value if isinstance(value, dict) else {}


def assess_collection(doc, now=None, stale_after_hours=36):
    """Separate latest attempt from last new-product success.

    last_attempt is authoritative if present, else legacy last_run. last_success
    must be status=ok && ok>0; when absent only legacy last_run can supply it.
    no_change never advances success. Failure wins over age. Fresh no_change
    is warning even when product success is old/missing. Unknown is not success.
    """
    clock, limit = _clock(now), _limit(stale_after_hours, "stale_after_hours")
    doc = doc if isinstance(doc, dict) else {}
    attempt = _record(doc, "last_attempt", "last_run")
    candidate = _record(doc, "last_success", "last_run")
    success = candidate if _is_success(candidate) else {}
    attempt_dt, attempt_age, attempt_problem = _observation(_record_time(attempt), clock)
    success_dt, success_age, _ = _observation(_record_time(success), clock)
    last_status = _status(attempt) or None
    is_failure = last_status in _FAILURE
    is_no_change = (last_status == "no_change" or
                    last_status == "ok" and _zero_ok(attempt) or
                    last_status == "ok" and bool(attempt.get("is_no_change")))
    attempt_stale = attempt_age is None or attempt_age > limit
    data_stale = success_age is None or success_age > limit
    detail = str(attempt.get("failure_reason") or attempt.get("reason") or "").strip()
    if is_failure:
        status, reason = "failed", f"최신 수집 시도 실패 ({last_status})"
        if detail:
            reason += ": " + detail
    elif attempt_problem:
        status, reason = "degraded", "수집 시도 시각 " + attempt_problem + ": 최신성 검증 불가"
    elif attempt_stale:
        status, reason = "degraded", f"수집 시도 {attempt_age:.1f}시간 경과"
    elif is_no_change:
        status, reason = "warning", "수집 정상 완료: 새 상품 없음"
    elif _is_success(attempt):
        status, reason = "success", "최근 수집 정상 완료: 새 상품 있음"
    else:
        status, reason = "degraded", f"수집 시도 상태 검증 불가 ({last_status or 'missing'})"
    if data_stale:
        reason += " · 새 상품 성공 데이터 오래됨 또는 검증 불가"
    return {
        "status": status, "reason": reason,
        "last_attempt_at": _iso(attempt_dt), "last_success_at": _iso(success_dt),
        "last_attempt_status": last_status,
        "attempt_age_hours": _age(attempt_age), "success_age_hours": _age(success_age),
        "data_stale": data_stale, "attempt_stale": attempt_stale,
        "is_no_change": bool(is_no_change), "is_failure": is_failure,
    }


def assess_heartbeat(report, now=None, interval_hours=2, grace_hours=4.5):
    """Assess only SafeAutoFix report.generated_at, never derived mtimes.

    grace_hours is total maximum age from generated_at, not added to interval.
    Healthy means status ok/success; disabled/warning/unknown stay warning.
    """
    clock = _clock(now)
    interval = _limit(interval_hours, "interval_hours")
    grace = _limit(grace_hours, "grace_hours")
    report = report if isinstance(report, dict) else {}
    attempted, age, problem = _observation(report.get("generated_at"), clock)
    raw_status = _status(report)
    is_failure = raw_status in _FAILURE
    delayed = age is None or age > grace
    if is_failure:
        status, reason = "failed", f"SafeAutoFix 실행 실패 ({raw_status})"
    elif problem:
        status, reason = "warning", "SafeAutoFix generated_at " + problem + ": 실행 시각 검증 불가"
    elif delayed:
        status, reason = "warning", f"SafeAutoFix heartbeat 지연 ({age:.1f}시간)"
    elif raw_status in {"ok", "success"}:
        status, reason = "success", "SafeAutoFix heartbeat 정상"
    else:
        status, reason = "warning", f"SafeAutoFix 상태 검증 필요 ({raw_status or 'missing'})"
    try:
        next_expected = attempted + timedelta(hours=interval) if attempted else None
        deadline = attempted + timedelta(hours=grace) if attempted else None
    except OverflowError:
        next_expected, deadline = None, None
    return {
        "status": status, "reason": reason, "last_attempt_at": _iso(attempted),
        "age_hours": _age(age), "next_expected_at": _iso(next_expected),
        "grace_deadline_at": _iso(deadline), "is_failure": is_failure,
        "delayed": delayed,
    }
