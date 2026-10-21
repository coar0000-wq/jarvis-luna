#!/usr/bin/env python3
"""Offline, deterministic 3-category beauty price strategy (skincare / makeup / body).

Categories come from config/daiso_commerce_strategy.json (score_buckets): skincare = 스킨케어 + 마스크팩 +
클렌징 + 선케어, makeup = 메이크업, body = 바디케어. Reclassifying a bucket into a category never changes
its grade; US OTC/claim pre-gates, the original S gate and non-beauty exclusion still apply.

Compares Daiso cost, our own Shopify prices and market comparable prices from
already-collected local JSON. It never touches the network, never calls a paid
API and never edits any other file. The only side effect is the single file
passed with --output (explicit, required; existing files are not overwritten
unless --overwrite is given).

Truthfulness rules enforced here (each one is covered by a unit test):
  * Units are normalised exactly (Decimal): ml / g / count, with unit size, pack
    count and pack total kept as separate fields. Grams are never compared with
    millilitres; a bare "oz" is ambiguous and only compares with itself.
  * A market price is only a comparator when brand/line/variant tokens are the
    same (different strength, formulation, model, set/kit or "N options"
    listings are rejected) and the unit dimension is the same.
  * Stale or unverified sources, unknown currency/market, sold-out items and
    items without a parseable quantity never produce a "victory".
    Stale/unverified identity matches are kept as reference_only and are never
    used for a score.
  * A verified comparison requires exact pack quantities and fresh, price-bound
    US standard-delivery quotes for the same non-personal destination key.
    Shipping, tax and mandatory fees must be explicit, including genuine zeroes.
    Missing costs are unknown, never zero. Only verified comparisons earn points.
  * Original grades are never changed. A price advantage cannot upgrade an A
    product to S; S products are audited against the original S gate only.
  * Margin is advisory (the user waived the margin block). Negative margins stay
    visible as profitability risk and never remove or block a product.
  * Missing analytics are the literal string "UNKNOWN", never zero.
  * No handoff / approval / completion receipt is ever invented.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit

from payment_fees import profit_flags
from manufacturer_safety import manufacturer_safety_record, public_view as safety_public_view

SCHEMA_VERSION = 1
GENERATOR = "scripts/build_beauty_price_strategy.py"
UTC = timezone.utc
UNKNOWN = "UNKNOWN"

# Built-in fallback that mirrors config/daiso_commerce_strategy.json (read at run time when present).
DEFAULT_COMMERCE_CONFIG = {
    "policy_id": "builtin_fallback_mirror",
    "grade_policy": {"allowed_grades": ["S"], "lower_grade_fallback": False},
    "categories": [
        {"tag": "skincare", "daiso_name": "스킨케어", "score_buckets": ["스킨케어", "마스크팩", "클렌징", "선케어"], "allowed_grades": ["S"]},
        {"tag": "makeup", "daiso_name": "메이크업", "score_buckets": ["메이크업"], "allowed_grades": ["S"]},
        {"tag": "body", "daiso_name": "바디케어", "score_buckets": ["바디케어"], "allowed_grades": ["S"]},
    ],
    "price_policy": {"margin_advisory": {"target_margin": 0.40, "minimum_margin": 0.30, "estimated_weight_extra_margin": 0.05},
                     "volume_comparison": {"tolerance": 0.05},
                     "price_evidence": {"sources": {"serpapi_google_shopping": {"min_sample": 5, "max_age_days": 30, "price_factor": 0.95},
                                                       "shop_com_live_comparable": {"max_age_days": 1}}}},
}
GRADE_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}

# Mirrors scripts/daiso/score_shopify_demand.py (read only, not imported).
S_CORE_BUCKETS = {"스킨케어", "마스크팩", "클렌징", "메이크업", "헤어케어", "바디케어"}
S_QUALIFYING_RULES = {"ingredient+form", "multi_token", "strong_ingredient", "strong_form"}
S_MIN_SCORE = 82

DEFAULT_MAX_AGE_HOURS = 168.0
DEFAULT_VOLUME_TOLERANCE = Decimal("0.05")

# Mirrors the US legal pre-gates in scripts/daiso/score_shopify_demand.py (read only).
US_OTC_SUN = ("spf", "선크림", "선스틱", "선쿠션", "선세럼", "자차", "선블록", "sunscreen", "sun cream", "pa+")
KR_CLAIM_RISK = ("화이트닝", "미백", "주름개선", "링클", "안티에이징", "여드름", "아크네", "기능성화장품", "아토피")


def us_gate_kind(name, score_block_kind=None) -> str:
    """'' | otc_drug | claim_risk. Name lexicon mirror OR the score file's own us_block_kind."""
    if score_block_kind in ("otc_drug", "claim_risk"):
        return score_block_kind
    low = (name or "").lower()
    if any(k in low for k in US_OTC_SUN):
        return "otc_drug"
    if any(k in (name or "") for k in KR_CLAIM_RISK):
        return "claim_risk"
    return ""


def parse_category_config(doc) -> dict:
    """-> {order, tags{tag:{daiso_name, buckets, allowed_grades}}, bucket_to_tag, grade_policy, policy_id}."""
    cfg = doc if isinstance(doc, dict) and isinstance(doc.get("categories"), list) and doc["categories"] else DEFAULT_COMMERCE_CONFIG
    used_fallback = cfg is DEFAULT_COMMERCE_CONFIG
    tags, b2t, order = {}, {}, []
    for c in cfg["categories"]:
        tag = c.get("tag")
        if not isinstance(tag, str) or not tag or tag in tags:
            continue
        buckets = [b for b in (c.get("score_buckets") or []) if isinstance(b, str)]
        tags[tag] = {"daiso_name": c.get("daiso_name"), "buckets": buckets, "allowed_grades": list(c.get("allowed_grades") or [])}
        order.append(tag)
        for b in buckets:
            b2t.setdefault(b, tag)
    return {"order": order, "tags": tags, "bucket_to_tag": b2t, "grade_policy": cfg.get("grade_policy") or {},
            "policy_id": cfg.get("policy_id"), "price_policy": cfg.get("price_policy") or {}, "used_fallback": used_fallback}
FUTURE_SKEW = timedelta(minutes=5)
DEFAULT_REVIEW_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------

ML_PER_FL_OZ = Decimal("29.5735295625")
G_PER_OZ = Decimal("28.349523125")
G_PER_LB = Decimal("453.59237")
QTY_TOLERANCE = Decimal("0.05")


