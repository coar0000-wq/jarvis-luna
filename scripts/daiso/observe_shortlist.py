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
COOLDOWN = 24 * 3600
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
            self.data = _read(self.root, LEDGER) if self.path.exists() else {}
            if not isinstance(self.data, dict):
                raise Blocked("invalid_claim_ledger")
            if self.path.exists():
                counter = self.data.get("total_http_attempts")
                if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
                    raise Blocked("invalid_claim_counter")
                for key in ("last_run_attempt_at", "last_request_at"):
                    value = _epoch(self.data.get(key))
                    if value is None or value > time.time() + 5:
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
        if minimum is None or minimum > time.time() + 5 or actual is None or actual < minimum:
            raise Blocked("durable_claim_clock_below_budget_checkpoint")
    if _epoch(checkpoint["last_request_at"]) < _epoch(checkpoint["last_run_attempt_at"]):
        raise Blocked("invalid_budget_checkpoint_clock_order")


def observe(root, *, force=False):
    """Fixed-scope entry point. No caller transport, endpoints, or adapters."""
    root = Path(root)
    if ".." in root.parts:
        raise Blocked("path_traversal")
    root = root.absolute()
    _safe(root)
    _safe(root, OUTPUT)
    before = _hashes(root)
    pairs = _members(root)
    previous = _read(root, OUTPUT) if _safe(root, OUTPUT).exists() else {}
    if not _safe(root, OUTPUT).exists() and not _safe(root, LEDGER).exists():
        _deny_reset_with_watch_history(root)
    if previous and not _safe(root, LEDGER).exists() and (
        previous.get("products") or previous.get("retained_previous_products") or
        previous.get("http_attempt_count", 0) or any(
            a.get("http_status") is not None or a.get("attempted_at") or "error" in a
            for a in previous.get("attempts", [])
        )
    ):
        raise Blocked("durable_claim_missing_with_observation_history")
    prior = [r for r in previous.get("products", []) if _valid_prior(r, pairs)]
    if len({r["pd_no"] for r in prior}) != len(prior):
        raise Blocked("duplicate_prior_observations")
    products = {r["pd_no"]: r for r in prior}
    attempts = []
    failures = []
    new_ids = []
    now = time.time()
    with _Claim(root) as claim:
        _check_budget_checkpoint(previous, claim.data)
        prior_count = previous.get("http_attempt_count", 0)
        if isinstance(prior_count, bool) or not isinstance(prior_count, int) or prior_count < 0:
            raise Blocked("invalid_prior_attempt_count")
        counter = claim.data.get("total_http_attempts", 0)
        if counter < prior_count or (previous.get("products") and counter == 0):
            raise Blocked("durable_claim_counter_reset")
        last = _epoch(claim.data.get("last_run_attempt_at"))
        run_cooldown = not force and last is not None and 0 <= now - last < COOLDOWN
        needed = [(pd, cp) for pd, cp in pairs if force or pd not in products or not 0 <= now - _epoch(products[pd]["source"]["collected_at"]) < COOLDOWN]
        def request(url, kind, pd=None, delay=30):
            last_request = _epoch(claim.data.get("last_request_at"))
            if last_request is not None:
                wait = delay - (time.time() - last_request)
                if wait > 0:
                    time.sleep(wait)
            claim.data["last_request_at"] = _now()
            claim.data["total_http_attempts"] = claim.data.get("total_http_attempts", 0) + 1
            claim.save()
            event = {"kind": kind, "pd_no": pd, "url": url, "attempted_at": _now(), "attempt_number": 1 + sum(a.get("url") == url for a in attempts), "http_status": None, "parse_status": "not_parsed"}
            attempts.append(event)
            try:
                status, body = _http_get(url)
                event["http_status"] = status
                event["response_bytes"] = len(body)
                return status, body, event
            except (OSError, ValueError, urllib.error.URLError) as exc:
                event["error"] = type(exc).__name__
                event["parse_status"] = "blocked" if isinstance(exc, Blocked) else "transport_failed"
                return None, b"", event
        if run_cooldown:
            failures = [cp for pd, cp in needed]
            attempts.append({"kind": "cooldown", "http_attempts": 0, "reason": "durable_attempt_cooldown"})
        elif needed:
            claim.data["last_run_attempt_at"] = _now()
            # Establish both clocks/counter before any HTTP read, atomically.
            # This conservative reservation survives a crash before robots GET.
            claim.data["last_request_at"] = claim.data["last_run_attempt_at"]
            claim.data.setdefault("total_http_attempts", 0)
            claim.data["expected_ids"] = [cp for _, cp in pairs]
            claim.save()
            status, body, event = request(BASE + "/robots.txt", "robots")
            if status in TRANSIENT or (status is None and event["parse_status"] == "transport_failed"):
                status, body, event = request(BASE + "/robots.txt", "robots")
            parser = None
            delay = 30
            if status == 200:
                try:
                    text = body.decode("utf-8-sig", errors="strict")
                    if not re.search(r"(?im)^\s*User-agent\s*:", text) or "<html" in text.lower():
                        raise Blocked("unknown_robots")
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(text.splitlines())
                    # Honour even fractional and wildcard crawl-delay conservatively.
                    delays = re.findall(r"(?im)^\s*Crawl-delay\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$", text)
                    delay = max([30] + [float(x) for x in delays])
                    if delay > 300:
                        raise Blocked("crawl_delay_exceeds_bounded_run")
                    event["parse_status"] = "robots_parsed"
                except (ValueError, UnicodeError):
                    parser = None
                    event["parse_status"] = "robots_unknown"
            halted = parser is None
            for pd, cp in needed:
                url = BASE + SEARCH + "?searchTerm=" + pd
                if halted or not parser.can_fetch(UA, url):
                    attempts.append({"kind": "product", "pd_no": pd, "http_attempts": 0, "parse_status": "blocked", "reason": "robots_unknown_or_denied" if not halted else "robots_or_rate_limit_blocked"})
                    failures.append(cp)
                    continue
                status, body, event = request(url, "product", pd, delay)
                if status in TRANSIENT or (status is None and event["parse_status"] == "transport_failed"):
                    status, body, event = request(url, "product", pd, delay)
                restricted = status == 200 and bool(re.search(rb"quota|rate.?limit|captcha|access.denied", body, re.I))
                parsed = _parse(body, pd) if status == 200 and not restricted else None
                if parsed:
                    price, key = parsed
                    event["parse_status"] = "exact_pd_no_numeric_price"
                    products[pd] = {"canonical_product_id": cp, "pd_no": pd, "price_krw": price, "price_unit": "product", "source": {"url": url, "collected_at": _now(), "capture_kind": "successful_http_parse"}, "provenance": {"endpoint": BASE + SEARCH, "http_status": 200, "parse_status": "exact_pd_no_numeric_price", "identity_key": "pdNo", "price_key": key, "response_sha256": hashlib.sha256(body).hexdigest(), "robots_checked": True, "crawl_delay_seconds": delay}}
                    new_ids.append(cp)
                else:
                    event["parse_status"] = "parse_failed" if status == 200 else event["parse_status"]
                    failures.append(cp)
                if status in {401, 403, 407, 429} or restricted:
                    halted = True
        after = _hashes(root)
        if before != after:
            raise Blocked("operating_inputs_changed_no_observation_write")
        expected = [cp for _, cp in pairs]
        missing = [cp for pd, cp in pairs if pd not in products]
        status = "partial" if failures and products else "blocked" if failures else "complete" if new_ids else "cached"
        doc = {"schema_version": 1, "scope": "active_shopify_shortlist_only", "operating_catalog_mutated": False, "status": status, "complete": not failures and not missing, "expected_ids": expected, "products": [products[pd] for pd, cp in pairs if pd in products], "attempts": attempts, "http_attempt_count": sum(a.get("http_status") is not None or "error" in a for a in attempts), "new_success_ids": new_ids, "failed_ids": failures, "missing_ids": missing, "retained_original_capture_ids": [cp for pd, cp in pairs if pd in products and cp not in new_ids], "cooldown_seconds": COOLDOWN, "catalog_count": 356, "registry_count": 357, "input_hashes_before": before, "input_hashes_after": after, "inputs_byte_identical": True, "retained_previous_products": previous.get("retained_previous_products", []) + [r for r in previous.get("products", []) if (r.get("pd_no"), r.get("canonical_product_id")) not in pairs]}
        _check_budget_checkpoint(previous, claim.data)
        doc["budget_checkpoint"] = {key: claim.data[key] for key in (
            "total_http_attempts", "last_run_attempt_at", "last_request_at"
        )}
        # These minima survive cached/cooldown outputs with zero per-run reads.
        # Validation above ensures neither clocks nor lifetime count decrease.
        _atomic(root, OUTPUT, doc)
        claim.data["last_result_status"] = status
        claim.save()
        return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Manual re-observation; never bypasses robots or read bounds")
    args = parser.parse_args(argv)
    try:
        result = observe(args.root, force=args.force)
    except (Blocked, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "operating_catalog_mutated": False}))
        return 2
    print(json.dumps({k: result[k] for k in ("status", "expected_ids", "new_success_ids", "failed_ids", "http_attempt_count", "inputs_byte_identical")}))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
