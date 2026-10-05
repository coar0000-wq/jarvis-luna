#!/usr/bin/env python3
"""Bounded public GET observations. Never imports/runs the operating collector.

Only SearchGoods JSON objects with a direct exact pdNo and direct actual price
are accepted. HTML, nested prices, stock, inferred and search-window prices are
not evidence. All network dependencies are private; tests patch them internally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.daisomall.co.kr"
SEARCH = "/ssn/search/SearchGoods"
UA = "JarvisShortlistObserver/1.0"
OUTPUT = "data/daiso_real/shortlist_observations.json"
LEDGER = "data/daiso_real/.shortlist_observation_claim.json"
INPUTS = (
    "data/product_master.json", "data/daiso_real/products.json",
    "data/daiso_real/collection_status.json", "data/daiso_real/shopify_s_recommendations.json",
    "data/shopify_shortlist.json", "data/listing_gate.json", "data/legal_full.json",
    "data/legal_products.json", "data/pricing_model.json", "data/mocra_readiness.json",
    "data/shopify_listing_copy.json", "data/shopify_action_queue.json",
    "data/daiso_real/candidate_pool.json", "data/daiso_real/candidate_observations.json",
)
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
FRESH_TTL = 24 * 3600
COOLDOWN = 2 * 3600
POLICY = {"version": 2, "fresh_ttl_seconds": FRESH_TTL,
          "retry_cooldown_seconds": COOLDOWN, "per_run_http_cap": 12,
          "rolling_window_seconds": 24 * 3600, "rolling_http_cap": 24,
          "run_deadline_seconds": 660, "safety_margin_seconds": 30,
          "http_envelope_seconds": 2 * TIMEOUT}
TRANSIENT = {500, 502, 503, 504}
PRICE_KEYS = ("sellAmt", "salePrice", "sellingPrice", "sellPrice", "goodsPrice", "productPrice", "salePrc", "pdPrc", "price", "price_krw", "sale_price", "selling_price", "sell_price", "goods_price", "product_price")


class Blocked(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _epoch(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return None
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _safe(root, relative=""):
    p = root / relative
    for component in (root, *root.parents, *p.relative_to(root).parts):
        # Inspect each actual ancestor, including Windows junction/reparse points.
        if isinstance(component, Path):
            q = component
        else:
            continue
        s = q.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
            raise Blocked("symlink_or_reparse_path")
    q = root
    for part in Path(relative).parts:
        if part in {"..", "."}:
            raise Blocked("path_traversal")
        q = q / part
        if q.exists() or q.is_symlink():
            s = q.lstat()
            if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
                raise Blocked("symlink_or_reparse_path")
    return p


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read(root, relative):
    return json.loads(_safe(root, relative).read_bytes(), object_pairs_hook=_unique_object)


def _hashes(root):
    # Fixed public operating files only. Never enumerate data directories or
    # inspect manual identity/contact/credential data.
    result = {}
    for rel in INPUTS:
        p = _safe(root, rel)
        if not p.exists():
            result[rel] = "missing"
        elif not p.is_file():
            raise Blocked("operating_input_not_regular_file")
        else:
            result[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def _atomic(root, relative, document):
    target = _safe(root, relative)
    temp = _safe(root, str(Path(relative).parent / ("." + target.name + "." + os.urandom(8).hex())))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        _safe(root, relative)
        os.replace(temp, target)
        if os.name != "nt":
            dfd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if temp.exists():
            temp.unlink()


class _Claim:
    """OS lock plus fixed atomically fsynced durable ledger; no lock-file output."""
    def __init__(self, root):
        self.root = root
        self.path = _safe(root, LEDGER)
        self.handle = None
        self.acquired = False

    def __enter__(self):
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                self.kernel.CreateMutexW.restype = wintypes.HANDLE
                self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
                self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                name = "Local\\JarvisShortlist_" + hashlib.sha256(str(self.root).casefold().encode()).hexdigest()
                self.handle = self.kernel.CreateMutexW(None, False, name)
                if not self.handle or self.kernel.WaitForSingleObject(self.handle, 0) not in (0, 0x80):
                    raise Blocked("claim_locked")
            else:
                import fcntl
                self.handle = os.open(_safe(self.root, "data/daiso_real"), os.O_RDONLY)
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
            if not self.path.exists():
                raise Blocked("durable_claim_missing_no_bootstrap")
            self.data = _read(self.root, LEDGER)
            if not isinstance(self.data, dict):
                raise Blocked("invalid_claim_ledger")
            counter = self.data.get("total_http_attempts")
            if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
                raise Blocked("invalid_claim_counter")
            for key in ("last_run_attempt_at", "last_request_at"):
                value = _epoch(self.data.get(key))
                if value is None or value > time.time():
                    raise Blocked("invalid_claim_clock")
            if _epoch(self.data["last_request_at"]) < _epoch(self.data["last_run_attempt_at"]):
                raise Blocked("invalid_claim_clock_order")
            return self
        except Exception as exc:
            self.__exit__()
            raise Blocked("claim_locked_or_invalid") from exc

    def save(self):
        _atomic(self.root, LEDGER, self.data)

    def __exit__(self, *args):
        if self.handle is not None:
            if os.name == "nt":
                if self.acquired:
                    self.kernel.ReleaseMutex(self.handle)
                self.kernel.CloseHandle(self.handle)
            else:
                os.close(self.handle)
            self.handle = None


def _url_ok(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.netloc != "www.daisomall.co.kr" or u.username or u.password or u.fragment:
        raise Blocked("unsafe_url")
    if u.path == "/robots.txt" and not u.query:
        return
    if u.path != SEARCH:
        raise Blocked("unsafe_path")
    args = urllib.parse.parse_qs(u.query, strict_parsing=True)
    if set(args) != {"searchTerm"} or len(args["searchTerm"]) != 1 or not re.fullmatch(r"[0-9]+", args["searchTerm"][0]):
        raise Blocked("unsafe_query")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject all redirects, including same-host: no unchecked URL is fetched.
        _url_ok(newurl)
        raise Blocked("redirect_not_followed")


def _http_get(url):
    _url_ok(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/plain", "Accept-Encoding": "identity"}, method="GET")
    started = time.monotonic()
    try:
        response = opener.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        _url_ok(response.geturl())
        chunks, size = [], 0
        while True:
            if time.monotonic() - started > TIMEOUT:
                raise TimeoutError("response_timeout")
            # read1 performs at most one buffered/raw read, so slow trickles
            # cannot hold read(size) indefinitely while resetting socket timeout.
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise Blocked("response_too_large")
        return response.code, b"".join(chunks)


def _numeric(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 1000000 and value == int(value):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value) and int(value) <= 1000000:
        return int(value)
    return None


def _parse(body, pd_no):
    try:
        payload = json.loads(body, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        return None
    found = []
    stack = [payload]
    while stack:
        obj = stack.pop()
        if isinstance(obj, list):
            stack.extend(obj)
        elif isinstance(obj, dict):
            stack.extend(v for v in obj.values() if isinstance(v, (dict, list)))
            # A direct pdNo is mandatory; URL mentions/SKU guesses never qualify.
            if "pdNo" not in obj or isinstance(obj["pdNo"], bool) or str(obj["pdNo"]) != pd_no:
                continue
            identities = [str(obj[k]) for k in ("pdNo", "pd_no", "productId", "goodsNo") if k in obj]
            if any(v != pd_no for v in identities):
                return None
            allowed = {k.lower() for k in PRICE_KEYS}
            prices = [(k, _numeric(v)) for k, v in obj.items() if k.lower() in allowed]
            if not prices or any(v is None for _, v in prices) or len({v for _, v in prices}) != 1:
                return None
            found.append((prices[0][1], prices[0][0]))
    return found[0] if len(found) == 1 else None


def _members(root):
    shortlist = _read(root, "data/shopify_shortlist.json")
    master = _read(root, "data/product_master.json")
    catalog = _read(root, "data/daiso_real/products.json")
    ids = shortlist.get("active_pd_nos")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(not isinstance(x, str) or not re.fullmatch(r"[0-9]+", x) for x in ids) or len(set(ids)) != len(ids):
        raise Blocked("invalid_shortlist_members")
    registry = master.get("pd_no_to_cp", {})
    products = master.get("products", [])
    cp_ids = list(registry.values())
    if master.get("active_product_count") != 356 or master.get("registry_count") != 357 or len(registry) != 357 or len(set(cp_ids)) != 357 or len(products) != 356 or len(catalog.get("products", [])) != 356:
        raise Blocked("catalog_registry_count_mismatch")
    active = {}
    for p in products:
        pd, cp = p.get("pd_no"), p.get("canonical_product_id")
        if pd in active or not isinstance(cp, str) or not re.fullmatch(r"CP[0-9]{6}", cp) or registry.get(pd) != cp:
            raise Blocked("noncanonical_master")
        active[pd] = cp
    catalog_ids = [p.get("pd_no") for p in catalog["products"]]
    if len(set(catalog_ids)) != 356 or set(catalog_ids) != set(active):
        raise Blocked("catalog_identity_mismatch")
    pairs = []
    for pd in ids:
        if pd not in active:
            raise Blocked("unknown_or_noncanonical_member")
        pairs.append((pd, active[pd]))
    units = shortlist.get("units", [])
    declared = []
    for unit in units:
        if unit.get("status") != "active":
            continue
        pds, cps = unit.get("pd_nos", []), unit.get("canonical_product_ids", [])
        if len(pds) != len(cps) or any(active.get(pd) != cp for pd, cp in zip(pds, cps)):
            raise Blocked("noncanonical_shortlist_unit")
        declared.extend(pds)
    if len(declared) != len(set(declared)) or set(declared) != set(ids):
        raise Blocked("shortlist_unit_membership_mismatch")
    return pairs


def _valid_prior(row, pairs):
    try:
        if (row["pd_no"], row["canonical_product_id"]) not in pairs or _numeric(row["price_krw"]) is None or row["price_unit"] != "product":
            return False
        source, prov = row["source"], row["provenance"]
        _url_ok(source["url"])
        return source["url"] == BASE + SEARCH + "?searchTerm=" + row["pd_no"] and source["capture_kind"] == "successful_http_parse" and _epoch(source["collected_at"]) is not None and prov["http_status"] == 200 and prov["parse_status"] == "exact_pd_no_numeric_price" and prov["endpoint"] == BASE + SEARCH
    except (KeyError, TypeError, ValueError):
        return False


def _deny_reset_with_watch_history(root):
    state_path = "data/operations/state.json"
    if not _safe(root, state_path).exists():
        return
    state = _read(root, state_path)
    if not isinstance(state, dict):
        raise Blocked("invalid_fixed_operations_state")
    sources = state.get("watch", {}).get("sources", {})
    if not isinstance(sources, dict):
        raise Blocked("invalid_fixed_watch_sources")
    # Inspect only known sourcing/pricing watch records in this one fixed file.
    # Never follow paths, tasks, adapters, or instructions in the state.
    stack = [sources.get(team, {}) for team in ("sourcing", "pricing")]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and item.replace("\\\\", "/").rstrip("/").endswith(OUTPUT):
            raise Blocked("durable_observation_history_deleted_watch_evidence")


def _check_budget_checkpoint(previous, ledger):
    checkpoint = previous.get("budget_checkpoint")
    if checkpoint is None:
        # Legacy real outputs retain their original captures; require the
        # existing durable counter to cover their per-run HTTP count below.
        return
    if not isinstance(checkpoint, dict):
        raise Blocked("invalid_budget_checkpoint")
    count = checkpoint.get("total_http_attempts")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise Blocked("invalid_budget_checkpoint_counter")
    if ledger.get("total_http_attempts", 0) < count:
        raise Blocked("durable_claim_below_budget_checkpoint")
    for key in ("last_run_attempt_at", "last_request_at"):
        minimum = _epoch(checkpoint.get(key))
        actual = _epoch(ledger.get(key))
        if minimum is None or minimum > time.time() or actual is None or actual < minimum:
            raise Blocked("durable_claim_clock_below_budget_checkpoint")
    if _epoch(checkpoint["last_request_at"]) < _epoch(checkpoint["last_run_attempt_at"]):
        raise Blocked("invalid_budget_checkpoint_clock_order")


def _history_digest(history):
    return hashlib.sha256(json.dumps(history, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _continuity(previous, claim):
    """No genesis creation here. Exact matching legacy evidence is required."""
    data = claim.data
    _check_budget_checkpoint(previous, data)
    count = data["total_http_attempts"]
    if "policy" not in data:
        evidence = previous.get("budget_checkpoint", {}).get("total_http_attempts", previous.get("http_attempt_count"))
        checkpoint = previous.get("budget_checkpoint")
        matched = isinstance(checkpoint, dict) and all(checkpoint.get(key) == data.get(key) for key in ("total_http_attempts", "last_run_attempt_at", "last_request_at"))
        legacy_seven = checkpoint is None and count == 7 and evidence == 7
        if not count or not previous.get("products") or not (matched or legacy_seven):
            raise Blocked("unsupported_legacy_claim")
        data["policy"] = dict(POLICY)
        data["request_history"] = [{"sequence": i, "reserved_at": data["last_request_at"], "kind": "legacy_reserved"} for i in range(1, count + 1)]
        data["migration"] = {"version": 2, "legacy_total_http_attempts": count,
                             "legacy_last_run_attempt_at": data["last_run_attempt_at"],
                             "legacy_last_request_at": data["last_request_at"]}
        data["last_checked_at"] = data["last_request_at"]
    if data.get("policy") != POLICY:
        raise Blocked("invalid_claim_policy")
    history = data.get("request_history")
    if not isinstance(history, list) or len(history) != count:
        raise Blocked("invalid_window_lifetime_proof")
    minimum = None
    for index, event in enumerate(history, 1):
        stamp = _epoch(event.get("reserved_at")) if isinstance(event, dict) else None
        if not isinstance(event, dict) or isinstance(event.get("sequence"), bool) or event.get("sequence") != index or stamp is None or stamp > time.time() or (minimum is not None and stamp < minimum):
            raise Blocked("invalid_window_lifetime_proof")
        minimum = stamp
    if history and _epoch(data["last_request_at"]) != minimum:
        raise Blocked("claim_history_clock_mismatch")
    checked = _epoch(data.get("last_checked_at"))
    if checked is None or checked > time.time() or checked < _epoch(data["last_request_at"]):
        raise Blocked("claim_clock_rollback")
    checkpoint = previous.get("budget_checkpoint", {})
    proof = checkpoint.get("request_history_sha256")
    if proof is not None:
        prefix = checkpoint["total_http_attempts"]
        if proof != _history_digest(history[:prefix]):
            raise Blocked("claim_history_rollback")
        prior_checked = _epoch(checkpoint.get("last_checked_at"))
        if prior_checked is None or checked < prior_checked:
            raise Blocked("claim_checked_clock_rollback")
    for state in data.get("member_attempts", {}).values():
        stamp = _epoch(state.get("attempted_at"))
        if stamp is None or stamp > checked:
            raise Blocked("invalid_member_attempt_clock")
    claim.save()


def observe(root, *, force=False):
    """Fixed official GET scope. Force reevaluates metadata only; it cannot release safety stops."""
    started = time.monotonic()
    wall_started = time.time()
    root = Path(root)
    if ".." in root.parts:
        raise Blocked("path_traversal")
    root = root.absolute()
    _safe(root)
    if _safe(root, 'data/operations/.restore-pending.json').exists():
        raise Blocked('operations_safety_restore_pending')
    if _safe(root, '.source-safety-restore.pending').exists():
        raise Blocked('source_safety_restore_requires_reconciliation')
    _safe(root, OUTPUT)
    before = _hashes(root)
    pairs = _members(root)
    previous = _read(root, OUTPUT) if _safe(root, OUTPUT).exists() else {}
    if not _safe(root, LEDGER).exists():
        raise Blocked("durable_claim_missing_no_bootstrap")
    prior = [r for r in previous.get("products", []) if _valid_prior(r, pairs)]
    if len({r["pd_no"] for r in prior}) != len(prior):
        raise Blocked("duplicate_prior_observations")
    for row in prior:
        if _epoch(row["source"]["collected_at"]) > wall_started:
            raise Blocked("future_capture_clock")
    products = {r["pd_no"]: r for r in prior}
    attempts, failures, new_ids = [], [], []
    history = list(previous.get("observation_history", []))
    if previous.get("attempts"):
        history.append({"attempts": previous["attempts"], "budget_checkpoint": previous.get("budget_checkpoint"), "status": previous.get("status")})
    captures = list(previous.get("capture_history", []))
    for row in previous.get("products", []) + previous.get("retained_previous_products", []):
        if row not in captures:
            captures.append(row)
    retained = previous.get("retained_previous_products", []) + [r for r in previous.get("products", []) if (r.get("pd_no"), r.get("canonical_product_id")) not in pairs]
    with _Claim(root) as claim:
        _continuity(previous, claim)
        # Retain the original legacy checkpoint verbatim. A separate proof
        # binds its evidenced reservation prefix when it is observed during
        # migration; this is a CHECK time, never a fabricated capture time.
        for event in history:
            old_checkpoint = event.get("budget_checkpoint") or {}
            if old_checkpoint.get("request_history_sha256") is None and "legacy_budget_proof" not in event:
                n = old_checkpoint.get("total_http_attempts")
                migration = claim.data.get("migration") or {}
                if (not old_checkpoint and previous.get('schema_version') == 1
                        and migration.get('legacy_total_http_attempts') == 7
                        and previous.get('http_attempt_count') == 7
                        and event.get('attempts') == previous.get('attempts')):
                    # The original legacy7 document had no checkpoint. Its
                    # exact capture/attempt evidence was validated by migration.
                    # Keep None verbatim; bind known legacy ledger clocks only.
                    n = 7
                if type(n) is not int or n != migration.get("legacy_total_http_attempts") or not all(r.get("kind") == "legacy_reserved" for r in claim.data["request_history"][:n]):
                    raise Blocked("unproved_legacy_history_checkpoint")
                event["legacy_budget_proof"] = {"legacy_checkpoint_sha256": hashlib.sha256(json.dumps(old_checkpoint, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "checkpoint": {**(old_checkpoint or {k:claim.data[k] for k in ('total_http_attempts','last_run_attempt_at','last_request_at')}), "policy_version": 2,
                    "last_checked_at": datetime.fromtimestamp(wall_started, timezone.utc).isoformat(),
                    "request_history_sha256": _history_digest(claim.data["request_history"][:n])}}
        prior_count = previous.get("http_attempt_count", 0)
        if isinstance(prior_count, bool) or not isinstance(prior_count, int) or prior_count < 0 or claim.data["total_http_attempts"] < prior_count:
            raise Blocked("invalid_prior_attempt_count")
        run_count = 0
        last_wall, last_mono = wall_started, started

        def clock():
            nonlocal last_wall, last_mono
            wall, mono = time.time(), time.monotonic()
            if wall < last_wall or mono < last_mono or wall < _epoch(claim.data["last_checked_at"]):
                raise Blocked("run_clock_rollback")
            last_wall, last_mono = wall, mono
            return wall, mono

        def checkpoint():
            return {**{key: claim.data[key] for key in ("total_http_attempts", "last_run_attempt_at", "last_request_at", "last_checked_at")},
                    "policy_version": POLICY["version"], "request_history_sha256": _history_digest(claim.data["request_history"])}

        def persist():
            after = _hashes(root)
            if before != after:
                raise Blocked("operating_inputs_changed_no_observation_write")
            wall, _ = clock()
            claim.data["last_checked_at"] = datetime.fromtimestamp(wall, timezone.utc).isoformat()
            missing = [cp for pd, cp in pairs if pd not in products]
            status = "partial" if failures and products else "blocked" if failures else "complete" if new_ids else "cached"
            doc = {"schema_version": 2, "policy": dict(POLICY), "scope": "active_shopify_shortlist_only", "operating_catalog_mutated": False,
                   "status": status, "complete": not failures and not missing, "expected_ids": [cp for _, cp in pairs],
                   "products": [products[pd] for pd, cp in pairs if pd in products], "attempts": attempts,
                   "http_attempt_count": run_count, "new_success_ids": new_ids, "failed_ids": list(dict.fromkeys(failures)),
                   "missing_ids": missing, "retained_original_capture_ids": [cp for pd, cp in pairs if pd in products and cp not in new_ids],
                   "cooldown_seconds": COOLDOWN, "fresh_ttl_seconds": FRESH_TTL, "catalog_count": 356, "registry_count": 357,
                   "input_hashes_before": before, "input_hashes_after": after, "inputs_byte_identical": True,
                   "retained_previous_products": retained, "capture_history": captures,
                   "observation_history": history, "budget_checkpoint": checkpoint()}
            # Ledger first: a crash can overcount a reservation, never undercount.
            claim.data["last_result_status"] = status
            claim.save()
            _atomic(root, OUTPUT, doc)
            return doc

        def request(url, kind, pd=None, delay=30):
            nonlocal run_count
            wall, mono = clock()
            recent = sum(wall - _epoch(e["reserved_at"]) < POLICY["rolling_window_seconds"] for e in claim.data["request_history"])
            if run_count >= POLICY["per_run_http_cap"]:
                raise Blocked("per_run_http_cap")
            if recent >= POLICY["rolling_http_cap"]:
                raise Blocked("rolling_http_cap")
            wait = max(0, delay - (wall - _epoch(claim.data["last_request_at"])))
            envelope = POLICY["http_envelope_seconds"] + POLICY["safety_margin_seconds"]
            if mono - started + wait + envelope > POLICY["run_deadline_seconds"]:
                raise Blocked("run_deadline_admission")
            if wait:
                time.sleep(wait)
            wall, mono = clock()
            if mono - started + envelope > POLICY["run_deadline_seconds"]:
                raise Blocked("run_deadline_admission")
            stamp = datetime.fromtimestamp(wall, timezone.utc).isoformat()
            if run_count == 0:
                claim.data["last_run_attempt_at"] = stamp
            claim.data["last_request_at"] = stamp
            claim.data["total_http_attempts"] += 1
            run_count += 1
            claim.data["request_history"].append({"sequence": claim.data["total_http_attempts"], "reserved_at": stamp, "kind": kind, "pd_no": pd})
            event = {"kind": kind, "pd_no": pd, "url": url, "attempted_at": stamp,
                     "attempt_number": 1 + sum(a.get("url") == url for a in attempts), "http_status": None, "parse_status": "reserved"}
            attempts.append(event)
            if pd:
                claim.data.setdefault("member_attempts", {})[pd] = {"attempted_at": stamp, "outcome": "inflight"}
            persist()  # reservation durable before entering any network code
            try:
                status, body = _http_get(url)
                event["http_status"] = status
                event["response_bytes"] = len(body)
                return status, body, event
            except (OSError, ValueError, urllib.error.URLError) as exc:
                event["error"] = type(exc).__name__
                event["parse_status"] = "blocked" if isinstance(exc, Blocked) else "transport_failed"
                return None, b"", event

        needed = []
        for pd, cp in pairs:
            if pd in products and wall_started - _epoch(products[pd]["source"]["collected_at"]) < FRESH_TTL:
                continue
            state = claim.data.get("member_attempts", {}).get(pd)
            reason = None
            if claim.data.get("automatic_retry_block"):
                reason = "manual_review_required"
            elif state and wall_started - _epoch(state["attempted_at"]) < COOLDOWN:
                reason = "member_retry_cooldown"
            if reason:
                failures.append(cp)
                attempts.append({"kind": "cooldown", "pd_no": pd, "http_attempts": 0, "reason": reason})
            else:
                needed.append((pd, cp))
        # Mark pending members before reservations so a hardkill never reports completion.
        failures.extend(cp for _, cp in needed)
        parser, delay = None, 30
        if needed:
            try:
                status, body, event = request(BASE + "/robots.txt", "robots")
                if status == 200 and not re.search(rb"quota|rate.?limit|captcha|access.denied", body, re.I):
                    try:
                        text = body.decode("utf-8-sig", errors="strict")
                        if not re.search(r"(?im)^\s*User-agent\s*:", text) or "<html" in text.lower():
                            raise Blocked("unknown_robots")
                        parser = urllib.robotparser.RobotFileParser()
                        parser.parse(text.splitlines())
                        delays = re.findall(r"(?im)^\s*Crawl-delay\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$", text)
                        delay = max([30] + [float(x) for x in delays])
                        if not math.isfinite(delay):
                            raise Blocked("invalid_crawl_delay")
                        event["parse_status"] = "robots_parsed"
                    except (ValueError, UnicodeError):
                        parser = None
                        event["parse_status"] = "robots_unknown"
                if parser is None:
                    claim.data["automatic_retry_block"] = "robots_or_access_unknown"
                else:
                    claim.data.pop("automatic_retry_block", None)
                persist()  # no automatic retries of robots, auth, or quota
            except Blocked as exc:
                if str(exc) not in {"per_run_http_cap", "rolling_http_cap", "run_deadline_admission"}:
                    raise
                attempts.append({"kind": "admission", "http_attempts": 0, "reason": str(exc)})
        halted = parser is None
        for pd, cp in needed:
            url = BASE + SEARCH + "?searchTerm=" + pd
            if halted or not parser.can_fetch(UA, url):
                if not halted:
                    claim.data["automatic_retry_block"] = "robots_denied"
                    halted = True
                attempts.append({"kind": "product", "pd_no": pd, "http_attempts": 0, "parse_status": "blocked", "reason": "robots_or_admission_blocked"})
                continue
            try:
                for retry in range(2):
                    status, body, event = request(url, "product", pd, delay)
                    restricted = bool(re.search(rb"quota|rate.?limit|captcha|access.denied", body, re.I))
                    parsed = _parse(body, pd) if status == 200 and not restricted else None
                    if parsed:
                        price, key = parsed
                        event["parse_status"] = "exact_pd_no_numeric_price"
                        products[pd] = {"canonical_product_id": cp, "pd_no": pd, "price_krw": price, "price_unit": "product", "source": {"url": url, "collected_at": _now(), "capture_kind": "successful_http_parse"}, "provenance": {"endpoint": BASE + SEARCH, "http_status": 200, "parse_status": "exact_pd_no_numeric_price", "identity_key": "pdNo", "price_key": key, "response_sha256": hashlib.sha256(body).hexdigest(), "robots_checked": True, "crawl_delay_seconds": delay}}
                        new_ids.append(cp)
                        failures.remove(cp)
                    else:
                        event["parse_status"] = "parse_failed" if status == 200 else event["parse_status"]
                    claim.data["member_attempts"][pd]["outcome"] = "success" if parsed else "failed"
                    if status in {401, 403, 407, 429} or restricted:
                        halted = True
                        claim.data["automatic_retry_block"] = "auth_quota_or_rate_limit"
                    persist()  # actual received parse/capture is durable before next call/sleep
                    if parsed or halted or retry or not (status in TRANSIENT or (status is None and event["parse_status"] == "transport_failed")):
                        break
            except Blocked as exc:
                if str(exc) not in {"per_run_http_cap", "rolling_http_cap", "run_deadline_admission"}:
                    raise
                attempts.append({"kind": "admission", "pd_no": pd, "http_attempts": 0, "reason": str(exc)})
                halted = True
        return persist()

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Reevaluate metadata only; never bypasses freshness, cooldown, provider stops or safety bounds")
    args = parser.parse_args(argv)
    try:
        # An old workflow may checkout newer code without new always-upload
        # steps. It must never consume reservations without restored continuity.
        if os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('JARVIS_SOURCE_CONTINUITY') != 'verified':
            raise Blocked('authenticated_runner_continuity_required')
        # Exact prior bytes survive normal, partial and failed publication.
        # Recording diagnostics never changes a genuine capture clock.
        previous_output = _safe(args.root, OUTPUT).read_bytes() if _safe(args.root, OUTPUT).exists() else None
        previous_ledger = _safe(args.root, LEDGER).read_bytes() if _safe(args.root, LEDGER).exists() else None
        result = observe(args.root, force=args.force)
        repository = Path(__file__).resolve().parents[2]
        if str(repository) not in sys.path:
            sys.path.insert(0, str(repository))
        from scripts.shortlist_observation_history import preserve
        preserve(args.root, previous_output=previous_output, previous_ledger=previous_ledger)
    except (Blocked, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "operating_catalog_mutated": False}))
        return 2
    print(json.dumps({k: result[k] for k in ("status", "expected_ids", "new_success_ids", "failed_ids", "http_attempt_count", "inputs_byte_identical")}))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
