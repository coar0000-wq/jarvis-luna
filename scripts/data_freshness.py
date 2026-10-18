"""Strict source timestamp assessment; never invent or repair observation times."""
from datetime import datetime, timezone


def parse_timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def assess_timestamp(value, now=None, max_age_hours=36):
    clock = now or datetime.now(timezone.utc)
    if isinstance(clock, str):
        clock = parse_timestamp(clock)
    if clock is None or clock.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    parsed = parse_timestamp(value)
    age = (clock - parsed).total_seconds() / 3600 if parsed else None
    status = ("invalid" if parsed is None else "future" if age < 0 else
              "stale" if age > max_age_hours else "fresh")
    return {"source_timestamp": value if isinstance(value, str) else None,
            "timestamp_input_type": type(value).__name__, "status": status,
            "age_hours": round(age, 4) if age is not None else None,
            "is_stale": status != "fresh", "max_age_hours": max_age_hours}