def _dec(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _f(value, places=6):
    """Decimal/number -> deterministic finite float (or None)."""
    d = _dec(value)
    if d is None:
        return None
    q = Decimal(1).scaleb(-places)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def _positive(value):
    d = _dec(value)
    return d if d is not None and d > 0 else None


def checkout_total_evidence(quote, item_id, item_price, shipping_usd, as_of):
    """Validate recorded checkout facts, not a checkout/purchase or authenticity.

    Quotes describe one sale unit (which may itself be a pack). A destination
    key is a shared non-customer test scope, never an address or customer ID.
    Unknown extra fields are deliberately not copied into generated reports.
    """
    # No trusted checkout-observation producer is wired into this report yet.
    # A URL, self-declared boolean, reviewer name or hash supplied by this same
    # row cannot authenticate its source. Never copy an input's "verified" flag.
    result = {"known": False, "total_usd": None, "reasons": [],
              "source_verified": False,
              "source_reasons": ["checkout_source_provenance_unverified"],
              "scope": "recorded_quote_consistency_only"}
    if not isinstance(quote, dict):
        result["reasons"] = ["checkout_quote_missing"]
        return result
    reasons = result["reasons"]
    if quote.get("item_id") != item_id or not isinstance(item_id, str) or not item_id:
        reasons.append("checkout_item_mismatch")
    if quote.get("currency") != "USD" or quote.get("market") != "US":
        reasons.append("checkout_currency_or_market_unverified")
    if type(quote.get("quantity")) is not int or quote["quantity"] != 1:
        reasons.append("checkout_sale_unit_quantity_unverified")
    if quote.get("shipping_method") != "standard":
        reasons.append("checkout_standard_shipping_unverified")
    destination = quote.get("destination_key")
    if not isinstance(destination, str) or not re.fullmatch(r"us_[a-z0-9_]{3,64}", destination):
        reasons.append("checkout_destination_unknown")
    stamp = None
    try:
        raw_stamp = quote.get("observed_at")
        stamp = datetime.fromisoformat(raw_stamp.replace("Z", "+00:00"))
        age = (as_of - stamp).total_seconds() if stamp.tzinfo is not None else -1
        if not 0 <= age <= 24 * 3600:
            reasons.append("checkout_observation_stale_or_future")
    except (AttributeError, TypeError, ValueError, OverflowError):
        reasons.append("checkout_observation_invalid")
    url = quote.get("source_url")
    try:
        parsed = urlsplit(url if isinstance(url, str) else "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            reasons.append("checkout_source_url_missing_or_invalid")
    except ValueError:
        reasons.append("checkout_source_url_missing_or_invalid")
    amounts = {}
    for key in ("item_price_usd", "shipping_usd", "tax_usd", "mandatory_fees_usd"):
        amount = _dec(quote.get(key))
        if amount is None or amount < 0 or (key == "item_price_usd" and amount == 0):
            reasons.append("checkout_" + key + "_unknown")
        elif amount > Decimal("1000000"):
            reasons.append("checkout_" + key + "_outside_supported_range")
        else:
            try:
                if amount != amount.quantize(Decimal("0.01")):
                    reasons.append("checkout_" + key + "_fractional_cent")
                else:
                    amounts[key] = amount
            except InvalidOperation:
                reasons.append("checkout_" + key + "_invalid_precision")
    if amounts.get("item_price_usd") != _positive(item_price):
        reasons.append("checkout_item_price_mismatch")
    if _dec(shipping_usd) is None or amounts.get("shipping_usd") != _dec(shipping_usd):
        reasons.append("checkout_shipping_price_unverified")
    if reasons:
        return result
    result.update(known=True, total_usd=_f(sum(amounts.values()), 2),
                  tax_usd=_f(amounts["tax_usd"], 2),
                  mandatory_fees_usd=_f(amounts["mandatory_fees_usd"], 2),
                  destination_key=destination, shipping_method="standard",
                  observed_at=iso(stamp), source_url=url)
    return result


def _close(a: Decimal, b: Decimal, tol: Decimal = QTY_TOLERANCE) -> bool:
    if a == b:
        return True
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tol


def assert_finite(obj, path="$"):
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"non-finite number at {path}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_finite(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_finite(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# timestamps / freshness
# ---------------------------------------------------------------------------

def parse_ts(value):
    """ISO timestamp -> aware UTC datetime. Date-only / invalid -> None. Naive = UTC."""
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


def iso(dt) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def assess_freshness(ts, as_of: datetime, max_age_hours: float) -> dict:
    parsed = parse_ts(ts)
    if parsed is None:
        return {"state": "invalid", "age_hours": None}
    delta = as_of - parsed
    if delta < -FUTURE_SKEW:
        return {"state": "invalid", "age_hours": None}
    age = max(0.0, delta.total_seconds() / 3600.0)
    state = "fresh" if age <= max_age_hours else "stale"
    return {"state": state, "age_hours": round(age, 2)}


# ---------------------------------------------------------------------------
# exact unit parsing
# ---------------------------------------------------------------------------

_MEASURE_RE = re.compile(
    r"(?P<num>\d+(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>fl\.?\s*oz\.?|ml|㎖|kg|mg|lb|oz|ct|ea|pcs|pc|매입|매|개입|개|l|g)(?![a-z])",
    re.IGNORECASE,
)
_PACK_AFTER_RE = re.compile(
    r"(?:\s*[x×*]\s*(?P<a>\d+)(?!\d|\.\d)(?:\s*(?:ea|ct|pcs|pc|개입|개|매입|매))?"
    r"|\s+(?P<b>\d+)\s*(?:개입|ea|ct|pcs)(?![a-z]))",
    re.IGNORECASE,
)
_PACK_BEFORE_RE = re.compile(r"(?P<n>\d+)\s*[x×*]\s*$", re.IGNORECASE)
_PLUS_RE = re.compile(r"(?<!\d)\+")

_UNIT_TABLE = {
    "ml": ("ml", Decimal(1), "ml"),
    "㎖": ("ml", Decimal(1), "ml"),
    "l": ("ml", Decimal(1000), "ml"),
    "floz": ("ml", ML_PER_FL_OZ, "floz"),
    "g": ("g", Decimal(1), "g"),
    "kg": ("g", Decimal(1000), "g"),
    "mg": ("g", Decimal("0.001"), "g"),
    "lb": ("g", G_PER_LB, "g"),
    "oz": ("oz_ambiguous", Decimal(1), "oz"),
}
for _u in ("ct", "ea", "pcs", "pc", "매입", "매", "개입", "개"):
    _UNIT_TABLE[_u] = ("count", Decimal(1), "count")

_DIM_PRIORITY = ("ml", "g", "oz_ambiguous", "count")
_BASE_UNIT = {"ml": "ml", "g": "g", "oz_ambiguous": "oz", "count": "count"}


def _scan_measures(text: str, label: str):
    out = []
    consumed = 0
    for m in _MEASURE_RE.finditer(text):
        if m.start() < consumed:
            continue
        unit_key = re.sub(r"[\s.]", "", m.group("unit").lower())
        spec = _UNIT_TABLE.get(unit_key)
        num = _dec(m.group("num"))
        if spec is None or num is None or num <= 0:
            continue
        dim, factor, origin = spec
        pack = 1
        pm = _PACK_AFTER_RE.match(text, m.end())
        if pm:
            pack = int(pm.group("a") or pm.group("b"))
            consumed = pm.end()
        else:
            pre = _PACK_BEFORE_RE.search(text[: m.start()])
            if pre:
                pack = int(pre.group("n"))
        if pack < 1:
            pack = 1
        out.append({"dim": dim, "amount": num * factor, "pack": pack, "origin": origin, "src": label})
    return out


def _resolve_dim(measures):
    """-> (chosen measure | None, flags). None means conflicting evidence."""
    flags = []
    packed = [m for m in measures if m["pack"] > 1]
    if packed:
        chosen = packed[0]
        for other in packed[1:]:
            if other["pack"] != chosen["pack"] or not _close(other["amount"], chosen["amount"]):
                return None, ["pack_conflict"]
    else:
        metric_first = sorted(measures, key=lambda m: m["origin"] == "floz")
        chosen = metric_first[0]
    total = chosen["amount"] * chosen["pack"]
    for m in measures:
        if not (_close(m["amount"], chosen["amount"]) or (m["pack"] == 1 and _close(m["amount"], total))):
            return None, ["unit_value_conflict"]
    if chosen["origin"] == "floz":
        flags.append("converted_from_fl_oz")
    return chosen, flags


def parse_quantity(texts) -> dict:
    """texts: iterable of (label, text). Exact ml / g / count normalisation.

    unit_amount, pack_count and total are separate; total = unit_amount * pack_count.
    """
    flags = []
    by_dim = defaultdict(list)
    plus = False
    seen_text = False
    for label, text in texts:
        if not isinstance(text, str) or not text.strip():
            continue
        seen_text = True
        text = text.replace("\xa0", " ")
        if _PLUS_RE.search(text):
            plus = True
        for m in _scan_measures(text, label):
            by_dim[m["dim"]].append(m)
    if plus:
        flags.append("contains_plus_bundle")
    if not by_dim:
        return {"status": "unknown", "primary_dim": None, "base_unit": None, "unit_amount": None,
                "pack_count": None, "total": None, "alternates": {},
                "flags": sorted(set(flags + ([] if seen_text else ["no_text"]))), "sources": []}

    # oz_ambiguous that is corroborated by g is only a label restatement.
    if "oz_ambiguous" in by_dim and "g" in by_dim:
        g_ref = by_dim["g"][0]["amount"] * by_dim["g"][0]["pack"]
        oz_ok = all(_close(m["amount"] * m["pack"] * G_PER_OZ, g_ref) or
                    _close(m["amount"] * G_PER_OZ, by_dim["g"][0]["amount"]) for m in by_dim["oz_ambiguous"])
        if oz_ok:
            flags.append("oz_corroborates_g")
            del by_dim["oz_ambiguous"]
        else:
            return {"status": "ambiguous" if plus else "conflict", "primary_dim": None, "base_unit": None, "unit_amount": None,
                    "pack_count": None, "total": None, "alternates": {},
                    "flags": sorted(set(flags + ["oz_vs_g_conflict"])), "sources": []}

    resolved = {}
    for dim in _DIM_PRIORITY:
        if dim not in by_dim:
            continue
        chosen, dflags = _resolve_dim(by_dim[dim])
        if chosen is None:
            if dim == next((d for d in _DIM_PRIORITY if d in by_dim), None):
                return {"status": "ambiguous" if plus else "conflict", "primary_dim": None, "base_unit": None, "unit_amount": None,
                        "pack_count": None, "total": None, "alternates": {},
                        "flags": sorted(set(flags + dflags + [f"{dim}_conflict"])), "sources": []}
            flags.append(f"{dim}_alternate_dropped_conflict")
            continue
        flags.extend(dflags)
        resolved[dim] = chosen

    primary_dim = next(d for d in _DIM_PRIORITY if d in resolved)
    prim = resolved[primary_dim]
    # A separate count such as "30ml (2pcs)" does not establish whether 30ml
    # is per bottle or the whole pack. Never silently treat it as one bottle.
    secondary_count = resolved.get("count") if primary_dim != "count" else None
    if secondary_count and secondary_count["amount"] * secondary_count["pack"] != prim["pack"]:
        flags.append("secondary_count_pack_ambiguous")
    alternates = {}
    for dim, ch in resolved.items():
        if dim == primary_dim:
            continue
        alternates[dim] = {"base_unit": _BASE_UNIT[dim], "unit_amount": _f(ch["amount"]),
                           "pack_count": ch["pack"], "total": _f(ch["amount"] * ch["pack"])}
    status = "ambiguous" if plus or "secondary_count_pack_ambiguous" in flags else "ok"
    if primary_dim == "oz_ambiguous":
        flags.append("plain_oz_ambiguous_mass_or_volume")
    return {
        "status": status,
        "primary_dim": primary_dim,
        "base_unit": _BASE_UNIT[primary_dim],
        "unit_amount": _f(prim["amount"]),
        "pack_count": prim["pack"],
        "total": _f(prim["amount"] * prim["pack"]),
        "alternates": alternates,
        "flags": sorted(set(flags)),
        "sources": sorted({m["src"] for ms in by_dim.values() for m in ms}),
    }


def quantity_usable(q: dict) -> bool:
    return bool(q) and q.get("status") == "ok" and q.get("total") is not None and q["total"] > 0


def comparable_dim(own_q: dict, comp_q: dict):
    """Dimension both sides share with the SAME dimension label (never g vs ml)."""
    if not (quantity_usable(own_q) and quantity_usable(comp_q)):
        return None
    dim = own_q["primary_dim"]
    if comp_q["primary_dim"] == dim:
        return dim
    alt = comp_q.get("alternates", {}).get(dim)
    if alt and alt.get("total"):
        return dim
    return None


def comp_total_for_dim(comp_q: dict, dim: str):
    if comp_q["primary_dim"] == dim:
        return comp_q["total"], comp_q["unit_amount"], comp_q["pack_count"]
    alt = comp_q["alternates"][dim]
    return alt["total"], alt["unit_amount"], alt["pack_count"]


def unit_price(price, total):
    p, t = _dec(price), _positive(total)
    if p is None or t is None:
        return None
    return p / t


# ---------------------------------------------------------------------------
# identity (same product / variant / formulation)
# ---------------------------------------------------------------------------

_STOP = {
    "the", "and", "for", "with", "by", "a", "of", "new", "x", "k", "beauty", "korean", "korea",
    "facial", "boosting", "first", "skincare", "skin", "care", "cosmetics", "cosmetic",
    "pack", "ea", "ct", "pcs", "fl", "oz", "ml", "g", "official",
}
TYPE_WORDS = {
    "ampoule", "serum", "essence", "cream", "mask", "toner", "lotion", "gel", "mist", "oil", "balm",
    "cleanser", "wash", "pad", "patch", "sunscreen", "cushion", "foundation", "tint", "lipstick",
    "moisturizer", "capsule", "sheet", "bar", "treatment",
}
_MULTI_OPTION_RE = re.compile(r"\[\s*\d+\s*(?:options?|shades?|types?|colors?|colours?)\s*\]", re.IGNORECASE)
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_TOKEN_RE = re.compile(r"[a-z0-9가-힣]+")


def _stem(tok: str) -> str:
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _strip_measures(text: str) -> str:
    """Remove 'N unit', its pack tail ('x 6', '6개입') and a pack head ('2 x ')."""
    pieces, last, consumed = [], 0, 0
    for m in _MEASURE_RE.finditer(text):
        if m.start() < consumed:
            continue
        start, end = m.start(), m.end()
        pm = _PACK_AFTER_RE.match(text, end)
        if pm:
            end = pm.end()
        else:
            pre = _PACK_BEFORE_RE.search(text[:start])
            if pre:
                start = pre.start()
        if start < last:
            start = last
        pieces.append(text[last:start])
        pieces.append(" ")
        last = consumed = end
    pieces.append(text[last:])
    return "".join(pieces)


def identity_tokens(title, brand=None) -> dict:
    text = " ".join(x for x in (brand, title) if isinstance(x, str) and x.strip())
    multi = bool(_MULTI_OPTION_RE.search(text))
    text = _BRACKET_RE.sub(" ", text.replace("\xa0", " "))
    text = _strip_measures(text.lower())
    tokens = {_stem(t) for t in _TOKEN_RE.findall(text)}
    tokens = {t for t in tokens if t and t not in _STOP}
    return {"tokens": sorted(tokens), "multi_option": multi}


def identity_match(own_tokens, comp_tokens) -> bool:
    """Same brand/line/variant. Type words may be missing on ONE side, never different."""
    own, comp = set(own_tokens), set(comp_tokens)
    own_core, comp_core = own - TYPE_WORDS, comp - TYPE_WORDS
    if len(own_core) < 2 or own_core != comp_core:
        return False
    own_t, comp_t = own & TYPE_WORDS, comp & TYPE_WORDS
    if own_t and comp_t and own_t != comp_t:
        return False
    return True


def near_miss(own_tokens, comp_tokens) -> list:
    """Overlapping but NOT the same product/variant. Returns differing tokens (info only)."""
    own, comp = set(own_tokens) - TYPE_WORDS, set(comp_tokens) - TYPE_WORDS
    if not own or not comp:
        return []
    jac = len(own & comp) / len(own | comp)
    if jac >= 0.5 and own != comp:
        return sorted(own ^ comp)
    return []


# ---------------------------------------------------------------------------
# margin advisory (never blocks)
# ---------------------------------------------------------------------------

_RISK_ORDER = {"negative_margin": 4, "below_advisory_floor": 3, "below_target_margin": 2, "ok": 1, "unknown": 0}


def _q2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def margin_scenario(price_usd, landed_cost_usd, fee_rate, floor_margin_pct=None, floor_net_usd=None,
                    target_margin_pct=None) -> dict:
    price, landed, rate = _positive(price_usd), _dec(landed_cost_usd), _dec(fee_rate)
    if price is None or landed is None or rate is None:
        return {"status": "unknown_missing_inputs", "risk": "unknown", **profit_flags()}
    fee = _q2(price * rate)
    net = price - landed - fee
    margin = net / price * 100
    risk = "ok"
    if net <= 0:
        risk = "negative_margin"
    else:
        fm, fn = _dec(floor_margin_pct), _dec(floor_net_usd)
        if (fm is not None and margin < fm) or (fn is not None and net < fn):
            risk = "below_advisory_floor"
        elif _dec(target_margin_pct) is not None and margin < _dec(target_margin_pct):
            risk = "below_target_margin"
    return {"status": "computed", **profit_flags(), "price_usd": _f(price, 2), "landed_cost_usd": _f(landed, 2),
            "fee_usd": _f(fee, 2), "net_profit_usd": _f(net, 2), "margin_pct": _f(margin, 1), "risk": risk}


def margin_advisory(price_usd, price_source, product_cost_usd, scenarios, fee_rate, floors, weight_estimated=False) -> dict:
    """scenarios: {name: landed_cost_usd or None}. Always blocking=False (user waived).

    The target margin gets the config's extra points when the shipping weight is only estimated."""
    floor_m, floor_n = floors.get("min_margin_pct"), floors.get("min_net_profit_usd")
    target = _dec(floors.get("target_margin_pct"))
    if target is not None and weight_estimated and _dec(floors.get("estimated_weight_extra_margin_pct")) is not None:
        target += _dec(floors.get("estimated_weight_extra_margin_pct"))
    out = {"blocking": False, **profit_flags(), "waiver": "user_waived_margin_block", "advisory_floor": floors,
           "weight_estimated": bool(weight_estimated), "effective_target_margin_pct": _f(target, 2) if target is not None else None,
           "basis_price_usd": _f(price_usd, 2) if _positive(price_usd) else None, "price_source": price_source,
           "scenarios": {}, "risk": "unknown", "risk_basis": "unknown"}
    worst, any_computed = "unknown", False
    for name, landed in scenarios.items():
        sc = margin_scenario(price_usd, landed, fee_rate, floor_m, floor_n, target)
        out["scenarios"][name] = sc
        if sc["status"] == "computed":
            any_computed = True
            if _RISK_ORDER[sc["risk"]] > _RISK_ORDER[worst]:
                worst = sc["risk"]
    if any_computed:
        out["risk"], out["risk_basis"] = worst, "computed_landed_cost"
        return out
    price, cost, rate = _positive(price_usd), _positive(product_cost_usd), _dec(fee_rate)
    if price is not None and cost is not None and rate is not None:
        upper = (price - _q2(price * rate) - cost) / price * 100
        out["upper_bound_margin_pct_excluding_shipping_and_tariff"] = _f(upper, 1)
        if upper <= 0:
            out["risk"], out["risk_basis"] = "negative_margin", "upper_bound_certain"
        elif _dec(floor_m) is not None and upper < _dec(floor_m):
            out["risk"], out["risk_basis"] = "below_advisory_floor", "upper_bound_certain"
        else:
            out["risk_basis"] = "landed_cost_missing"
    else:
        out["risk_basis"] = "price_or_cost_missing"
    return out


# ---------------------------------------------------------------------------
# market comparators
# ---------------------------------------------------------------------------

MARKET_SPECS = (
    {"id": "oliveyoung_us", "file": "oliveyoung_us_products.json", "channel": "oliveyoung_us",
     "title": "product", "brand": "brand", "item_id": ("product_id", "url"), "soldout": "is_soldout", "currency": "currency"},
    {"id": "sokoglam_us", "file": "sokoglam_products.json", "channel": "sokoglam_us",
     "title": "name", "brand": "brand", "item_id": ("url",)},
    {"id": "us_beauty_retail", "file": "us_beauty_products.json", "channel": None,
     "title": "title", "brand": "brand", "item_id": ("url",), "store_channels": {"Ulta": "ulta_beauty", "Sephora": "sephora"}},
    {"id": "walmart_beauty", "file": "walmart_products.json", "channel": "walmart_beauty",
     "title": "name", "brand": None, "item_id": ("item_id", "url")},
    {"id": "amazon_best_sellers", "file": "amazon_products.json", "channel": "amazon_best_sellers",
     "title": "name", "brand": None, "item_id": ("asin", "url")},
    {"id": "amazon_new_beauty", "file": "amazon_new_products.json", "channel": "amazon_new_beauty",
     "title": "name", "brand": None, "item_id": ("asin", "url")},
    {"id": "amazon_movers_beauty", "file": "amazon_movers_products.json", "channel": "amazon_movers_beauty",
     "title": "name", "brand": None, "item_id": ("asin", "url")},
    {"id": "tiktok_shop_us", "file": "tiktok_shop_us_products.json", "channel": "tiktok_shop_us",
     "title": "product", "brand": None, "item_id": ("product",)},
)


def normalize_market(docs: dict, candidate_comparison, as_of: datetime, max_age_hours: float):
    """-> (sources list, items list). A source is `verified` only with positive evidence:
    fresh + not flagged stale + present in candidate_comparison and NOT in its
    excluded_market_sources."""
    excluded = None
    if isinstance(candidate_comparison, dict) and isinstance(candidate_comparison.get("excluded_market_sources"), dict):
        excluded = candidate_comparison["excluded_market_sources"]
    sources, items = [], []
    for spec in MARKET_SPECS:
        doc = docs.get(spec["id"])
        if not isinstance(doc, dict):
            sources.append({"source_id": spec["id"], "present": False, "verified": False,
                            "reasons": ["source_file_missing_or_unreadable"], "items_total": 0, "items_priced": 0})
            continue
        fresh = assess_freshness(doc.get("collected_at"), as_of, max_age_hours)
        rows = doc.get("products") if isinstance(doc.get("products"), list) else []
        base_reasons = []
        if fresh["state"] == "invalid":
            base_reasons.append("collected_at_invalid")
        elif fresh["state"] == "stale":
            base_reasons.append("stale_by_age")
        if doc.get("is_stale") is True:
            base_reasons.append("source_marked_stale")
        priced = 0
        channel_state = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            channel = spec["channel"]
            if spec.get("store_channels"):
                channel = spec["store_channels"].get(row.get("store"), "unknown_store")
            price = _positive(row.get("price_usd"))
            if price is not None:
                priced += 1
            if channel not in channel_state:
                reasons = list(base_reasons)
                if excluded is None:
                    reasons.append("verification_evidence_missing")
                elif channel in excluded:
                    reasons.append(str(excluded[channel]))
                channel_state[channel] = reasons
            title = row.get(spec["title"])
            brand = row.get(spec["brand"]) if spec["brand"] else None
            ident = identity_tokens(title, brand)
            currency = str(row.get(spec.get("currency", "currency")) or "USD").upper() if spec.get("currency") or row.get("currency") else "USD"
            ship = _dec(row.get("shipping_usd"))
            if ship is not None and ship < 0:
                ship = None
            if row.get("free_shipping") is True:
                ship = Decimal(0)
            item_id = next((str(row[k]) for k in spec["item_id"] if row.get(k)), None)
            items.append({
                "source_id": spec["id"], "channel": channel, "item_id": item_id,
                "title": title if isinstance(title, str) else None, "brand": brand if isinstance(brand, str) else None,
                "price_usd": price, "currency": currency, "market": str(row.get("market") or doc.get("country") or "US").upper(),
                "soldout": bool(row.get(spec["soldout"])) if spec.get("soldout") else False,
                "shipping_usd": ship, "url": row.get("url"),
                "checkout_evidence": checkout_total_evidence(
                    row.get("checkout_quote"), item_id, price, ship, as_of),
                "tokens": ident["tokens"], "multi_option": ident["multi_option"],
                "quantity": parse_quantity([("title", title)]),
            })
        for channel, reasons in sorted(channel_state.items()):
            sources.append({
                "source_id": spec["id"] if channel == spec["channel"] else f"{spec['id']}:{channel}",
                "channel": channel, "present": True, "collected_at": doc.get("collected_at"),
                "age_hours": fresh["age_hours"], "verified": not reasons, "reasons": reasons,
                "items_total": sum(1 for i in items if i["source_id"] == spec["id"] and i["channel"] == channel),
                "items_priced": sum(1 for i in items if i["source_id"] == spec["id"] and i["channel"] == channel and i["price_usd"] is not None),
                "shipping_known_items": sum(1 for i in items if i["source_id"] == spec["id"] and i["channel"] == channel and i["shipping_usd"] is not None),
            })
        if not channel_state:
            sources.append({"source_id": spec["id"], "channel": spec["channel"], "present": True,
                            "collected_at": doc.get("collected_at"), "age_hours": fresh["age_hours"],
                            "verified": False, "reasons": base_reasons + ["no_items"], "items_total": len(rows), "items_priced": 0,
                            "shipping_known_items": 0})
    return sources, items


def _source_for(sources, item):
    for s in sources:
        if s.get("present") and s.get("channel") == item["channel"] and s["source_id"].split(":")[0] == item["source_id"]:
            return s
    return None


def evaluate_comparators(own_tokens, own_qty, own_has_identity, items, sources, own_market="US", cap=5,
                         tolerance=DEFAULT_VOLUME_TOLERANCE) -> dict:
    """Return tiers: qualified / provisional / reference_only plus rejection counts.

    qualified   : identity+unit match, verified fresh source and authenticated complete quote
    provisional : same, but quote provenance or shipping/tax/fees evidence incomplete
    reference_only : identity+unit match but stale/unverified source (never scored)
    """
    res = {"qualified": [], "provisional": [], "reference_only": [], "rejected_counts": {}, "near_misses": []}
    rej = Counter()
    if not own_has_identity:
        res["rejected_counts"] = {"own_english_identity_missing": len(items)}
        return res
    for it in items:
        if not identity_match(own_tokens, it["tokens"]):
            diff = near_miss(own_tokens, it["tokens"])
            if diff and len(res["near_misses"]) < cap:
                res["near_misses"].append({"source_id": it["source_id"], "title": it["title"], "price_usd": _f(it["price_usd"], 2),
                                            "differing_tokens": diff, "reason": "different_variant_or_formulation_not_compared"})
            rej["identity_mismatch"] += 1
            continue
        if it["multi_option"]:
            rej["multi_option_listing_price_unspecified"] += 1
            continue
        if it["price_usd"] is None:
            rej["price_missing_or_invalid"] += 1
            continue
        if it["currency"] != "USD":
            rej["currency_not_usd"] += 1
            continue
        if it["market"] != own_market:
            rej["market_mismatch"] += 1
            continue
        if it["soldout"]:
            rej["sold_out"] += 1
            continue
        dim = comparable_dim(own_qty, it["quantity"])
        if dim is None:
            rej["quantity_unknown_or_dimension_mismatch"] += 1
            continue
        total, unit_amount, pack_count = comp_total_for_dim(it["quantity"], dim)
        exact_pack = (_close(Decimal(str(total)), Decimal(str(own_qty["total"])), Decimal("0.0001"))
                      and pack_count == own_qty["pack_count"])
        within_tol = _close(Decimal(str(total)), Decimal(str(own_qty["total"])), Decimal(str(tolerance)))
        src = _source_for(sources, it) or {"verified": False, "reasons": ["source_unknown"]}
        rec = {"source_id": it["source_id"], "channel": it["channel"], "item_id": it["item_id"], "title": it["title"],
               "price_usd": _f(it["price_usd"], 2), "shipping_usd": _f(it["shipping_usd"], 2) if it["shipping_usd"] is not None else None,
               "delivered_price_usd": None, "item_shipping_subtotal_usd": None,
               "checkout_evidence": it["checkout_evidence"],
               "dimension": dim, "base_unit": _BASE_UNIT[dim], "comparator_total": total,
               "comparator_pack_count": pack_count,
               "basis": "exact_pack_total" if exact_pack else ("total_volume_within_tolerance" if within_tol else "per_unit_like_basis"),
               "volume_within_tolerance": within_tol,
               "unit_price_item": None, "unit_price_delivered": None, "url": it["url"]}
        rec["unit_price_item"] = _f(unit_price(it["price_usd"], total), 6)
        if it["shipping_usd"] is not None:
            rec["item_shipping_subtotal_usd"] = _f(it["price_usd"] + it["shipping_usd"], 2)
        if it["checkout_evidence"]["known"]:
            rec["delivered_price_usd"] = it["checkout_evidence"]["total_usd"]
            rec["unit_price_delivered"] = _f(unit_price(rec["delivered_price_usd"], total), 6)
        if not src.get("verified"):
            rec["not_used_because"] = sorted(src.get("reasons") or ["source_unverified"])
            res["reference_only"].append(rec)
        elif (it["shipping_usd"] is None or not it["checkout_evidence"]["known"]
              or not it["checkout_evidence"].get("source_verified")):
            rec["provisional_because"] = (
                (["market_shipping_unknown"] if it["shipping_usd"] is None else []) +
                ["market_" + reason for reason in it["checkout_evidence"]["reasons"]] +
                ["market_" + reason for reason in it["checkout_evidence"].get("source_reasons", [])])
            res["provisional"].append(rec)
        else:
            res["qualified"].append(rec)
    # Serialized unit prices are rounded for display only, never for decisions.
    key = lambda r: (unit_price(r["delivered_price_usd"] if r["delivered_price_usd"] is not None
                               else r["price_usd"], r["comparator_total"]),
                     r["source_id"], str(r["item_id"]))
    for tier in ("qualified", "provisional", "reference_only"):
        res[tier].sort(key=key)
    res["rejected_counts"] = dict(sorted(rej.items()))
    return res


def price_position(own: dict, own_qty: dict, tiers: dict, own_shipping_usd=None) -> dict:
    """Decide verified / provisional / unknown. Only `verified_*` may earn score points."""
    pos = {"status": "unknown", "verified": False, "reasons": [], "below_lowest": None, "gap_pct": None,
           "own_unit_price": None, "comparator_unit_price": None, "comparator": None, "base_unit": None, "basis": None,
           "comparison_scope": "observed_comparable_offers_only",
           "verified_cost_basis": "item_plus_standard_shipping_tax_and_mandatory_fees"}
    price = _positive(own.get("price_usd")) if own else None
    if price is None:
        pos["reasons"].append("own_price_missing")
        return pos
    if not quantity_usable(own_qty):
        pos["reasons"].append("own_quantity_unknown_or_conflicting")
        return pos
    q, p = tiers.get("qualified") or [], tiers.get("provisional") or []
    if not q and not p:
        pos["reasons"].append("no_qualified_or_provisional_comparator")
        if tiers.get("reference_only"):
            pos["reasons"].append("only_stale_or_unverified_reference_matches")
        return pos
    ship = _dec(own_shipping_usd)
    # live AND a fresh parseable observation timestamp; draft/model prices can never be verified
    own_live = own.get("kind") == "live" and own.get("live_fresh") is True
    own_checkout = own.get("checkout_evidence") or {"known": False, "reasons": ["checkout_quote_missing"]}
    exact = [x for x in q if x.get("basis") == "exact_pack_total"]
    qv = [x for x in exact if own_checkout.get("known") and own_checkout.get("source_verified") and
          (x.get("checkout_evidence") or {}).get("source_verified") and
          (x.get("checkout_evidence") or {}).get("destination_key") == own_checkout.get("destination_key")]
    verified = bool(qv) and own_live and ship is not None and ship >= 0 and own_checkout.get("known")
    reasons = []
    if q and not any(x.get("volume_within_tolerance") for x in q):
        reasons.append("comparator_size_outside_volume_tolerance")
    if q and not exact:
        reasons.append("comparator_exact_pack_required")
    if exact and own_checkout.get("known") and not qv:
        reasons.append("comparison_destination_mismatch")
    if not own_checkout.get("known"):
        reasons.extend("own_" + reason for reason in own_checkout["reasons"])
    if not own_checkout.get("source_verified"):
        reasons.extend("own_" + reason for reason in
                       own_checkout.get("source_reasons", ["checkout_source_provenance_unverified"]))
    if own.get("kind") != "live":
        reasons.append("own_price_not_live_listing")
    elif not own_live:
        reasons.append("own_live_price_observation_" + str((own.get("live_freshness") or {}).get("state") or "missing"))
    if ship is None:
        reasons.append("own_customer_shipping_unknown")
    if not q and any("market_shipping_unknown" in x.get("provisional_because", []) for x in p):
        reasons.append("market_shipping_unknown")
    if p:
        reasons.extend(sorted({reason for x in p for reason in x.get("provisional_because", [])
                               if reason != "market_shipping_unknown"}))
    if verified:
        best = qv[0]
        own_metric = unit_price(own_checkout["total_usd"], own_qty["total"])
        comp_metric = unit_price(best["delivered_price_usd"], best["comparator_total"])
        pos["basis"] = "delivered_" + best["basis"]
        # An incomplete quote whose item-only lower bound is already <= ours
        # could still be cheaper at checkout; no verified lowest claim then.
        incomplete = p + [x for x in q if x not in qv]
        cheaper_unknown = [x for x in incomplete if own_metric is not None
                           and unit_price(x["price_usd"], x["comparator_total"]) is not None
                           and unit_price(x["price_usd"], x["comparator_total"]) <= own_metric]
        if cheaper_unknown:
            verified = False
            reasons.append("cheaper_item_price_with_incomplete_checkout")
            if any("market_shipping_unknown" in x.get("provisional_because", []) for x in cheaper_unknown):
                reasons.append("cheaper_item_price_with_unknown_shipping")
    if not verified:
        best = min(q + p, key=lambda x: (unit_price(x["price_usd"], x["comparator_total"]),
                                         x["source_id"], str(x["item_id"])))
        own_metric = unit_price(price, own_qty["total"])
        comp_metric = unit_price(best["price_usd"], best["comparator_total"])
        pos["basis"] = "item_price_" + best["basis"]
    if own_metric is None or comp_metric is None or comp_metric <= 0:
        pos["reasons"] = reasons + ["comparator_metric_missing"]
        return pos
    below = own_metric < comp_metric
    gap = (comp_metric - own_metric) / comp_metric * 100
    pos.update({
        "status": ("verified_below" if below else "verified_not_below") if verified
        else ("provisional_below" if below else "provisional_not_below"),
        "verified": verified, "reasons": reasons, "below_lowest": below, "gap_pct": _f(gap, 2),
        "own_unit_price": _f(own_metric, 6), "comparator_unit_price": _f(comp_metric, 6),
        "base_unit": best["base_unit"],
        "comparator": {k: best.get(k) for k in ("source_id", "item_id", "title", "price_usd",
                                               "shipping_usd", "delivered_price_usd", "basis")},
    })
    return pos


# ---------------------------------------------------------------------------
# S gate audit / priority
# ---------------------------------------------------------------------------

def s_audit(rec: dict) -> dict:
    failed = []
    if rec.get("grade") != "S":
        return {"applies": False}
    if (_dec(rec.get("shopify_score")) or Decimal(0)) < S_MIN_SCORE:
        failed.append("score_below_82")
    if rec.get("bucket") not in S_CORE_BUCKETS:
        failed.append("non_core_bucket")
    if rec.get("s_rule") not in S_QUALIFYING_RULES:
        failed.append("s_rule_not_qualifying")
    if rec.get("downgrade_reason"):
        failed.append("downgrade_reason_present")
    if not rec.get("best_global_match"):
        failed.append("no_global_match")
    if _dec((rec.get("score_breakdown") or {}).get("penalty")) not in (None, Decimal(0)):
        failed.append("non_core_penalty")
    gate = us_gate_kind(rec.get("name"), (rec.get("score_breakdown") or {}).get("us_block_kind"))
    if gate:
        failed.append("us_legal_gate_" + gate)
    return {"applies": True, "original_grade": "S", "s_rule": rec.get("s_rule"), "s_rank": rec.get("s_rank"),
            "constraints_met": not failed, "failed_constraints": failed,
            "note": "audit only; the S gate is owned by scripts/daiso/score_shopify_demand.py"}


def priority_score(shopify_score, position: dict) -> dict:
    base = (_dec(shopify_score) or Decimal(0)) * Decimal("0.6")
    counted = Decimal(0)
    not_counted = Decimal(0)
    gap = _dec(position.get("gap_pct"))
    pts = Decimal(0)
    if position.get("below_lowest") and gap is not None and gap > 0:
        pts = Decimal(20) + min(Decimal(20), gap * Decimal("0.8"))
    status = "unknown_price_evidence"
    if position.get("status") == "verified_below":
        counted, status = pts, "verified_price_advantage"
    elif position.get("status") == "verified_not_below":
        status = "verified_no_price_advantage"
    elif str(position.get("status", "")).startswith("provisional"):
        not_counted, status = pts, "provisional_not_counted"
    return {"score": _f(base + counted, 2), "evidence_status": status,
            "components": {"demand_score_x0.6": _f(base, 2), "verified_price_points": _f(counted, 2),
                           "provisional_price_points_not_counted": _f(not_counted, 2)}}


# ---------------------------------------------------------------------------
# product-kind heuristics (bucket misfits)
# ---------------------------------------------------------------------------

NON_BEAUTY_EXTRA = ("아이워머", "장갑", "클립", "슬리퍼", "커피", "필터", "케이스", "렌치", "보관함", "안경", "스푼", "탈취",
                    "오피스", "그립", "멀티탭", "갤럭시", "맥세이프", "아이스크림")
BEAUTY_TOOL_HINTS = ("브러시", "브러쉬", "퍼프", "스펀지", "샤워볼", "때타월", "타월")


def product_kind(name: str, penalty) -> str:
    name = name or ""
    if (_dec(penalty) or Decimal(0)) > 0 or any(k in name for k in NON_BEAUTY_EXTRA):
        return "non_beauty_misfit"
    if any(k in name for k in BEAUTY_TOOL_HINTS):
        return "beauty_tool"
    return "formulation_or_unspecified"


# ---------------------------------------------------------------------------
# input loading
# ---------------------------------------------------------------------------

INPUT_FILES = (
    ("score", "daiso_real/shopify_demand_score.json", True),
    ("master", "product_master.json", False),
    ("gosi", "gosi.json", False),
    ("pricing_model", "pricing_model.json", False),
    ("registry", "shopify_daily_registry.json", False),
    ("queue", "shopify_action_queue.json", False),
    ("shopify_products", "shopify_products.json", False),
    ("market_team", "market_team.json", False),
    ("candidate_comparison", "daiso_real/candidate_comparison.json", False),
    ("serpapi", "serpapi_market.json", False),
    ("profitability", "daiso_real/profitability_rule.json", False),
    ("monthly_revenue", "monthly_revenue.json", False),
    ("commerce_config", "../config/daiso_commerce_strategy.json", False),
    ("mocra_business", "manual/mocra_business.json", False),
    ("manual_sephora", "manual/sephora_2026-09-01.json", False),
) + tuple((spec["id"], spec["file"], False) for spec in MARKET_SPECS)


def _first_ts(doc):
    if isinstance(doc, dict):
        for k in ("generated_at", "collected_at", "updated_at", "captured_at"):
            if isinstance(doc.get(k), str):
                return doc[k]
    return None


def _count(doc):
    if isinstance(doc, dict):
        for k in ("all_scored", "products", "items", "draft_actions"):
            if isinstance(doc.get(k), list):
                return len(doc[k])
        if isinstance(doc.get("pd_pairs"), dict):
            return len(doc["pd_pairs"])
    return None


def load_inputs(data_dir: Path, analytics_path=None):
    docs, status = {}, []
    for key, rel, required in INPUT_FILES:
        path = data_dir / rel
        entry = {"key": key, "path": rel, "required": required, "present": path.exists(), "loaded": False, "error": None,
                 "timestamp": None, "record_count": None}
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
                docs[key] = doc
                entry.update(loaded=True, timestamp=_first_ts(doc), record_count=_count(doc))
            except (OSError, ValueError) as exc:
                entry["error"] = f"unreadable_json:{type(exc).__name__}"
        status.append(entry)
    if analytics_path:
        p = Path(analytics_path)
        entry = {"key": "analytics", "path": str(p), "required": False, "present": p.exists(), "loaded": False,
                 "error": None, "timestamp": None, "record_count": None}
        if p.exists():
            try:
                doc = json.loads(p.read_text(encoding="utf-8-sig"))
                docs["analytics"] = doc
                entry.update(loaded=True, timestamp=_first_ts(doc),
                             record_count=len(doc.get("observations", [])) if isinstance(doc, dict) else None)
            except (OSError, ValueError) as exc:
                entry["error"] = f"unreadable_json:{type(exc).__name__}"
        status.append(entry)
    # Only actual scoped file/hash/adequacy checks supply safety coverage.
    rows = (docs.get("score") or {}).get("all_scored", [])
    ids = {str(row.get("pd_no")) for row in rows if isinstance(row, dict) and row.get("pd_no") is not None}
    docs["manufacturer_safety_record_views"] = {pd: safety_public_view(
        manufacturer_safety_record(pd, Path(data_dir).parent)) for pd in ids}
    return docs, status


# ---------------------------------------------------------------------------
# own-price evidence
# ---------------------------------------------------------------------------

OWN_KIND_RANK = {"live": 0, "draft_payload": 1, "model_recommended": 2}
# A live own price may only earn a verified advantage with a parseable, fresh OBSERVATION timestamp.
# A date-only value (the registry's `date`) never counts. Item-level fields win over registry-level ones.
OWN_LIVE_ITEM_TS_KEYS = ("price_observed_at", "observed_at", "verified_at", "checked_at")
OWN_LIVE_REGISTRY_TS_KEYS = ("snapshot_at", "generated_at", "captured_at", "updated_at")
DEFAULT_OWN_LIVE_MAX_AGE_HOURS = 24.0


def live_price_freshness(observed_at, as_of: datetime, max_age_hours: float = DEFAULT_OWN_LIVE_MAX_AGE_HOURS) -> dict:
    """state: fresh | stale | missing | invalid | future. Only `fresh` may support a verified claim.

    missing: no value; invalid: unparseable or date-only; future: more than 5 minutes after as_of;
    stale: older than max_age_hours (exactly max_age_hours is still fresh). Naive timestamps are UTC."""
    if observed_at is None or (isinstance(observed_at, str) and not observed_at.strip()):
        return {"state": "missing", "age_hours": None, "observed_at": None}
    parsed = parse_ts(observed_at)
    if parsed is None:
        return {"state": "invalid", "age_hours": None, "observed_at": None}
    delta = as_of - parsed
    if delta < -FUTURE_SKEW:
        return {"state": "future", "age_hours": None, "observed_at": iso(parsed)}
    age = max(0.0, delta.total_seconds() / 3600.0)
    return {"state": "fresh" if age <= max_age_hours else "stale", "age_hours": round(age, 2), "observed_at": iso(parsed)}


def collect_own_prices(registry, queue, pricing_model) -> dict:
    """pd_no -> {candidates, inactive}. Only qty-1 prices. Never fabricated."""
    out = defaultdict(lambda: {"candidates": [], "inactive": [], "english_titles": [], "registry_size": None})
    if isinstance(registry, dict):
        for it in registry.get("items") or []:
            pd = str(it.get("pd_no") or "")
            if not pd:
                continue
            status = str(it.get("status") or "")
            price = _positive(it.get("single_usd"))
            if it.get("title"):
                out[pd]["english_titles"].append(("registry_title", str(it["title"])))
            if isinstance(it.get("size"), dict):
                out[pd]["registry_size"] = it["size"]
            if status.upper() == "ACTIVE" and price is not None:
                ts, ts_src = None, None
                for k in OWN_LIVE_ITEM_TS_KEYS:
                    if it.get(k) not in (None, ""):
                        ts, ts_src = it.get(k), "item:" + k
                        break
                if ts_src is None:
                    for k in OWN_LIVE_REGISTRY_TS_KEYS:
                        if registry.get(k) not in (None, ""):
                            ts, ts_src = registry.get(k), "registry_snapshot:" + k
                            break
                out[pd]["candidates"].append({"kind": "live", "price_usd": _f(price, 2), "source": "shopify_daily_registry.json",
                                              "_checkout_quote": it.get("checkout_quote"), "_checkout_item_id": pd,
                                              "observed_at": ts, "observed_at_source": ts_src,
                                              "status": status, "observed_on": it.get("date"),
                                              "quarantine_reasons": list(it.get("quarantine_reasons") or []),
                                              "unverified_references": {"shop_com_lowest_usd": it.get("shop_com_lowest_usd"),
                                                                        "pack_usd_qty_unspecified": it.get("pack_usd")}})
            else:
                out[pd]["inactive"].append({"status": status, "note": it.get("note")})
    if isinstance(queue, dict):
        for act in queue.get("draft_actions") or []:
            payload = act.get("immutablePayload") or {}
            for prod in payload.get("products") or []:
                pd = str(prod.get("pd_no") or "")
                price = _positive(prod.get("Variant Price"))
                if not pd:
                    continue
                if prod.get("Title"):
                    out[pd]["english_titles"].append(("draft_title", str(prod["Title"])))
                if price is not None:
                    out[pd]["candidates"].append({"kind": "draft_payload", "price_usd": _f(price, 2), "source": "shopify_action_queue.json",
                                                  "status": str(prod.get("Status") or ""), "observed_on": queue.get("generated_at")})
    offers = (pricing_model or {}).get("offers_by_product") if isinstance(pricing_model, dict) else None
    if isinstance(offers, dict):
        for off in offers.get("single") or []:
            pd = str(off.get("pd_no") or "")
            price = _positive(off.get("price_usd"))
            if pd and price is not None and off.get("qty") == 1:
                out[pd]["candidates"].append({"kind": "model_recommended", "price_usd": _f(price, 2), "source": "pricing_model.json",
                                              "status": "recommendation_not_a_listing", "observed_on": pricing_model.get("generated_at")})
    return out


def select_own_price(entry) -> dict:
    cands = sorted(entry["candidates"], key=lambda c: (OWN_KIND_RANK[c["kind"]], c["price_usd"]))
    if not cands:
        return {"status": "missing", "kind": None, "price_usd": None, "source": None, "candidates": [], "conflict": False}
    best = cands[0]
    values = sorted({c["price_usd"] for c in cands})
    conflict = len(values) > 1 and (values[-1] - values[0]) > 0.005
    return {"status": best["kind"], "kind": best["kind"], "price_usd": best["price_usd"], "source": best["source"],
            "candidates": cands, "conflict": conflict, "observed_at": best.get("observed_at"),
            "observed_at_source": best.get("observed_at_source"),
            "_checkout_quote": best.get("_checkout_quote"), "_checkout_item_id": best.get("_checkout_item_id")}


# ---------------------------------------------------------------------------
# analytics / review plan
# ---------------------------------------------------------------------------

REVIEW_METRICS = ("sessions", "product_views", "add_to_cart", "orders", "units", "revenue_usd")


def _metric_value(obs, key):
    v = obs.get(key) if isinstance(obs, dict) else None
    d = _dec(v)
    if d is None or d < 0:
        return UNKNOWN
    return _f(d, 2) if key == "revenue_usd" else (int(d) if d == d.to_integral_value() else _f(d, 2))


def product_analytics(analytics, pd_no, window_hours=DEFAULT_REVIEW_WINDOW_HOURS):
    """Latest valid ~24h product-level observation or None. Missing metrics -> UNKNOWN."""
    if not isinstance(analytics, dict):
        return None
    best = None
    for obs in analytics.get("observations") or []:
        if not isinstance(obs, dict) or str(obs.get("pd_no") or "") != pd_no:
            continue
        start, end = parse_ts(obs.get("window_start")), parse_ts(obs.get("window_end"))
        if start is None or end is None or end <= start:
            continue
        hours = (end - start).total_seconds() / 3600.0
        if abs(hours - window_hours) > 1.0:
            continue
        if best is None or end > best[0]:
            best = (end, start, obs)
    if best is None:
        return None
    end, start, obs = best
    return {"window_start": iso(start), "window_end": iso(end), "source": obs.get("source") or UNKNOWN,
            "metrics": {k: _metric_value(obs, k) for k in REVIEW_METRICS}}


def build_review_plan(products, analytics, analytics_status, monthly_revenue, window_hours=DEFAULT_REVIEW_WINDOW_HOURS):
    entries = []
    obs_found = 0
    for p in products:
        own = p["own_price"]
        if own["status"] not in ("live", "draft_payload"):
            continue
        live = own["status"] == "live"
        found = product_analytics(analytics, p["pd_no"], window_hours) if live else None
        if found:
            obs_found += 1
        entries.append({
            "pd_no": p["pd_no"], "category": p["category"], "grade": p["grade"],
            "own_price_status": own["status"], "own_price_usd": own["price_usd"],
            "review_applicable": live,
            "not_applicable_reason": None if live else "draft_payload_is_not_a_live_listing",
            "price_change_anchor_at": UNKNOWN,
            "anchor_note": "registry holds a date only; supply an exact price-change/publish timestamp to anchor the 24h window",
            "observation": found,
            "metrics": found["metrics"] if found else {k: UNKNOWN for k in REVIEW_METRICS},
            "evidence_requirements": [
                "product-level Shopify analytics export (sessions, views, add-to-cart, orders, units) for the exact 24h window",
                "price in force during the window (price history entry with timestamp)",
                "explicit confirmation that no other price/promo/ad change happened in the window, or a list of what changed",
            ],
        })
    store = UNKNOWN
    if isinstance(monthly_revenue, dict) and isinstance(monthly_revenue.get("last_month"), dict):
        store = {"label": monthly_revenue["last_month"].get("label"),
                 "orders": monthly_revenue["last_month"].get("orders") if monthly_revenue["last_month"].get("orders") is not None else UNKNOWN,
                 "revenue_usd": monthly_revenue["last_month"].get("revenue_usd") if monthly_revenue["last_month"].get("revenue_usd") is not None else UNKNOWN,
                 "level": "store_monthly_not_product_level"}
    return {
        "status": "plan_only_not_executed",
        "window_hours": window_hours,
        "analytics_input": {"provided": analytics is not None, "path": analytics_status.get("path") if analytics_status else None,
                            "loaded": bool(analytics_status and analytics_status.get("loaded")),
                            "product_level_observations_used": obs_found},
        "missing_metric_policy": f"a metric that is absent, null, negative or non-numeric is reported as the string \"{UNKNOWN}\", never as 0",
        "causality_policy": "A 24h before/after view cannot show that a price change caused any order or traffic change. Report observations only; do not promise sales effects.",
        "store_level_context": store,
        "read_plan": [
            "T0: record exact timestamp, price in force, and live/draft state of each listing",
            "T+24h: read product-level sessions, product views, add-to-cart, orders, units for the same window",
            "Report each metric as observed or UNKNOWN; flag any concurrent ad/promo/stock change as a confounder",
        ],
        "products": entries,
    }


# ---------------------------------------------------------------------------
# team work plan (proposals only)
# ---------------------------------------------------------------------------

def _task(task_id, title, gaps, evidence):
    return {"task_id": task_id, "title": title, "state": "input_required" if gaps else "proposed",
            "blocked_on": list(gaps), "evidence_required": list(evidence)}


def build_team_plan(cov: dict) -> dict:
    teams = []

    def team(name, tasks):
        teams.append({"team": name, "state": "input_required" if any(t["state"] == "input_required" for t in tasks) else "proposed",
                      "tasks": tasks})

    team("sourcing", [
        _task("sourcing-1", "Confirm exact size / pack contents and stock for priority products",
              (["gosi_volume_missing_for_%d_products" % cov["quantity_unknown"]] if cov["quantity_unknown"] else []) +
              (["quantity_conflict_for_%d_products" % cov["quantity_conflict"]] if cov["quantity_conflict"] else []),
              ["Daiso detail page / gosi volume text per pd_no", "unit weight in grams (measured) for landed-cost accuracy",
               "in-stock evidence with timestamp"]),
    ])
    team("market", [
        _task("market-1", "Collect fresh US standard-delivery totals for the exact product and pack",
              (["no_verified_fresh_market_source"] if cov["verified_market_sources"] == 0 else []) +
              (["market_shipping_not_recorded_by_any_source"] if cov["market_shipping_known_items"] == 0 else []) +
              (["market_complete_checkout_quote_missing"] if not cov.get("market_checkout_known_items") else []) +
              (["market_checkout_source_provenance_unverified"] if not cov.get("market_checkout_verified_items") else []),
              ["listing URL + capture timestamp", "exact variant/strength/size on the page", "shipping cost or free-shipping statement to US",
               "explicit tax and mandatory fees, including evidenced zeroes; standard shipping; same non-customer destination key",
               "seller identity; sold-out state"]),
    ])
    team("pricing", [
        _task("pricing-1", "Reconcile conflicting own prices and set customer shipping policy",
              (["own_price_conflicts_in_%d_products" % cov["own_price_conflicts"]] if cov["own_price_conflicts"] else []) +
              (["own_customer_shipping_policy_unknown"] if not cov["own_shipping_known"] else []) +
              (["own_complete_checkout_quote_missing"] if not cov.get("own_checkout_known_products") else []) +
              (["own_checkout_source_provenance_unverified"] if not cov.get("own_checkout_verified_products") else []) +
              (["own_live_price_observation_not_fresh_for_%d_products" % cov["own_live_not_fresh"]] if cov.get("own_live_not_fresh") else []) +
              (["duty_mode_ddu_vs_ddp_unconfirmed"] if cov["duty_mode_unconfirmed"] else []),
              ["live Shopify price + shipping rate table", "price-bound quote with explicit tax and mandatory fees for a non-customer US test destination",
               "DDU/DDP confirmation from Markets settings", "landed-cost sheet per product (weight-based)"]),
        _task("pricing-2", "Review negative / below-floor margin advisories (advisory only, margin block waived)",
              [], ["landed cost scenario used", "standing user margin-waiver policy + profitability warning (no new approval for margin alone)"]),
    ])
    team("listing", [
        _task("listing-1", "Carry exact unit, pack count and total into titles/variants; add English identity for products that lack one",
              (["english_identity_missing_for_%d_products" % cov["english_identity_missing"]] if cov["english_identity_missing"] else []),
              ["English title with brand, line, variant and size", "gosi-backed size statement", "variant mapping (e.g. strength 100 vs 300) kept separate"]),
    ])
    team("legal", [
        _task("legal-1", "Review live listings that still carry quarantine/legal hard-block reasons",
              (["live_listing_with_quarantine_reasons_%d" % cov["live_with_quarantine"]] if cov["live_with_quarantine"] else []) +
              (["manufacturer_safety_record_missing_for_%d_S_products" % cov["safety_record_missing_s"]] if cov.get("safety_record_missing_s") else []),
              ["legal_full / listing_gate result per live pd_no", "label and claim review", "responsible-person / MoCRA status evidence"]),
    ])
    team("design", [
        _task("design-1", "Pack-structure visuals (unit size x count = total) and price-comparison-safe imagery",
              [], ["approved size/pack facts from listing", "image rights evidence"]),
    ])
    team("channels", [
        _task("channels-1", "Choose channels only after a verified price position exists",
              (["no_verified_price_position"] if cov["positions_verified"] == 0 else []),
              ["verified price position per product", "channel fee and shipping terms"]),
    ])
    team("knowledge", [
        _task("knowledge-1", "File the evidence ledger (sources, timestamps, rejected comparators) in the knowledge base",
              [], ["this report path + generated input list", "reviewer name and date once reviewed"]),
    ])
    team("graph", [
        _task("graph-1", "Link product -> own price -> comparator -> source nodes in the artifact graph",
              [], ["stable node ids (pd_no / canonical_product_id)", "source file + timestamp per edge"]),
    ])
    return {
        "status": "proposed_not_started",
        "receipt_policy": "No handoff, approval or completion receipt exists or is implied. States are limited to proposed / input_required.",
        "receipts": {"handoff": None, "approval": None, "completion": None},
        "teams": teams,
    }


# ---------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------

def _gosi_volume(gosi, pd_no):
    items = (gosi or {}).get("items") if isinstance(gosi, dict) else None
    if isinstance(items, dict) and isinstance(items.get(pd_no), dict):
        v = items[pd_no].get("volume")
        return v if isinstance(v, str) and v.strip() else None
    return None


def _fee_rate(pricing_model):
    basis = (pricing_model or {}).get("cost_basis") or {}
    if "payment_fee_rate" in basis:
        value = basis["payment_fee_rate"]
        rate = _dec(value) if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else None
        return rate if rate is not None and 0 <= rate < 1 else None
    text = str(basis.get("payment_fee") or "")
    m = re.search(r"=\s*(\d+(?:\.\d+)?)\s*%", text)
    return Decimal(m.group(1)) / 100 if m else None


def _landed(pricing_model):
    out = {}
    sc = (pricing_model or {}).get("scenarios") if isinstance(pricing_model, dict) else None
    if not isinstance(sc, dict):
        return out
    for name, key in (("1개_묶음배송", "ship_1_unit_order"), ("2개_묶음배송", "ship_2_unit_order")):
        for row in sc.get(name) or []:
            pd = str(row.get("pd_no") or "")
            val = row.get("landed_cost_ddu_usd", row.get("landed_cost_usd"))
            if pd and _dec(val) is not None:
                out.setdefault(pd, {})[key] = {"ddu": val, "ddp": row.get("landed_cost_ddp_usd"),
                                               "weight_g_est": row.get("weight_g_est"), "weigh_needed": row.get("weigh_needed"),
                                               "weight_estimated": row.get("weight_source") != "measured" or bool(row.get("weigh_needed"))}
    return out


def serp_reference_basis(sp: dict, own_qty: dict, age_hours, rule: dict, tolerance=DEFAULT_VOLUME_TOLERANCE) -> dict:
    """Config-aligned SerpApi *reference price basis* (factor x median). Never a market-lowest claim.

    Needs: enough samples, age within max_age_days, and a query whose parsed total volume matches the
    product within tolerance in the same base unit. Unknown volume on either side rejects the evidence."""
    min_n = int(_dec(rule.get("min_sample")) or 5)
    max_days = _dec(rule.get("max_age_days")) or Decimal(30)
    factor = _dec(rule.get("price_factor")) or Decimal("0.95")
    reasons = []
    n = _dec(sp.get("n"))
    if n is None or n < min_n:
        reasons.append("sample_below_minimum")
    if age_hours is None or Decimal(str(age_hours)) > max_days * 24:
        reasons.append("older_than_max_age_days")
    q = parse_quantity([("serp_query", sp.get("query"))])
    if not quantity_usable(own_qty):
        reasons.append("product_volume_unknown")
    elif not quantity_usable(q):
        reasons.append("comparison_volume_unknown")
    else:
        dim = comparable_dim(own_qty, q)
        if dim is None:
            reasons.append("volume_dimension_mismatch")
        else:
            total, _u, _p = comp_total_for_dim(q, dim)
            if not _close(Decimal(str(total)), Decimal(str(own_qty["total"])), Decimal(str(tolerance))):
                reasons.append("volume_outside_tolerance")
    median = _positive(sp.get("median_usd"))
    if median is None:
        reasons.append("median_missing")
    out = {"eligible": not reasons, "reasons": reasons, "factor": _f(factor, 4),
           "claim": "reference_price_basis_only", "used_for_priority_score": False,
           "reference_basis_price_usd": None}
    if not reasons:
        out["reference_basis_price_usd"] = _f(median * factor, 2)
    return out


def build_strategy(docs: dict, file_status: list, as_of: datetime, max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
                   own_shipping_usd=None, analytics_status=None) -> dict:
    score = docs["score"]
    all_scored = [r for r in score.get("all_scored", []) if isinstance(r, dict)]
    master = {str(p.get("pd_no")): p for p in (docs.get("master") or {}).get("products", []) if isinstance(p, dict)}
    pricing_model = docs.get("pricing_model") or {}
    fx = _positive((pricing_model.get("exchange_rate") or {}).get("usd_to_krw"))
    fee_rate = _fee_rate(pricing_model)
    prof = docs.get("profitability") or {}
    cfg = parse_category_config(docs.get("commerce_config"))
    b2t, tag_order = cfg["bucket_to_tag"], cfg["order"]
    pp = cfg["price_policy"]
    ma = pp.get("margin_advisory") or {}
    tol = _dec((pp.get("volume_comparison") or {}).get("tolerance"))
    tolerance = tol if tol is not None and 0 <= tol < 1 else DEFAULT_VOLUME_TOLERANCE
    serp_rule = ((pp.get("price_evidence") or {}).get("sources") or {}).get("serpapi_google_shopping") or {}
    live_rule = ((pp.get("price_evidence") or {}).get("sources") or {}).get("shop_com_live_comparable") or {}
    live_days = _dec(live_rule.get("max_age_days"))
    own_live_max_hours = float(live_days * 24) if live_days is not None and live_days > 0 else DEFAULT_OWN_LIVE_MAX_AGE_HOURS

    def _pct(v):
        d = _dec(v)
        return _f(d * 100, 2) if d is not None else None
    cfg_min = _pct(ma.get("minimum_margin"))
    prof_min = _f(prof.get("min_margin_pct"), 2) if _dec(prof.get("min_margin_pct")) is not None else None
    floors = {"min_margin_pct": cfg_min if cfg_min is not None else prof_min,
              "target_margin_pct": _pct(ma.get("target_margin")),
              "estimated_weight_extra_margin_pct": _pct(ma.get("estimated_weight_extra_margin")),
              "min_net_profit_usd": _f(prof.get("min_net_profit_usd"), 2) if _dec(prof.get("min_net_profit_usd")) is not None else None,
              "source": "config.price_policy.margin_advisory" + (" (builtin mirror)" if cfg["used_fallback"] else "") if cfg_min is not None
              else "daiso_real/profitability_rule.json"}
    safety_covered = {str(pd) for pd, view in (docs.get("manufacturer_safety_record_views") or {}).items()
                      if isinstance(view, dict) and view.get("covered") is True
                      and isinstance(view.get("evidence_digest"), str)
                      and re.fullmatch(r"[0-9a-f]{64}", view["evidence_digest"])}
    landed = _landed(pricing_model)
    own_all = collect_own_prices(docs.get("registry"), docs.get("queue"), pricing_model)
    mt_names = {str(r.get("pd_no")): r.get("name_en") for r in (docs.get("market_team") or {}).get("s_grade_priority", []) if isinstance(r, dict)}
    serp = {str(r.get("pd_no")): r for r in ((docs.get("serpapi") or {}).get("prices") or {}).get("items", []) if isinstance(r, dict)}
    serp_fresh = assess_freshness((docs.get("serpapi") or {}).get("generated_at"), as_of, max_age_hours)
    sources, items = normalize_market(docs, docs.get("candidate_comparison"), as_of, max_age_hours)

    name_count = Counter(r.get("name") for r in all_scored if r.get("bucket") in b2t)
    products = []
    for r in all_scored:
        bucket = r.get("bucket")
        # 2026-10-11 카테고리 전담팀: 점수 파일의 desk(다이소몰 카테고리 목록 기준)가 있으면 그 카테고리로 센다.
        tag = r.get("desk") if r.get("desk") in tag_order else b2t.get(bucket)
        if tag is None:
            continue
        pd = str(r.get("pd_no"))
        m = master.get(pd) or {}
        entry = own_all.get(pd) if pd in own_all else {"candidates": [], "inactive": [], "english_titles": [], "registry_size": None}
        titles = list(entry["english_titles"])
        if mt_names.get(pd):
            titles.append(("market_team_name_en", str(mt_names[pd])))
        name_en = titles[0][1] if titles else None
        qty_texts = [("name_ko", r.get("name")), ("gosi_volume", _gosi_volume(docs.get("gosi"), pd))]
        rs = entry.get("registry_size")
        if isinstance(rs, dict) and _positive(rs.get("unit")) is not None and rs.get("base") in ("ml", "g"):
            qty_texts.append(("registry_size", f"{rs['unit']}{rs['base']} x {int(rs.get('count') or 1)}"))
        qty = parse_quantity(qty_texts)
        ident = identity_tokens(name_en) if name_en else {"tokens": [], "multi_option": False}
        own = select_own_price(entry)
        own["checkout_evidence"] = checkout_total_evidence(
            own.pop("_checkout_quote", None), own.pop("_checkout_item_id", None),
            own["price_usd"], own_shipping_usd, as_of)
        for candidate in own["candidates"]:
            candidate.pop("_checkout_quote", None)
            candidate.pop("_checkout_item_id", None)
        if own["kind"] == "live":
            own["live_freshness"] = live_price_freshness(own.get("observed_at"), as_of, own_live_max_hours)
            own["live_fresh"] = own["live_freshness"]["state"] == "fresh"
        else:
            own["live_freshness"], own["live_fresh"] = None, False
        tiers = evaluate_comparators(ident["tokens"], qty, bool(name_en) and len(ident["tokens"]) >= 2, items, sources,
                                     tolerance=tolerance)
        position = price_position(own, qty, tiers, own_shipping_usd)

        krw = _positive(r.get("price_krw"))
        cost_usd = (krw / fx) if krw is not None and fx is not None else None
        land = landed.get(pd, {})
        scen = {k: v["ddu"] for k, v in land.items()}
        weight_estimated = any(v.get("weight_estimated", True) for v in land.values()) if land else True
        margin = margin_advisory(own["price_usd"], own["source"], cost_usd, scen, fee_rate, floors, weight_estimated)
        if own["price_usd"] is None:
            margin["risk_basis"] = "own_price_missing"

        kind = product_kind(r.get("name"), (r.get("score_breakdown") or {}).get("penalty"))
        included = kind != "non_beauty_misfit"
        pr = priority_score(r.get("shopify_score"), position) if included else \
            {"score": None, "evidence_status": "excluded_non_beauty_misfit", "components": {}}
        flags = []
        if kind != "formulation_or_unspecified":
            flags.append(kind)
        if own["conflict"]:
            flags.append("own_price_conflict")
        if any(c.get("quarantine_reasons") for c in own["candidates"] if c["kind"] == "live"):
            flags.append("live_listing_has_quarantine_reasons")
        if entry["inactive"]:
            flags.append("inactive_registry_entry_present")
        if name_count[r.get("name")] > 1:
            flags.append("duplicate_name_in_catalog")
        if m.get("grade") and m.get("grade") != r.get("grade"):
            flags.append("grade_differs_from_product_master")
        if krw is not None and krw > 20000:
            flags.append("daiso_price_outlier_review")
        gate = us_gate_kind(r.get("name"), (r.get("score_breakdown") or {}).get("us_block_kind"))
        if gate:
            flags.append("us_legal_gate_" + gate)
        if bucket == "선케어" or gate == "otc_drug":
            flags.append("suncare_otc_review_not_s_eligible")
        sp = serp.get(pd)
        agg = None
        if sp:
            agg = {"source": "serpapi_market.json (google_shopping aggregate)", "query": sp.get("query"), "sample_n": sp.get("n"),
                   "min_usd": sp.get("min_usd"), "median_usd": sp.get("median_usd"), "max_usd": sp.get("max_usd"),
                   "freshness": serp_fresh["state"], "age_hours": serp_fresh["age_hours"], "qualified": False,
                   "not_used_because": ["aggregate_not_item_level", "seller_variant_and_shipping_unknown"] +
                                       (["stale_by_age"] if serp_fresh["state"] != "fresh" else []),
                   "reference_basis": serp_reference_basis(sp, qty, serp_fresh["age_hours"], serp_rule, tolerance)}
        products.append({
            "pd_no": pd, "canonical_product_id": m.get("canonical_product_id") or r.get("canonical_product_id"),
            "name_ko": r.get("name"), "name_en": name_en, "category": tag, "bucket_ko": bucket,
            "category_daiso_name": cfg["tags"][tag]["daiso_name"],
            "reclassified_into_category_from_bucket": bucket if bucket != cfg["tags"][tag]["daiso_name"] else None,
            "us_legal_gate": gate or None,
            "manufacturer_safety_record_covered": pd in safety_covered,
            "grade": r.get("grade"), "grade_original": r.get("grade"), "grade_changed_by_this_report": False,
            "shopify_score": r.get("shopify_score"), "item_kind": kind, "included_in_priority": included,
            "s_gate_audit": s_audit(r),
            "daiso": {"price_krw": _f(krw, 0) if krw is not None else None, "usd_krw": _f(fx, 2) if fx is not None else None,
                      "product_cost_usd": _f(cost_usd, 2) if cost_usd is not None else None,
                      "landed_cost_usd_ddu": {k: v["ddu"] for k, v in land.items()} or None,
                      "landed_cost_usd_ddp": {k: v["ddp"] for k, v in land.items()} or None,
                      "weight_g_est": next((v["weight_g_est"] for v in land.values()), None)},
            "quantity": qty,
            "own_price": own,
            "market": {"english_identity_available": bool(name_en), "identity_tokens": ident["tokens"],
                       "qualified_lowest": tiers["qualified"][0] if tiers["qualified"] else None,
                       "provisional_lowest": tiers["provisional"][0] if tiers["provisional"] else None,
                       "tier_counts": {"qualified": len(tiers["qualified"]), "provisional": len(tiers["provisional"]),
                                       "reference_only": len(tiers["reference_only"])},
                       "reference_only": tiers["reference_only"][:3], "near_misses": tiers["near_misses"],
                       "rejected_counts": tiers["rejected_counts"], "aggregate_reference": agg},
            "price_position": position,
            "margin_advisory": margin,
            "profitability_risk": margin["risk"],
            "priority": pr,
            "variant_group": (m.get("variant") or {}).get("group_id") if (m.get("variant") or {}).get("group_id", "").startswith("VG-") else None,
            "flags": sorted(flags),
        })

    # ranking: original grade tier first so an A can never leapfrog an S.
    ranked = [p for p in products if p["included_in_priority"]]
    ranked.sort(key=lambda p: (GRADE_RANK.get(p["grade"], 9), -(p["priority"]["score"] or 0), p["pd_no"]))
    for i, p in enumerate(ranked, 1):
        p["priority_rank"] = i
    for p in products:
        p.setdefault("priority_rank", None)
    products.sort(key=lambda p: (tag_order.index(p["category"]), GRADE_RANK.get(p["grade"], 9), p["pd_no"]))

    # advisory preview of config grade policy + legal pre-gates (the live selector stays the authority)
    for p in products:
        allowed = cfg["tags"][p["category"]]["allowed_grades"] or list(cfg["grade_policy"].get("allowed_grades") or [])
        blocked = []
        if p["grade"] not in allowed:
            blocked.append("grade_not_allowed_by_config")
        if not p["included_in_priority"]:
            blocked.append("non_beauty_misfit")
        if p["s_gate_audit"].get("applies") and not p["s_gate_audit"]["constraints_met"]:
            blocked.extend("s_gate_" + x for x in p["s_gate_audit"]["failed_constraints"])
        if p["us_legal_gate"] and not any(b.startswith("s_gate_us_legal") for b in blocked):
            blocked.append("us_legal_gate_" + p["us_legal_gate"])
        if not p["manufacturer_safety_record_covered"]:
            blocked.append("manufacturer_safety_record_missing")
        if p["own_price"]["status"] == "missing" and not ((p["market"]["aggregate_reference"] or {}).get("reference_basis") or {}).get("eligible"):
            blocked.append("price_evidence_missing")
        p["live_selection_preview"] = {"eligible_by_grade_and_gates": not [b for b in blocked if b != "manufacturer_safety_record_missing"
                                                                           and b != "price_evidence_missing"],
                                       "all_blockers": sorted(set(blocked)),
                                       "note": "advisory preview; margin never appears as a blocker (hard block removed by user authorization)"}

    # grade preservation proof
    src_grade = {str(r.get("pd_no")): r.get("grade") for r in all_scored}
    grade_changes = [p["pd_no"] for p in products if p["grade"] != src_grade.get(p["pd_no"])]
    s_all = [r for r in all_scored if r.get("grade") == "S"]
    s_three = [p for p in products if p["grade"] == "S"]
    s_uncovered = [str(r.get("pd_no")) for r in s_all if r.get("bucket") not in b2t and r.get("desk") not in tag_order]
    s_failed = [p["pd_no"] for p in s_three if not p["s_gate_audit"]["constraints_met"]]

    # coverage
    cov_items = [p for p in products]
    cats = {}
    for c in tag_order:
        ps = [p for p in cov_items if p["category"] == c]
        inc = [p for p in ps if p["included_in_priority"]]
        top = sorted(inc, key=lambda p: p["priority_rank"])[:5]
        pos_counts = Counter(p["price_position"]["status"] for p in ps)
        risk_counts = Counter(p["profitability_risk"] for p in ps)
        grade_counts = Counter(p["grade"] for p in ps)
        cats[c] = {
            "daiso_name": cfg["tags"][c]["daiso_name"], "score_buckets": cfg["tags"][c]["buckets"],
            "by_score_bucket": dict(sorted(Counter(p["bucket_ko"] for p in ps).items())),
            "s_by_score_bucket": dict(sorted(Counter(p["bucket_ko"] for p in ps if p["grade"] == "S").items())),
            "product_count": len(ps), "included_in_priority": len(inc),
            "excluded_non_beauty_misfit": sum(1 for p in ps if p["item_kind"] == "non_beauty_misfit"),
            "grade_counts": {g: grade_counts.get(g, 0) for g in ("S", "A", "B", "C")},
            "own_price": {k: sum(1 for p in ps if p["own_price"]["status"] == k) for k in ("live", "draft_payload", "model_recommended", "missing")},
            "quantity_usable": sum(1 for p in ps if quantity_usable(p["quantity"])),
            "english_identity_available": sum(1 for p in ps if p["market"]["english_identity_available"]),
            "comparator_tiers": {t: sum(p["market"]["tier_counts"][t] > 0 for p in ps) for t in ("qualified", "provisional", "reference_only")},
            "price_position_counts": dict(sorted(pos_counts.items())),
            "profitability_risk_counts": dict(sorted(risk_counts.items())),
            "priority_top5": [{"pd_no": p["pd_no"], "grade": p["grade"], "priority_score": p["priority"]["score"],
                               "evidence_status": p["priority"]["evidence_status"]} for p in top],
            "strategy_note": _category_note(c, ps, pos_counts),
        }

    quarantine_live = sum(1 for p in products if "live_listing_has_quarantine_reasons" in p["flags"])
    cov = {
        "quantity_unknown": sum(1 for p in products if p["included_in_priority"] and p["quantity"]["status"] == "unknown"),
        "quantity_conflict": sum(1 for p in products if p["included_in_priority"] and p["quantity"]["status"] == "conflict"),
        "verified_market_sources": sum(1 for s in sources if s.get("verified")),
        "market_shipping_known_items": sum(1 for i in items if i["shipping_usd"] is not None),
        "market_checkout_known_items": sum(1 for i in items if i["checkout_evidence"]["known"]),
        "market_checkout_verified_items": sum(1 for i in items if i["checkout_evidence"].get("source_verified")),
        "own_checkout_known_products": sum(1 for p in products if p["own_price"]["checkout_evidence"]["known"]),
        "own_checkout_verified_products": sum(1 for p in products if p["own_price"]["checkout_evidence"].get("source_verified")),
        "own_price_conflicts": sum(1 for p in products if p["own_price"]["conflict"]),
        "own_shipping_known": _dec(own_shipping_usd) is not None,
        "duty_mode_unconfirmed": bool((pricing_model.get("duty_mode_note") or {}).get("선택_필요")),
        "english_identity_missing": sum(1 for p in products if p["included_in_priority"] and not p["market"]["english_identity_available"]),
        "live_with_quarantine": quarantine_live,
        "own_live_not_fresh": sum(1 for p in products if p["own_price"]["kind"] == "live" and not p["own_price"]["live_fresh"]),
        "safety_record_missing_s": sum(1 for p in products if p["grade"] == "S" and not p["manufacturer_safety_record_covered"]),
        "positions_verified": sum(1 for p in products if p["price_position"]["verified"]),
    }
    analytics = docs.get("analytics")
    review = build_review_plan(products, analytics, analytics_status, docs.get("monthly_revenue"))

    unknowns = []
    if cov["verified_market_sources"] == 0:
        unknowns.append("No market source is verified and fresh as of the report time; no market minimum is qualified.")
    if cov["market_shipping_known_items"] == 0:
        unknowns.append("No market item records shipping, so no delivered comparison exists; comparisons are at best provisional.")
    if not cov["own_shipping_known"]:
        unknowns.append("Our customer-facing shipping charge is not in any input; pass --own-shipping-usd to evaluate delivered price.")
    unknowns.append("Checkout quote provenance is not authenticated by any connected producer in this report. Even complete recorded quotes remain provisional; self-declared verification never earns price points.")
    if analytics is None:
        unknowns.append("No product-level orders/traffic input; all review metrics are UNKNOWN (not zero).")
    if fee_rate is None:
        unknowns.append("Payment-fee rate could not be read from pricing_model.cost_basis; margins stay unknown.")
    unknowns.append("Supplemental Shopify transaction and Managed Markets fees are UNKNOWN, not assumed zero or added; modeled margins are not full verified profit.")
    unknowns.append(f"{len(landed)} products have a landed-cost scenario in pricing_model.json; all others have no margin beyond an upper bound.")

    coverage = {
        "files": file_status,
        "score_file": {"total_products": len(all_scored), "in_three_categories": len(products),
                       "by_category": {c: cats[c]["product_count"] for c in tag_order},
                       "other_buckets_not_covered": sum(1 for r in all_scored if r.get("bucket") not in b2t),
                       "other_buckets_detail": dict(sorted(Counter(r.get("bucket") for r in all_scored if r.get("bucket") not in b2t).items()))},
        "market_sources": sources,
        "market_items_total": len(items),
        "market_items_priced": sum(1 for i in items if i["price_usd"] is not None),
        "market_items_with_shipping": cov["market_shipping_known_items"],
        "own_price": {"live": sum(1 for p in products if p["own_price"]["status"] == "live"),
                      "draft_payload": sum(1 for p in products if p["own_price"]["status"] == "draft_payload"),
                      "model_recommended": sum(1 for p in products if p["own_price"]["status"] == "model_recommended"),
                      "missing": sum(1 for p in products if p["own_price"]["status"] == "missing")},
        "pricing_model_landed_cost_products": len(landed),
        "serpapi_product_aggregates": len(serp),
        "shopify_products_json": {"rows": len((docs.get("shopify_products") or {}).get("products", [])),
                                  "usable_as_product_price_evidence": False,
                                  "reason": "category-level placeholder rows with a flat price and no pd_no"},
        "quantity": dict(sorted(Counter(p["quantity"]["status"] for p in products).items())),
        "price_position": dict(sorted(Counter(p["price_position"]["status"] for p in products).items())),
        "profitability_risk": dict(sorted(Counter(p["profitability_risk"] for p in products).items())),
        "product_level_analytics_observations": review["analytics_input"]["product_level_observations_used"],
    }

    report = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "status": "advisory_unreviewed",
        "as_of": iso(as_of),
        "suggested_output_path": "data/beauty_price_strategy.json",
        "policy": {
            "network_calls": False, "paid_api_called": False, "other_files_modified": False,
            "grade_changes_allowed": False, "a_auto_upgrade_allowed": False,
            "margin_block_waived_by_user": True, "margin_is_advisory_only": True,
            "unknown_is_not_zero": True, "receipts_asserted": False,
            "comparison_rules": [
                "same brand + line + variant tokens; a different strength/formulation/model/set/kit is never compared",
                "ml, g and count are compared only within the same dimension; bare 'oz' is ambiguous and only matches itself",
                "pack total and unit size are kept separate; per-unit price is the common metric",
                "a verified claim needs total volume within the config tolerance (default 5%) in the same base unit; other sizes are provisional like-basis only",
                "SerpApi aggregates give a reference price basis only (0.95 x median) and never a competitive-minimum claim or score points",
                "stale or unverified sources are reference_only and never scored",
                "verified price advantage requires: fresh live own price, verified fresh market source, exact pack, and price-bound USD US standard-delivery quotes no older than 24h with explicit shipping, tax and mandatory fees for the same non-customer destination key; only observed comparable offers are compared",
                "draft payload and model-recommended prices are never verified",
            ],
        },
        "parameters": {"max_age_hours": max_age_hours, "own_live_max_age_hours": own_live_max_hours, "own_shipping_usd": _f(own_shipping_usd, 2) if _dec(own_shipping_usd) is not None else None,
                       "fx_usd_krw": _f(fx, 2) if fx is not None else None,
                       "payment_fee_rate": _f(fee_rate, 4) if fee_rate is not None else None,
                       "payment_fee_components": (pricing_model.get("cost_basis") or {}).get("payment_fee_components", []),
                       **profit_flags(), "advisory_floor": floors,
                       "priority_formula": "0.6*shopify_score + verified_price_points (20 + min(20, 0.8*gap_pct) only for verified_below); rank orders by original grade first"},
        "input_coverage": coverage,
        "unknowns": unknowns,
        "s_preservation": {
            "s_total_in_score_file": len(s_all), "s_in_three_categories": len(s_three), "s_in_config_categories": len(s_three),
            "s_outside_config_categories": s_uncovered,
            "s_by_category": {c: [p["pd_no"] for p in products if p["grade"] == "S" and p["category"] == c] for c in tag_order},
            "s_slot_limit": score.get("s_slot_limit"), "s_slot_open": score.get("s_slot_open"),
            "s_gate_constraints_failed": s_failed, "grade_changes": grade_changes,
            "a_products_with_verified_price_advantage_not_upgraded": [p["pd_no"] for p in products
                                                                      if p["grade"] == "A" and p["price_position"]["status"] == "verified_below"],
            "note": "Grades come only from the original S gate (qualify_s). A price advantage never upgrades a product.",
        },
        "config_alignment": {
            "config_loaded": not cfg["used_fallback"], "config_path": "config/daiso_commerce_strategy.json",
            "policy_id": cfg["policy_id"], "grade_policy": cfg["grade_policy"],
            "category_to_score_buckets": {c: cfg["tags"][c]["buckets"] for c in tag_order},
            "volume_tolerance": _f(tolerance, 4),
            "margin_advisory": floors,
            "reclassified_into_category": sorted([p["pd_no"] for p in products if p["reclassified_into_category_from_bucket"] and p["included_in_priority"]]),
            "reclassified_but_excluded_non_beauty": sorted([p["pd_no"] for p in products if p["reclassified_into_category_from_bucket"] and not p["included_in_priority"]]),
            "reclassified_s": sorted([p["pd_no"] for p in products if p["grade"] == "S" and p["reclassified_into_category_from_bucket"]]),
            "suncare_bucket_products": sum(1 for p in products if p["bucket_ko"] == "선케어"),
            "live_selection_preview": {c: [{"pd_no": p["pd_no"], "priority_rank": p["priority_rank"], "priority_score": p["priority"]["score"],
                                            "score_bucket": p["bucket_ko"], "blockers": p["live_selection_preview"]["all_blockers"]}
                                           for p in sorted((x for x in products if x["category"] == c and x["grade"] == "S"),
                                                           key=lambda x: (x["priority_rank"] is None, x["priority_rank"] or 0, x["pd_no"]))]
                                       for c in tag_order},
            "not_decided_here": ["image allowlist", "stock / authentication", "legal_full and label gates", "duplicate gate", "manufacturer safety record"],
        },
        "categories": cats,
        "priority_order": [p["pd_no"] for p in sorted(ranked, key=lambda p: p["priority_rank"])],
        "products": products,
        "team_work_plan": build_team_plan(cov),
        "review_24h": review,
    }
    assert_finite(report)
    return report


def _category_note(cat, ps, pos_counts):
    s = sum(1 for p in ps if p["grade"] == "S")
    a = sum(1 for p in ps if p["grade"] == "A")
    misfit = sum(1 for p in ps if p["item_kind"] == "non_beauty_misfit")
    verified = pos_counts.get("verified_below", 0) + pos_counts.get("verified_not_below", 0)
    own = sum(1 for p in ps if p["own_price"]["status"] in ("live", "draft_payload"))
    return (f"{cat}: {s} S, {a} A; {own} with an own live/draft price; {verified} with a verified price position; "
            f"{misfit} non-beauty misfit(s) excluded from ranking. Price advantage is not claimed where unverified.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", required=True, help="explicit output JSON path (e.g. data/beauty_price_strategy.json)")
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parent.parent / "data"))
    ap.add_argument("--as-of", help="ISO timestamp or now; default = generated_at of the score file (deterministic)")
    ap.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    ap.add_argument("--own-shipping-usd", type=float, default=None, help="customer shipping charge on a single unit, if known")
    ap.add_argument("--analytics", default=None, help="optional product-level analytics JSON (observations list)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    args = ap.parse_args(argv)

    if not math.isfinite(args.max_age_hours) or args.max_age_hours <= 0:
        ap.error("--max-age-hours must be a positive finite number")
    if args.own_shipping_usd is not None and (not math.isfinite(args.own_shipping_usd) or args.own_shipping_usd < 0):
        ap.error("--own-shipping-usd must be a finite non-negative number")
    out = Path(args.output)
    if out.exists() and not args.overwrite:
        print(f"refusing to overwrite existing {out}; pass --overwrite", file=sys.stderr)
        return 2
    docs, status = load_inputs(Path(args.data_dir), args.analytics)
    if "score" not in docs or not isinstance(docs["score"].get("all_scored"), list):
        print("required input daiso_real/shopify_demand_score.json (all_scored) is missing or unreadable", file=sys.stderr)
        return 2
    as_of = (datetime.now(UTC) if args.as_of == "now" else
             parse_ts(args.as_of) if args.as_of else parse_ts(docs["score"].get("generated_at")))
    if as_of is None:
        print("cannot determine --as-of (score file generated_at invalid)", file=sys.stderr)
        return 2
    analytics_status = next((s for s in status if s["key"] == "analytics"), None)
    report = build_strategy(docs, status, as_of, args.max_age_hours, args.own_shipping_usd, analytics_status)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _write_atomic(out, text)
    cov = report["input_coverage"]
    print(f"wrote {out} products={len(report['products'])} positions={cov['price_position']} risk={cov['profitability_risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
