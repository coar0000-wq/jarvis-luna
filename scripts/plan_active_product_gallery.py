#!/usr/bin/env python3
"""Offline ACTIVE-gallery review plan. No client, upload, apply flag or authority.

Observed roles and self-declared receipts never authorize writes. Existing IDs
and order are preserved; exact source/CDN decoded-RGB matches produce no-ops.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from PIL import Image, ImageCms, ImageOps

SCHEMA_VERSION = 1
SHA = re.compile(r"[0-9a-f]{64}")
GID = re.compile(r"gid://shopify/MediaImage/\d+")
PRODUCT_GID = re.compile(r"gid://shopify/Product/\d+")
HANGUL = re.compile(r"[\uac00-\ud7a3\u3131-\u318e]")
HERO_OBSERVATIONS = {"hero", "hero_single_box_contents", "hero_yellow_jar"}
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 30_000_000
FORBIDDEN_OPERATIONS = ["upload", "delete", "reorder", "update_alt", "bind_variant",
                        "change_price", "change_status", "publish", "checkout"]


class InvalidInput(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def canonical_url(value):
    """Provenance comparison only; never enough by itself to prove equivalence."""
    try:
        parts = urlsplit(value if isinstance(value, str) else "")
        if (parts.scheme != "https" or parts.hostname != "cdn.shopify.com"
                or parts.username or parts.password or parts.port not in (None, 443)):
            return None
        return "https://cdn.shopify.com" + parts.path
    except ValueError:
        return None


def fingerprint(filename, root):
    """Bounded local verification; never follows paths outside the caller's root."""
    try:
        base = Path(root).resolve()
        path = Path(filename)
        path = (path if path.is_absolute() else base / path).resolve()
        path.relative_to(base)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
            return None
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as source:
            if source.width <= 0 or source.height <= 0 or source.width * source.height > MAX_PIXELS:
                return None
            if getattr(source, "n_frames", 1) != 1:
                return None
            if source.mode not in ("RGB", "RGBA"):
                return None
            pixels = source.convert("RGB")
            # A raw RGB checksum alone discards transparency, display orientation
            # and colour profiles. Bind both raw audit pixels and rendered RGBA.
            displayed = ImageOps.exif_transpose(source).convert("RGBA")
            rgb = displayed.convert("RGB")
            if source.info.get("icc_profile"):
                profile = ImageCms.ImageCmsProfile(io.BytesIO(source.info["icc_profile"]))
                rgb = ImageCms.profileToProfile(rgb, profile, ImageCms.createProfile("sRGB"),
                                               outputMode="RGB")
            normalized = rgb.convert("RGBA")
            normalized.putalpha(displayed.getchannel("A"))
            return {"sha256": content, "pixel_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                    "width": pixels.width, "height": pixels.height,
                    "render_sha256": hashlib.sha256(normalized.tobytes()).hexdigest(),
                    "render_width": normalized.width, "render_height": normalized.height}
    except (OSError, ValueError, TypeError, Image.DecompressionBombError, ImageCms.PyCMSError):
        return None


def pixel_equal(left, right):
    keys = ("pixel_sha256", "width", "height", "render_sha256", "render_width", "render_height")
    return (isinstance(left, dict) and isinstance(right, dict)
            and isinstance(left.get("pixel_sha256"), str)
            and bool(SHA.fullmatch(left["pixel_sha256"]))
            and type(left.get("width")) is int and left["width"] > 0
            and type(left.get("height")) is int and left["height"] > 0
            and isinstance(left.get("render_sha256"), str) and bool(SHA.fullmatch(left["render_sha256"]))
            and all(left.get(key) == right.get(key) for key in keys))


def role_holds(role):
    result = []
    if any(word in role for word in ("face", "model", "portrait", "campaign")):
        result += ["likeness_and_reuse_rights_review_required", "final_output_face_review_required"]
    if "before_after" in role:
        result.append("claim_substantiation_review_required")
    if role in ("marketing_text_only", "ingredient_marketing"):
        result.append("not_an_exact_product_hero")
    if "range" in role:
        result.append("other_products_not_eligible_for_hero_or_variant")
    if "staging" in role or "pack_comparison" in role:
        result.append("not_count_specific_variant_evidence")
    return result


def _unique(rows, key, label):
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]:
            raise InvalidInput(label + "_identity_missing")
        if row[key] in result:
            raise InvalidInput(label + "_duplicate_identity")
        result[row[key]] = row
    return result


