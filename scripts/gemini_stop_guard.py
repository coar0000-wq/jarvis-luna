"""Read-only preflight for the existing gosi Gemini circuit policy.

No model/key exceptions, new stops, or canonical/history writes live here.
Expired stops are evaluated on a copy because assert_not_stopped mutates its
input when applying the existing cooldown policy.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import stat

from scripts.gosi_observation_history import ProviderStop, assert_not_stopped
from scripts.immutable_snapshot_store import MAX_BYTES
from scripts.moe_evaluation_history import safe_path


class GeminiStopStateError(RuntimeError):
    """Gemini cannot be contacted while the saved circuit state is unreadable."""


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate circuit document key")
        out[key] = value
    return out


def _invalid_constant(value):
    raise ValueError("non-JSON circuit document constant")


def _regular_state(info):
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
        raise ValueError("invalid circuit document file")


def _read_state(root):
    path = safe_path(root, "data/gosi.json")
    before = path.lstat()
    _regular_state(before)
    # A file swapped for a FIFO after lstat must not block open; a swapped
    # symlink must not be followed. Descriptor checks bind the bounded read.
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        _regular_state(opened)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(opened, key) for key in fields[:-1]):
            raise ValueError("circuit document changed before read")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(MAX_BYTES + 1)
        after = os.fstat(fd)
        final = safe_path(root, "data/gosi.json").lstat()
        _regular_state(after)
        _regular_state(final)
        # On Windows, path/fd ctime can mean creation/change time respectively.
        # Compare ctime within each API, and all other fields across both APIs.
        if any(getattr(opened, key) != getattr(after, key)
               or getattr(before, key) != getattr(final, key)
               or (key != "st_ctime_ns" and getattr(after, key) != getattr(final, key))
               for key in fields):
            raise ValueError("circuit document changed during read")
        if len(raw) > MAX_BYTES or len(raw) != after.st_size:
            raise ValueError("circuit document read size mismatch")
        return raw
    finally:
        os.close(fd)


def assert_gemini_not_stopped(root, *, now=None):
    """Re-read bounded saved state immediately before each Gemini request.

    Missing/malformed/unreadable state fails closed only at Gemini callers.
    Provider scope and expiry come exclusively from assert_not_stopped; absent,
    invalid or future stop timestamps remain active under that existing policy.
    """
    try:
        raw = _read_state(root)
        doc = json.loads(raw, object_pairs_hook=_unique_object,
                         parse_constant=_invalid_constant)
        if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
            raise ValueError("invalid circuit document")
        stops = doc.get("provider_stops", [])
        history = doc.get("provider_stop_history", [])
        if (not isinstance(stops, list) or not isinstance(history, list)
                or any(not isinstance(stop, dict) for stop in stops + history)):
            raise ValueError("invalid circuit state")
        for stop in stops:
            if (not isinstance(stop.get("provider"), str) or not stop["provider"].strip()
                    or ("category" in stop and not isinstance(stop["category"], str))
                    or ("code" in stop and type(stop["code"]) not in (str, int))):
                raise ValueError("invalid circuit scope")
        assert_not_stopped(deepcopy(doc), {"gemini"}, now=now)
    except ProviderStop:
        raise
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        raise GeminiStopStateError("gemini_persisted_stop_state_unavailable") from None
