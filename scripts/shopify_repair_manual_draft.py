#!/usr/bin/env python3
"""Bounded repair of ONE existing owner-approved nonpublic draft. No creation.

Run dry-run first, then supply its before_sha256 with --dry-run 0.
Only the existing Shopify adapter handles authentication/GraphQL. No env files,
credentials, new subscriptions, uploads, price updates, or activation are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PD = "1084687"
PRODUCT = "gid://shopify/Product/9590780723457"
STORE = "coarfamily.myshopify.com"  # Existing transport / exact environment endpoint.
# Pinned from live read-only report 38990202025 for this existing product.
SHOP_ID = "gid://shopify/Shop/82748997889"
CANONICAL_STORE = "rb3zh1-i1.myshopify.com"
TAG = "daiso-pd-1084687"
VARIANTS = {"gid://shopify/ProductVariant/50764170789121": "Single (1 pc)",
            "gid://shopify/ProductVariant/50764170821889": "1+1 (2 pcs)"}
MANIFEST = "data/manual/image_localization/1084687.json"
TARGET_SHA = "ddc8cf629f37c8240fcbc0759f7fbe1e282a9e1b99794a62f49bb5075a221f63"
# Shopify write scopes imply the corresponding read capabilities. The complete
# successful READ below proves read access; redundant read handles need not appear.
SCOPES = {"write_products", "write_publications"}
LIMITATION = ("Publication verification covers only the complete API-accessible view; "
              "global channel removal, public-sale readiness and safety are not certified. "
              "Shopify productUpdate has no atomic description-SHA compare-and-swap; "
              "a concurrent edit after the immediate preflight remains possible.")
READ = """query ManualDraftRepairRead($id:ID!){
 shop{id myshopifyDomain} currentAppInstallation{accessScopes{handle}}
 publications(first:50){nodes{id} pageInfo{hasNextPage}}
 product(id:$id){id status tags vendor productType descriptionHtml
 variants(first:3){nodes{id title price inventoryItem{tracked}} pageInfo{hasNextPage}}
 media(first:12){nodes{id mediaContentType status ... on MediaImage{image{url}}} pageInfo{hasNextPage}}
 resourcePublicationsV2(first:50){nodes{isPublished publication{id}} pageInfo{hasNextPage}}}}
