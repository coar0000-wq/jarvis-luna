#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 상품의 누락 영문 카피를 무료·로컬 템플릿으로 보완한다.

기존 검증 카피는 그대로 보존한다. 현재 listing gate의 agent_ready 상품 중
카피가 없거나 v1 로컬 초안인 상품, 예전 선행 게이트 때문에 건너뛴 상품만
처리한다. 제품명·제형·용량 사실만 쓰며 효능·인증·원산지를 추정하지 않는다.
외부 API와 유료 모델은 호출하지 않는다.
"""
from __future__ import annotations

import json
from html import escape
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SRC = DATA / "daiso_real" / "shopify_s_recommendations.json"
GATE = DATA / "listing_gate.json"
OUT = DATA / "shopify_listing_copy.json"
LOCAL_MODE = "deterministic_local_template_v2"
LEGACY_LOCAL_MODE = "deterministic_local_template_v1"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def clean(value) -> str:
    return " ".join(str(value or "").split()).strip()


def brand_of(name: str) -> str:
    pairs = (
        ("VT", "VT"),
        ("본셉", "VONSEP"),
        ("셀더마데일리", "CELDERMA Daily"),
        ("메디필", "MEDI-PEEL"),
    )
    upper = name.upper()
    for token, brand in pairs:
        if token.upper() in upper:
            return brand
    return ""


def type_of(name: str) -> str:
    pairs = (
        ("바디괄사 세럼", "Body Serum"),
        ("슬리핑 마스크", "Sleeping Mask"),
        ("랩핑 마스크", "Wrapping Mask"),
        ("겔 마스크", "Gel Sheet Mask"),
        ("마스크", "Sheet Mask"),
        ("토너", "Face Toner"),
        ("앰플", "Face Ampoule"),
        ("세럼", "Face Serum"),
        ("크림", "Face Cream"),
        ("미스트", "Face Mist"),
    )
    for token, value in pairs:
        if token in name:
            return value
    return "Cosmetic"


def focus_of(name: str) -> str:
    values = []
    upper = name.upper()
    for token, label in (
        ("PDRN", "PDRN"),
        ("레티놀", "Retinol"),
        ("콜라겐", "Collagen"),
        ("히알론", "Hyaluron"),
        ("리들샷 300", "Reedle Shot 300"),
        ("리들샷 100", "Reedle Shot 100"),
    ):
        if token.upper() in upper and label not in values:
            values.append(label)
    return " ".join(values[:2])


def volume_of(gate_row: dict, name: str) -> str:
    gosi = gate_row.get("gosi") or {}
    label = gate_row.get("us_label") or {}
    volume = clean(label.get("net_contents") or gosi.get("volume"))
    if volume:
        return volume
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|g|매)(?:\s*[*x×]\s*\d+개입)?", name, re.I)
    return clean(match.group(0)) if match else ""


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:48]


def local_copy(name: str, gate_row: dict) -> dict:
    brand = brand_of(name)
    product_type = type_of(name)
    focus = focus_of(name)
    volume = volume_of(gate_row, name)
    # Name tokens identify the product; they do not establish ingredient claims.
    # Unknown brands retain their source name rather than inferring an origin.
    title = (" ".join(x for x in (brand, focus, product_type, volume) if x)
             if brand else name)
    title = title[:70].rstrip()
    size_text = f" listed with {volume} net contents" if volume else ""
    identity_sentence = f"{title} is a {product_type.lower()}{size_text}."
    review_sentence = (
        f"Before publication, review {title} against its ingredient list, "
        "directions, and final US label."
    )
    description = (
        f"<p>{escape(identity_sentence)}</p><p>{escape(review_sentence)}</p>"
    )
    tags = [slug(x) for x in (brand, focus, product_type) if slug(x)]
    tags = list(dict.fromkeys(tags))
    seo_description = (
        f"{title}: source-listed {product_type.lower()}"
        + (f"; net contents {volume}" if volume else "")
        + f". Check the final US label for {title} before publication."
    )[:320]
    return {
        "title": title,
        "description_html": description,
        "seo_title": title,
        "seo_description": seo_description,
        "tags": tags,
        "product_type": product_type,
    }


COPY_REL = "data/shopify_listing_copy.json"
SOURCE_REL = "data/daiso_real/shopify_s_recommendations.json"
GATE_REL = "data/listing_gate.json"
HISTORY_KEY = "draft_history"


def verify_current(doc, source, gate):
    """Current rows equal canonical S members; historical drafts are not approval."""
    if source.get("canonical") is not True:
        raise ValueError("copy requires canonical S source")
    def index(rows):
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not r.get("pd_no") for r in rows):
            raise ValueError("copy/source/gate rows require pd_no")
        result = {str(r["pd_no"]): r for r in rows}
        if len(result) != len(rows):
            raise ValueError("duplicate copy/source/gate identity")
        return result
    canonical = index(source.get("recommendations"))
    current = index(doc.get("items"))
    gates = index(gate.get("items"))
    if set(current) != set(canonical) or not set(current) <= set(gates):
        raise ValueError("current copy membership differs from canonical S/gate")
    for key in ("generated_at", "generator", "model", "source", "note"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise ValueError("blank current copy provenance")
    eligible = 0
    for pd_no, row in current.items():
        gr = gates[pd_no]
        for target, key in (("name_ko", "name"), ("bucket", "bucket"), ("price_krw", "price_krw"),
                            ("rating", "rating"), ("review_count", "review_count"), ("shopify_score", "shopify_score"),
                            ("source_url", "url"), ("image_url", "image_url")):
            if target not in row or row[target] != canonical[pd_no].get(key):
                raise ValueError("current copy source facts differ from canonical S")
        if row.get("canonical_product_id") != gr.get("canonical_product_id"):
            raise ValueError("current copy canonical identity differs from gate")
        if not gr.get("agent_ready"):
            blocked = list(gr.get("agent_blocked_by") or ["ontology_gate_missing"])
            if (row.get("copy") is not None or row.get("copy_status") != "skipped_prerequisite"
                    or row.get("generation_mode") != "none" or row.get("agent_blocked_by") != blocked
                    or row.get("error") != "ontology 선행 게이트 미통과: " + ", ".join(blocked)):
                raise ValueError("blocked current copy must retain current gate blockers")
        else:
            eligible += 1
    if (doc.get("total") != len(current) or doc.get("eligible") != eligible
            or doc.get("ok") != eligible or doc.get("skipped_prerequisite") != len(current) - eligible):
        raise ValueError("current copy counters do not match canonical gate")
    return set(canonical)


def history_required(previous, current):
    old = {str(r["pd_no"]): r for r in previous.get("items", [])}
    new = {str(r["pd_no"]): r for r in current.get("items", [])}
    return bool(set(old) - set(new)) or any(isinstance(row.get("copy"), dict) and new[pd].get("copy") is None for pd, row in old.items() if pd in new)


def archive_previous(payload, previous, raw):
    import hashlib
    history = dict(previous.get(HISTORY_KEY) or {})
    history.update(payload.get(HISTORY_KEY) or {})
    if history_required(previous, payload):
        digest = hashlib.sha256(raw).hexdigest()
        snapshot = {k: v for k, v in previous.items() if k != HISTORY_KEY}
        snapshot_digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        entry = {"base_sha256": digest, "snapshot_sha256": snapshot_digest, "historical_not_approval": True,
                 "snapshot": snapshot,
                 "provenance": "Exact committed prior bytes remain in Git at base_sha256; snapshot excludes separately retained draft_history."}
        if digest in history and history[digest] != entry:
            raise ValueError("historical draft evidence changed")
        history[digest] = entry
    if history:
        payload[HISTORY_KEY] = history


def verify_copy_replacement(base, replacement, source, gate):
    import hashlib
    old, new = json.loads(base), json.loads(replacement)
    canonical = verify_current(new, json.loads(source), json.loads(gate))
    old_history, history = old.get(HISTORY_KEY) or {}, new.get(HISTORY_KEY) or {}
    if not isinstance(history, dict) or any(history.get(k) != v for k, v in old_history.items()):
        raise ValueError("historical draft evidence removed or changed")
    digest = hashlib.sha256(base).hexdigest()
    allowed_history = set(old_history) | ({digest} if history_required(old, new) else set())
    if set(history) - allowed_history:
        raise ValueError("unproven new historical draft source")
    if history_required(old, new):
        entry = history.get(digest) or {}
        expected_snapshot = {k: v for k, v in old.items() if k != HISTORY_KEY}
        expected_digest = hashlib.sha256(json.dumps(expected_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (entry.get("base_sha256") != digest or entry.get("snapshot_sha256") != expected_digest or entry.get("historical_not_approval") is not True
                or entry.get("snapshot") != {k: v for k, v in old.items() if k != HISTORY_KEY}):
            raise ValueError("prior copy snapshot not preserved as non-approval history")
    if not set(old) <= set(new):
        raise ValueError("copy root schema field removed")
    current = {str(r["pd_no"]): r for r in new["items"]}
    for row in old.get("items", []):
        if str(row["pd_no"]) in current and not set(row) <= set(current[str(row["pd_no"])]):
            raise ValueError("surviving copy row schema field removed")
    return sorted({str(r["pd_no"]) for r in old.get("items", [])} - canonical)


def record_publication(root):
    import subprocess
    import sys
    root = Path(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.publish_transaction import removed_identities, overlay, sha
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    base = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{COPY_REL}"], check=True, capture_output=True).stdout
    out = root / COPY_REL
    payload = json.loads(out.read_bytes())
    archive_previous(payload, json.loads(base), base)
    replacement = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    evidence = ((root / SOURCE_REL).read_bytes(), (root / GATE_REL).read_bytes())
    ids = verify_copy_replacement(base, replacement, *evidence)
    policy = json.loads((root / "config/publish_policy.json").read_bytes())
    removed = sorted(set(removed_identities(json.loads(base), payload, policy, where=COPY_REL)))
    if removed != ids:
        raise ValueError("copy removals are not exclusively retired canonical S members")
    mpath = root / "data/publish_deletions.json"
    manifest = json.loads(mpath.read_bytes()) if mpath.exists() else {"schema_version": 1, "deletions": []}
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("deletions"), list):
        raise ValueError("invalid deletion manifest")
    result = dict(manifest)
    result["deletions"] = [r for r in manifest["deletions"] if not (r.get("path") == COPY_REL and r.get("policy_ref") == "scripts/build_listing_copy_local.py")]
    if ids:
        result["deletions"].append({"path": COPY_REL, "base_sha256": sha(base), "replacement_sha256": sha(replacement),
            "base_commit": commit, "ids": ids, "delete_file": False, "policy_ref": "scripts/build_listing_copy_local.py",
            "reason": "Retired canonical S draft rows moved to preserved non-approval draft_history; current rows exactly match canonical S and current gate. Exact prior bytes remain in Git."})
    overlay(COPY_REL, base, replacement, base, policy, result, copy_evidence=evidence)
    out.write_bytes(replacement)
    mpath.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"path": COPY_REL, "retired_ids": ids, "historical_not_approval": True}


def main() -> int:
    source = load(SRC, {})
    gate = load(GATE, {})
    previous = load(OUT, {})
    products = source.get("recommendations") or []
    gate_by = {str(x.get("pd_no") or x.get("product_id")): x
               for x in (gate.get("items") or []) if isinstance(x, dict)}
    old_by = {str(x.get("pd_no")): x
              for x in (previous.get("items") or []) if isinstance(x, dict)}

    items = []
    carried = generated = skipped = 0
    for product in products:
        pd_no = str(product.get("pd_no") or "")
        gate_row = gate_by.get(pd_no) or {}
        old = old_by.get(pd_no) or {}
        common = {
            "canonical_product_id": gate_row.get("canonical_product_id"),
            "pd_no": product.get("pd_no"),
            "name_ko": product.get("name"),
            "bucket": product.get("bucket"),
            "price_krw": product.get("price_krw"),
            "rating": product.get("rating"),
            "review_count": product.get("review_count"),
            "shopify_score": product.get("shopify_score"),
            "source_url": product.get("url"),
            "image_url": product.get("image_url"),
        }
        if not gate_row.get("agent_ready"):
            blocked = list(gate_row.get("agent_blocked_by") or ["ontology_gate_missing"])
            items.append({
                **common,
                "copy": None,
                "copy_status": "skipped_prerequisite",
                "generation_mode": "none",
                "agent_blocked_by": blocked,
                "error": "ontology 선행 게이트 미통과: " + ", ".join(blocked),
            })
            skipped += 1
            continue

        if (old.get("copy_status") == "ok"
                and isinstance(old.get("copy"), dict)
                and old.get("generation_mode") != LEGACY_LOCAL_MODE):
            items.append({
                **common,
                "copy": old["copy"],
                "copy_status": "ok",
                "generation_mode": old.get("generation_mode") or "carried_verified_copy",
                "agent_blocked_by": [],
                "error": "",
            })
            carried += 1
            continue

        items.append({
            **common,
            "copy": local_copy(clean(product.get("name")), gate_row),
            "copy_status": "ok",
            "generation_mode": LOCAL_MODE,
            "agent_blocked_by": [],
            "error": "",
        })
        generated += 1

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": now,
        "generator": "scripts/build_listing_copy_local.py",
        "model": "none_local_deterministic",
        "paid_api_called": False,
        "source": "data/daiso_real/shopify_s_recommendations.json",
        "note": (
            "기존 검증 카피를 보존하고 누락분·v1 초안만 제품명·제형·용량 기반의 "
            "보수적 영문 초안으로 생성한다. 효능·인증·임상 결과는 생성하지 않는다."
        ),
        "total": len(items),
        "eligible": carried + generated,
        "ok": carried + generated,
        "failed": 0,
        "skipped_prerequisite": skipped,
        "carried_forward": carried,
        "generated_local": generated,
        "items": items,
    }
    if previous.get(HISTORY_KEY):
        payload[HISTORY_KEY] = previous[HISTORY_KEY]
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"LOCAL_COPY_OK carried={carried} generated={generated} skipped={skipped}")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-publication", action="store_true")
    args = parser.parse_args()
    if args.record_publication:
        print(json.dumps(record_publication(ROOT), ensure_ascii=False))
    else:
        raise SystemExit(main())
