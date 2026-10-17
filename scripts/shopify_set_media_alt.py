#!/usr/bin/env python3
"""기존 초안 상품의 이미지 대체텍스트(alt)만 채운다. 생성·가격·공개·이미지 교체는 하지 않는다.

왜 (2026-10-17)
  사용자가 기본 방식으로 지정한 Shopify 9590780723457 (다이소 1084687) 의 영문 이미지
  11장 alt 가 모두 비어 있었다 (data/manual/image_localization/1084687.json
  registration.media[].alt == ""). 대체텍스트가 없으면 검색·AI 검색·접근성에서
  이미지가 무엇인지 알 수 없다.

무엇을 쓰나
  alt 는 매니페스트에 이미 있는 사람이 지은 파일 이름(01-glutathione-main-en 등)과
  영문 제목에서 만든다. 새 주장을 만들지 않는다.

안전장치
  - 매니페스트의 미디어 ID 11개와 파일 이름 순서가 실제 상품과 정확히 같아야 한다.
  - 상점 ID·상품 ID 가 기록과 같아야 한다.
  - 기본은 읽기만 한다 (--dry-run 1). 쓰기는 비어 있는 alt 만 채운다. 이미 사람이
    적은 alt 가 있으면 덮지 않고 멈춘다.
  - 쓰고 나서 다시 읽어 11개가 모두 목표값인지 확인한다.
  - API: productUpdateMedia (2025-10 에서 deprecated 이지만 동작). 대체인 fileUpdate 는
    write_files 권한이 필요한데 이 앱은 write_products 만 있다 (shopify.dev 확인).

사용
  python scripts/shopify_set_media_alt.py --pd-no 1084687 --dry-run 1
  python scripts/shopify_set_media_alt.py --pd-no 1084687 --dry-run 0
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

MANIFESTS = {"1084687": "data/manual/image_localization/1084687.json"}
STORE = "coarfamily.myshopify.com"

READ = """query MediaAltRead($id:ID!){
 shop{id}
 product(id:$id){id status title
  media(first:20){nodes{id mediaContentType status alt ... on MediaImage{image{url}}} pageInfo{hasNextPage}}}}"""
WRITE = """mutation MediaAltWrite($pid:ID!,$media:[UpdateMediaInput!]!){
 productUpdateMedia(productId:$pid,media:$media){media{id alt} mediaUserErrors{field message code}}}"""


class Blocked(RuntimeError):
    """고정된 진단 코드만 담는다. API 응답 원문은 담지 않는다."""


def require(cond, code):
    if not cond:
        raise Blocked(code)


def filename(url: str) -> str:
    return re.sub(r"_\d+x\d+(?=\.(png|jpe?g)$)", "", unquote(urlsplit(url or "").path).rsplit("/", 1)[-1])


def alt_for(title: str, file: str) -> str:
    """'03-customize-your-routine-en.png' -> 'Title — Customize your routine'."""
    stem = re.sub(r"\.(png|jpe?g)$", "", file)
    words = re.sub(r"^\d+-", "", stem)
    words = re.sub(r"-en$", "", words).replace("-", " ").strip()
    words = words[:1].upper() + words[1:]
    return f"{title} — {words}"[:512] if words else title


def plan(manifest: dict) -> dict:
    reg = manifest.get("registration") or {}
    title = str(manifest.get("english_title") or "").strip()
    require(title, "manifest_title_missing")
    pid = f"gid://shopify/Product/{reg.get('product_id')}"
    require(re.fullmatch(r"gid://shopify/Product/\d{1,20}", pid), "manifest_product_id")
    media = reg.get("api_media") or []
    files = [o.get("file") for o in manifest.get("outputs") or []]
    require(media and len(media) == len(files), "manifest_media_count")
    targets = []
    for m, f in zip(media, files):
        url = (m.get("image") or {}).get("url") or ""
        require(filename(url) == f, "manifest_media_order")
        require(re.fullmatch(r"gid://shopify/MediaImage/\d{1,20}", m.get("id") or ""), "manifest_media_id")
        targets.append({"id": m["id"], "file": f, "alt": alt_for(title, f)})
    return {"product_id": pid, "shop_id": reg.get("api_shop_id"), "targets": targets}


def gql(client, query, variables):
    try:
        out = client.gql(query, variables)
    except Exception:  # noqa: BLE001  어댑터 오류 원문에는 응답 본문이 섞일 수 있다
        raise Blocked("api_unavailable_or_permission_denied") from None
    require(isinstance(out, dict) and not out.get("errors"), "api_response")
    return out


def observe(client, p: dict) -> dict[str, str]:
    d = gql(client, READ, {"id": p["product_id"]})
    require((d.get("shop") or {}).get("id") == p["shop_id"], "wrong_shop")
    prod = d.get("product") or {}
    require(prod.get("id") == p["product_id"], "wrong_product")
    conn = prod.get("media") or {}
    require((conn.get("pageInfo") or {}).get("hasNextPage") is False, "media_truncated")
    nodes = conn.get("nodes") or []
    require([n.get("id") for n in nodes] == [t["id"] for t in p["targets"]], "media_ids_or_order_changed")
    for n, t in zip(nodes, p["targets"]):
        require(filename(((n.get("image") or {}).get("url")) or "") == t["file"], "media_file_changed")
    return {n["id"]: (n.get("alt") or "") for n in nodes}


def run(client, manifest: dict, dry_run: bool) -> dict:
    p = plan(manifest)
    before = observe(client, p)
    todo = [t for t in p["targets"] if before[t["id"]] != t["alt"]]
    foreign = [t["file"] for t in todo if before[t["id"]].strip()]
    report = {"schema_version": 1, "product_id": p["product_id"], "dry_run": dry_run,
              "media": len(p["targets"]), "empty_before": sum(1 for v in before.values() if not v.strip()),
              "to_write": [{"file": t["file"], "alt": t["alt"]} for t in todo]}
    if foreign:
        report.update(status="blocked", reason="existing_alt_not_overwritten", existing=foreign)
        return report
    if dry_run or not todo:
        report["status"] = "dry_run" if dry_run else "already_set"
        return report
    out = gql(client, WRITE, {"pid": p["product_id"], "media": [{"id": t["id"], "alt": t["alt"]} for t in todo]})
    errs = ((out.get("productUpdateMedia") or {}).get("mediaUserErrors")) or []
    require(not errs, "media_user_errors")
    after = observe(client, p)
    require(all(after[t["id"]] == t["alt"] for t in p["targets"]), "readback_mismatch")
    report["status"] = "verified"
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pd-no", choices=sorted(MANIFESTS), required=True)
    ap.add_argument("--dry-run", choices=["0", "1"], default="1")
    ap.add_argument("--output", type=Path, default=Path("out/shopify_media_alt.json"))
    a = ap.parse_args(argv)
    out = a.output if a.output.is_absolute() else ROOT / a.output
    try:
        manifest = json.loads((ROOT / MANIFESTS[a.pd_no]).read_text(encoding="utf-8-sig"))
        plan(manifest)                                    # 로컬 검사를 인증 전에 끝낸다
        require(os.environ.get("SHOPIFY_STORE", "") == STORE, "wrong_store_environment")
        from daiso_daily_beauty_to_shopify import Shopify  # noqa: PLC0415
        report = run(Shopify(), manifest, dry_run=a.dry_run == "1")
    except Exception as exc:  # noqa: BLE001
        report = {"schema_version": 1, "status": "blocked",
                  "reason": str(exc) if isinstance(exc, Blocked) else "setup_unavailable"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("status", "reason", "empty_before", "media")}, ensure_ascii=False))
    return 0 if report["status"] in {"dry_run", "verified", "already_set"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