"""
UPDATE = """mutation ManualDraftRepairDescription($p:ProductUpdateInput!){
 productUpdate(product:$p){product{id} userErrors{field message}}}"""
UNPUBLISH = """mutation ManualDraftRepairUnpublish($id:ID!,$input:[PublicationInput!]!){
 publishableUnpublish(id:$id,input:$input){userErrors{field message}}}"""
STATUS = "query ManualDraftRepairStatus($id:ID!){product(id:$id){id status}}"


class Blocked(RuntimeError):
    """Messages are fixed diagnostic codes, never raw API responses."""


def require(condition, code):
    if not condition:
        raise Blocked(code)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "li", "h1", "h2", "h3", "br", "div", "ul", "ol"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, [])


def semantic(html):
    parser = Text()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())


def load_local(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8-sig"))
    registry = json.loads((root / "data/shopify_daily_registry.json").read_text(encoding="utf-8-sig"))
    return local_guard(manifest, registry)


def local_guard(manifest, registry):
    rows = registry.get("items", [])
    require(isinstance(rows, list), "registry_shape")
    matches = [r for r in rows if str(r.get("pd_no")) == PD]
    require(len(matches) == 1, "registry_exact_unique_item")
    row = matches[0]
    require(row.get("shopify_id") == PRODUCT and row.get("source_tag") == TAG,
            "local_identity")
    require(row.get("source") == "manual_owner_image_localization_example" and
            row.get("owner_requested_nonpublic_draft") is True and
            row.get("grade") == "-" and row.get("canonical_s_promotion") is False and
            row.get("status") == "DRAFT" and row.get("image_localization_manifest") == MANIFEST,
            "local_owner_nonpublic_approval")
    require(str(manifest.get("product_id")) == PD, "manifest_identity")
    registration = manifest.get("registration", {})
    require(str(registration.get("product_id")) == PRODUCT.rsplit("/", 1)[1] and
            registration.get("source_tag") == TAG and
            registration.get("public_sale_authorized") is False and
            registration.get("safety_evidence_verified") is False, "manifest_nonpublic_hold")
    target = manifest.get("desired_description_html")
    require(isinstance(target, str) and sha(target) == TARGET_SHA and
            bool(manifest.get("description_target_provenance")), "desired_html_source")
    outputs = manifest.get("outputs", [])
    files = [o.get("file", "") for o in outputs]
    require(len(files) == 11 and len(set(files)) == 11 and all(
        re.fullmatch(rf"{i:02d}-[a-z0-9-]+-en\.png", name)
        for i, name in enumerate(files, 1)), "manifest_ordered_english_images")
    return {"target": target, "files": files, "source_sha256": sha(target),
            "registry_source": row["source"], "owner_requested_nonpublic_draft": True}


def gql(client, query, variables):
    try:
        result = client.gql(query, variables)
        require(isinstance(result, dict) and not result.get("errors"), "api_response")
        return result
    except Blocked:
        raise
    except Exception:
        # Existing adapter errors can contain response bodies: never propagate them.
        raise Blocked("api_unavailable_or_permission_denied") from None


def nodes(connection, maximum, code):
    require(isinstance(connection, dict) and
            connection.get("pageInfo", {}).get("hasNextPage") is False and
            isinstance(connection.get("nodes"), list) and
            len(connection["nodes"]) <= maximum, code)
    return connection["nodes"]


def filename(url):
    # Shopify's observed resized CDN names use _800x800; only this harmless
    # transformation is accepted, not arbitrary prefix matching.
    return re.sub(r"_\d+x\d+(?=\.png$)", "", unquote(urlsplit(url).path).rsplit("/", 1)[-1])


def identity_observation(data):
    """Allowlisted, bounded identity-only evidence; never copy API payloads."""
    shop = data.get("shop") if isinstance(data.get("shop"), dict) else {}
    product = data.get("product") if isinstance(data.get("product"), dict) else {}

    def bounded(value, pattern):
        return value if isinstance(value, str) and len(value) <= 100 and re.fullmatch(pattern, value) else None

    return {"shop_id": bounded(shop.get("id"), r"gid://shopify/Shop/[0-9]{1,20}"),
            "myshopify_domain": bounded(shop.get("myshopifyDomain"),
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com"),
            "product_id": bounded(product.get("id"), r"gid://shopify/Product/[0-9]{1,20}"),
            "product_status": product.get("status") if product.get("status") in
                ("DRAFT", "ACTIVE", "ARCHIVED", "UNLISTED") else None}


def read_guard(client, local):
    d = gql(client, READ, {"id": PRODUCT})
    shop = d.get("shop") if isinstance(d.get("shop"), dict) else {}
    if shop.get("id") != SHOP_ID or shop.get("myshopifyDomain") != CANONICAL_STORE:
        error = Blocked("wrong_store")
        error.identity_observation = identity_observation(d)
        raise error
    installation = d.get("currentAppInstallation")
    require(isinstance(installation, dict), "malformed_scopes")
    scope_rows = installation.get("accessScopes")
    require(isinstance(scope_rows, list) and all(
        isinstance(s, dict) and isinstance(s.get("handle"), str) and bool(s["handle"])
        for s in scope_rows), "malformed_scopes")
    scopes = {s["handle"] for s in scope_rows}
    require(SCOPES <= scopes, "missing_scopes")
    pubs = nodes(d.get("publications"), 50, "publication_view_incomplete")
    pub_ids = [p.get("id") for p in pubs]
    require(len(set(pub_ids)) == len(pub_ids) and all(
        isinstance(p, str) and re.fullmatch(r"gid://shopify/Publication/\d+", p) for p in pub_ids),
        "publication_identity")
    p = d.get("product") or {}
    require(p.get("id") == PRODUCT, "wrong_product")
    require(p.get("status") == "DRAFT", "not_draft")
    require(TAG in p.get("tags", []) and
            {t for t in p["tags"] if t.startswith("daiso-pd-")} == {TAG}, "wrong_tag")
    require(p.get("vendor") == "Dr.CPU+" and p.get("productType") == "Skincare", "wrong_vendor_type")
    require(isinstance(p.get("descriptionHtml"), str), "description_unavailable")
    variants = nodes(p.get("variants"), 2, "variants_incomplete")
    require(len(variants) == 2 and {v.get("id"): v.get("title") for v in variants} == VARIANTS,
            "wrong_variants")
    try:
        require(all(Decimal(v["price"]).is_finite() and Decimal(v["price"]) == 0 for v in variants),
                "nonzero_prices")
    except (InvalidOperation, KeyError, TypeError):
        raise Blocked("invalid_prices") from None
    require(all(v.get("inventoryItem", {}).get("tracked") is False for v in variants), "inventory_tracking")
    media = nodes(p.get("media"), 11, "media_incomplete")
    require(len(media) == 11 and all(m.get("mediaContentType") == "IMAGE" and
            m.get("status") == "READY" and m.get("image", {}).get("url") for m in media), "wrong_media")
    require([filename(m["image"]["url"]) for m in media] == local["files"], "wrong_media_filenames")
    require(len({m.get("id") for m in media}) == 11 and all(m.get("id") for m in media), "media_identity")
    states = nodes(p.get("resourcePublicationsV2"), 50, "product_publications_incomplete")
    state_ids = [s.get("publication", {}).get("id") for s in states]
    require(len(set(state_ids)) == len(state_ids) and set(state_ids) <= set(pub_ids) and
            all(type(s.get("isPublished")) is bool for s in states), "publication_state_unavailable")
    return {"descriptionHtml": p["descriptionHtml"], "before_sha256": sha(p["descriptionHtml"]),
            "status": p["status"], "product_id": PRODUCT, "store": STORE,
            "shop_id": shop["id"], "canonical_domain": shop["myshopifyDomain"],
            "tags": sorted(p["tags"]), "vendor": p["vendor"], "product_type": p["productType"],
            "variants": sorted(variants, key=lambda v: v["id"]), "media": media,
            "publication_ids": sorted(pub_ids),
            "published_publication_ids": sorted(s["publication"]["id"] for s in states if s["isPublished"]),
            "api_publication_view_complete": True}


def unchanged(a, b):
    keys = ("product_id", "store", "shop_id", "canonical_domain", "status", "tags", "vendor", "product_type", "variants", "media", "publication_ids")
    require(all(a[k] == b[k] for k in keys), "protected_fields_changed")


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # Per-state backups must never overwrite a previous observation.
    if ".backup." in path.name:
        with path.open("x", encoding="utf-8") as f:
            f.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def repair(client, local, *, dry_run=True, expected_before_sha256=None,
           output=Path("out/shopify_manual_draft_repair.json"), writer=save_json):
    require(type(dry_run) is bool, "invalid_dry_run")
    require(dry_run or bool(re.fullmatch(r"[0-9a-f]{64}", expected_before_sha256 or "")), "expected_sha_required")
    report = {"schema_version": 1, "pd_no": PD, "product_id": PRODUCT, "dry_run": dry_run,
              "status": "blocked", "mutation_attempts": [], "global_channel_removal_verified": False,
              "limitations": [LIMITATION], "source_sha256": local["source_sha256"]}
    output = Path(output)
    try:
        before = read_guard(client, local)
        report["before_sha256"] = before["before_sha256"]
        require(dry_run or before["before_sha256"] == expected_before_sha256, "expected_sha_mismatch")
        # Fresh unique backup beside the report, including the original description and proofs.
        import uuid
        backup = output.with_name(output.stem + ".backup." + uuid.uuid4().hex + ".json")
        writer(backup, {"schema_version": 1, "before": before, "local_proof": local,
                        "limitations": [LIMITATION]})
        report["backup"] = str(backup)
        if dry_run:
            report.update(status="dry_run", remote_writes=0,
                          description_change_needed=semantic(before["descriptionHtml"]) != semantic(local["target"]),
                          publications_to_unpublish=before["publication_ids"] if before["published_publication_ids"] else [])
        else:
            fresh = read_guard(client, local)  # Immediately before any mutation.
            unchanged(before, fresh)
            require(fresh["before_sha256"] == expected_before_sha256, "expected_sha_mismatch")
            if semantic(fresh["descriptionHtml"]) != semantic(local["target"]):
                report["mutation_attempts"].append("productUpdate_description_only")
                result = gql(client, UPDATE, {"p": {"id": PRODUCT, "descriptionHtml": local["target"]}}).get("productUpdate") or {}
                require(result.get("userErrors") == [] and result.get("product", {}).get("id") == PRODUCT,
                        "description_mutation_rejected")
            current = read_guard(client, local)  # Recheck before unpublication too.
            unchanged(before, current)
            require(semantic(current["descriptionHtml"]) == semantic(local["target"]), "description_verification_failed")
            if current["published_publication_ids"]:
                report["mutation_attempts"].append("publishableUnpublish_existing_product")
                result = gql(client, UNPUBLISH, {"id": PRODUCT, "input": [
                    {"publicationId": p} for p in current["publication_ids"]]}).get("publishableUnpublish") or {}
                require(result.get("userErrors") == [], "unpublish_mutation_rejected")
            after = read_guard(client, local)
            unchanged(before, after)
            require(semantic(after["descriptionHtml"]) == semantic(local["target"]), "description_verification_failed")
            require(not after["published_publication_ids"], "publication_verification_failed")
            report.update(status="verified_api_accessible_draft", after=after,
                          api_accessible_publications_removed=True, remote_writes=len(report["mutation_attempts"]))
    except Exception as exc:
        report["status"] = "partial" if report["mutation_attempts"] else "blocked"
        report["reason"] = str(exc) if isinstance(exc, Blocked) else "local_or_proof_failure"
        if isinstance(exc, Blocked) and str(exc) == "wrong_store":
            report["identity_observation"] = getattr(exc, "identity_observation", {})
        # Read-only fallback confirms Draft even if publication permission disappears.
        try:
            p = gql(client, STATUS, {"id": PRODUCT}).get("product") or {}
            report["last_observed_status"] = p.get("status") if p.get("id") == PRODUCT else "unknown"
        except Exception:
            report["last_observed_status"] = "unknown"
    writer(output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pd-no", choices=[PD], required=True)
    parser.add_argument("--dry-run", choices=["0", "1"], default="1")
    parser.add_argument("--expected-before-sha256")
    parser.add_argument("--output", type=Path, default=Path("out/shopify_manual_draft_repair.json"))
    args = parser.parse_args(argv)
    if args.dry_run == "0" and not re.fullmatch(r"[0-9a-f]{64}", args.expected_before_sha256 or ""):
        parser.error("apply requires --expected-before-sha256 (64 lowercase hex characters)")
    try:
        local = load_local(ROOT)  # Local guards run before auth/network.
        require(os.environ.get("SHOPIFY_STORE", "") == STORE, "wrong_store_environment")
        from daiso_daily_beauty_to_shopify import Shopify
        client = Shopify()  # Existing GH environment credentials only, no dotenv/secret output.
        result = repair(client, local, dry_run=args.dry_run == "1",
                        expected_before_sha256=args.expected_before_sha256,
                        output=args.output if args.output.is_absolute() else ROOT / args.output)
    except Exception as exc:
        result = {"schema_version": 1, "status": "blocked", "product_id": PRODUCT,
                  "reason": str(exc) if isinstance(exc, Blocked) else "setup_unavailable",
                  "global_channel_removal_verified": False, "limitations": [LIMITATION]}
        save_json(args.output if args.output.is_absolute() else ROOT / args.output, result)
    print(json.dumps({k: result[k] for k in ("status", "reason", "before_sha256") if k in result}))
    return 0 if result["status"] in {"dry_run", "verified_api_accessible_draft"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