def build_plan(current, audit, *, media_root, reuse_manifest=None, source_root=None,
               localizations=None, findings=None, code_ref=None):
    """Return review tasks, held candidates and preservation no-ops, never writes."""
    if not isinstance(current, list) or not isinstance(audit, dict):
        raise InvalidInput("invalid_document_shape")
    products = _unique(current, "id", "current_product")
    observed = _unique(audit.get("products") or [], "product_id", "audit_product")
    if not observed or set(products) != set(observed):
        raise InvalidInput("current_audit_product_scope_mismatch")
    _unique(list(observed.values()), "pd_no", "audit_pd_no")
    localizations = localizations or {}
    findings = findings or {}
    if (not isinstance(localizations, dict) or not isinstance(findings, dict)
            or (reuse_manifest is not None and not isinstance(reuse_manifest, dict))):
        raise InvalidInput("optional_document_shape")
    reuse_products = _unique((reuse_manifest or {}).get("products") or [], "product_id", "reuse_product")
    rows, media_seen = [], set()
    for product_id, item in observed.items():
        if not PRODUCT_GID.fullmatch(product_id):
            raise InvalidInput("product_gid_invalid")
        live = products[product_id]
        pd_no = item["pd_no"]
        if live.get("status") != "ACTIVE" or item.get("status_observed") != "ACTIVE":
            raise InvalidInput("active_scope_required")
        images = live.get("images")
        media = item.get("media")
        if not isinstance(images, list) or not isinstance(media, list) or not images or len(images) != len(media):
            raise InvalidInput("media_inventory_incomplete")
        if item.get("images_observed") != len(media):
            raise InvalidInput("audit_media_count_mismatch")
        _unique(images, "mediaId", "current_media")
        indexed = _unique(media, "mediaId", "audit_media")
        ids = [x.get("mediaId") for x in images]
        if ids != list(indexed) or len(set(ids)) != len(ids):
            raise InvalidInput("media_order_or_identity_drift")
        if any(not GID.fullmatch(mid) or mid in media_seen for mid in ids):
            raise InvalidInput("media_identity_invalid_or_shared")
        media_seen.update(ids)
        product_holds = ["actual_label_and_exact_variant_identity_review_required",
                         "fresh_complete_admin_snapshot_required", "deployment_and_team_receipts_required"]
        loc = localizations.get(pd_no) or {}
        if not isinstance(loc, dict):
            raise InvalidInput("localization_record_shape")
        if loc.get("status") == "ok" and (loc.get("gallery_status") != "ready"
                                               or loc.get("gallery_complete") is not True):
            product_holds.append("translation_ok_is_not_gallery_readiness")
        # These observations add holds only. No input can remove a hold/authorize writes.
        extra = findings.get(pd_no) or {}
        if (not isinstance(extra, dict) or not isinstance(extra.get("hold_codes", []), list)
                or not isinstance(extra.get("media_issue_codes", {}), dict)):
            raise InvalidInput("findings_record_shape")
        product_holds.extend(x for x in extra.get("hold_codes", []) if isinstance(x, str))
        outputs, verified_pixels = [], {}
        for index, (actual, recorded) in enumerate(zip(images, media), 1):
            mid = recorded["mediaId"]
            if (recorded.get("index") != index or actual.get("url") != recorded.get("url")
                    or actual.get("altText", "") != recorded.get("altText", "")
                    or canonical_url(actual.get("url")) is None):
                raise InvalidInput("audit_snapshot_media_drift")
            facts = fingerprint(recorded.get("path"), media_root)
            holds = ["source_rights_claim_label_review_required"]
            raw_keys = ("sha256", "pixel_sha256", "width", "height")
            if not facts or any(facts[key] != recorded.get(key) for key in raw_keys):
                holds.append("local_media_bytes_or_pixels_unverified")
            else:
                verified_pixels[mid] = facts
            role = recorded.get("role_observed") if isinstance(recorded.get("role_observed"), str) else "unknown"
            holds.extend(role_holds(role))
            if HANGUL.search(actual.get("altText") or ""):
                holds.append("english_alt_source_review_required")
            asset_extra = extra.get("media_issue_codes", {}).get(mid, [])
            if not isinstance(asset_extra, list):
                raise InvalidInput("media_issues_shape")
            holds.extend(x for x in asset_extra if isinstance(x, str))
            outputs.append({"media_id": mid, "position": index, "url": actual["url"],
                            "alt": actual.get("altText") or "", "observed_role": role,
                            "local_fingerprint": facts, "inventory_bytes_verified": mid in verified_pixels,
                            "decision": "preserve_existing_noop", "holds": sorted(set(holds)),
                            "automatic_variant_assignment": False, "apply_authorized": False})
        roles = [row["observed_role"] for row in outputs]
        if not any(role in HERO_OBSERVATIONS for role in roles):
            product_holds.append("exact_product_hero_missing")
        if not any("pack" in role for role in roles):
            product_holds.append("pack_contents_role_missing")
        if not any("usage" in role for role in roles):
            product_holds.append("usage_role_missing")
        if not any("caution" in role for role in roles):
            product_holds.append("cautions_role_missing")
        reuse = reuse_products.get(product_id, {})
        checks = []
        if reuse and reuse.get("pd_no") != pd_no:
            raise InvalidInput("reuse_product_scope_mismatch")
        seen_candidates = set()
        for asset in reuse.get("assets") or []:
            if not isinstance(asset, dict):
                raise InvalidInput("reuse_asset_shape")
            mid = asset.get("attached_media_id")
            if mid in seen_candidates:
                raise InvalidInput("reuse_asset_duplicate")
            seen_candidates.add(mid)
            reasons = []
            existing = indexed.get(mid)
            source = fingerprint(asset.get("file"), source_root) if source_root else None
            if not existing or asset.get("pd_no") != pd_no:
                reasons.append("existing_media_product_binding_missing")
            if not source or source["sha256"] != asset.get("sha256"):
                reasons.append("source_file_binding_unverified")
            if not existing or canonical_url(asset.get("attached_image_url")) != canonical_url(existing.get("url")):
                reasons.append("existing_media_url_provenance_mismatch")
            if not pixel_equal(source, verified_pixels.get(mid)):
                reasons.append("decoded_pixels_or_dimensions_mismatch")
            checks.append({"media_id": mid, "role": asset.get("role"),
                           "decision": "hold_no_upload" if reasons else "reuse_existing_noop",
                           "reasons": reasons, "binary_equal": bool(source and existing and source["sha256"] == existing.get("sha256")),
                           "render_equivalent": pixel_equal(source, verified_pixels.get(mid)),
                           "apply_authorized": False})
        rows.append({"pd_no": pd_no, "product_id": product_id,
                     "status_observed": "ACTIVE", "preserve_media_ids_in_order": ids,
                     "snapshot_digest": digest(live), "protected_fields": {
                         "status": live.get("status"), "variants": deepcopy(live.get("variants")),
                         "totalVariants": live.get("totalVariants"), "currencyCode": live.get("currencyCode"),
                         "publications_observed": False},
                     "holds": sorted(set(product_holds)), "media": outputs, "reuse_checks": checks,
                     "apply_authorized": False})
    return {"schema_version": SCHEMA_VERSION, "mode": "plan_only", "status": "prepared_local",
            "code_ref": code_ref, "code_ref_verified_by_this_tool": False,
            "input_digests": {"current": digest(current), "audit": digest(audit),
                              "reuse_manifest": digest(reuse_manifest or {}), "findings": digest(findings),
                              "localizations": digest(localizations)},
            "authority": {"apply_authorized": False, "team_execution_verified": False},
            "lifecycle": {"prepared": True, "github_deployed": False, "team_flow_verified": False,
                          "shopify_applied": False, "admin_readback_verified": False,
                          "storefront_render_verified": False, "mobile_render_verified": False},
            "operations": [], "forbidden_operations": FORBIDDEN_OPERATIONS[:],
            "products": rows, "summary": {"products": len(rows), "media": len(media_seen),
                "existing_asset_reuse_noops": sum(c["decision"] == "reuse_existing_noop" for r in rows for c in r["reuse_checks"]),
                "held_reuse_candidates": sum(c["decision"] == "hold_no_upload" for r in rows for c in r["reuse_checks"]),
                "writes": 0},
            "next_executor_requirements": ["verified_code_and_team_handoff_receipts",
                "trusted_exact_asset_scope_rights_claim_label_and_final_output_qa_receipts",
                "fresh_complete_media_variants_prices_status_publications_snapshot",
                "abort_on_snapshot_drift", "reuse_existing_ids_before_any_create",
                "stop_on_write_unknown_never_blind_retry", "exact_admin_readback_and_protected_field_comparison",
                "separate_customer_storefront_and_mobile_render_review"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--reuse-manifest", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--localizations", type=Path)
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--code-ref")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    def read(path):
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    try:
        report = build_plan(read(args.current), read(args.audit), media_root=args.media_root,
                            reuse_manifest=read(args.reuse_manifest), source_root=args.source_root,
                            localizations=read(args.localizations), findings=read(args.findings), code_ref=args.code_ref)
    except (InvalidInput, OSError, ValueError, TypeError) as exc:
        print("Plan blocked: " + type(exc).__name__)
        return 2
    # Atomic report replace only after validation; no output to the input paths.
    inputs = [p.resolve() for p in (args.current, args.audit, args.reuse_manifest,
                                   args.localizations, args.findings) if p]
    if args.out.resolve() in inputs:
        print("Plan blocked: output_must_not_replace_input")
        return 2
    if any(args.out.resolve().is_relative_to(root.resolve())
           for root in (args.media_root, args.source_root) if root):
        print("Plan blocked: output_must_not_replace_asset")
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive random temporary file: a pre-existing .tmp path or symlink must
    # never be opened for writing. Keep the final replace on the same filesystem.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.out.parent,
                                     prefix=args.out.name + ".", suffix=".tmp", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    try:
        temp.replace(args.out)
    finally:
        temp.unlink(missing_ok=True)
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
