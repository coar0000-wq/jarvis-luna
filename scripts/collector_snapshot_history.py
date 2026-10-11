#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rotating collector snapshots -> exact reason manifest entries (no guard waiver).

왜 필요한가 (2026-10-11)
  아마존 신상품·베스트셀러, SerpApi 시장가, 실지식 소스 목록은 매 실행마다 "지금 순위"로
  통째로 바뀐다. 순위에서 빠진 상품은 데이터 손실이 아니라 정상 교체다.
  그런데 발행 트랜잭션은 사라진 식별자(url/id 등)에 사유 기록을 요구한다. 사유 기록을
  만드는 장치가 없어서 이 수집기들은 10-09 이후 한 번도 발행하지 못했다.

무엇을 하나
  - 선언된 파일의 선언된 "순위 목록" 안에서만 사라진 식별자를 허용한다.
  - 그 밖(필드 삭제, 다른 목록의 식별자 삭제)은 그대로 막는다. 정책 파일은 건드리지 않는다.
  - 이전 스냅샷의 정확한 바이트는 git 커밋에 그대로 남아 있다. base_sha256 이 그 바이트를 가리킨다.
  - data/publish_deletions.json 에 path/base_sha256/replacement_sha256/ids/reason 을 적고,
    publish_transaction.deletion_authorized 로 실제 통과 여부를 확인한 뒤에만 쓴다.

사용: python scripts/collector_snapshot_history.py data/amazon_new_products.json [...]
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_transaction import deletion_authorized, identity, removed_identities  # noqa: E402

MANIFEST = "data/publish_deletions.json"
POLICY = "config/publish_policy.json"
POLICY_REF = "scripts/collector_snapshot_history.py"

# 파일별로 "통째로 교체되는 순위 목록" 경로만 선언한다. * 는 한 단계 키.
ROTATING = {
    "data/amazon_products.json": ["products"],
    "data/amazon_new_products.json": ["products"],
    "data/amazon_movers_products.json": ["products"],
    "data/walmart_products.json": ["products"],
    "data/oliveyoung_us_products.json": ["products"],
    "data/sokoglam_products.json": ["products"],
    "data/us_beauty_products.json": ["products", "items", "by_store/*", "by_store/*/products", "by_store/*/items"],
    "data/serpapi_market.json": ["prices/items", "prices/failures", "trends/items", "trends/failures"],
    "data/knowledge/real_sources.json": ["sources/*/items"],
    # 환율 관측은 통째로 새 값으로 바뀐다 (대조 목록·보조 필드 포함). 다른 칸은 그대로 지킨다.
    "data/daiso_real/collection_status.json": ["fx"],
}


def sha(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def head_bytes(root: Path, rel: str) -> bytes | None:
    p = subprocess.run(["git", "-C", str(root), "show", "HEAD:" + rel], capture_output=True)
    return p.stdout if p.returncode == 0 else None


def rotating(rel: str, where: tuple[str, ...]) -> bool:
    path = "/".join(where)
    return any(fnmatch.fnmatchcase(path, pat) and path.count("/") == pat.count("/") for pat in ROTATING.get(rel, []))


def allowed_removals(rel: str, old, new, policy: dict, where: tuple[str, ...] = ()) -> list[str]:
    """Identities removed only inside declared rotating lists; anything else raises."""
    contract = {"identity_fields": policy["identity_fields"]}
    if rotating(rel, where):
        if not ((isinstance(old, list) and isinstance(new, list)) or (isinstance(old, dict) and isinstance(new, dict))):
            raise ValueError(f"rotating container type changed: {rel}/{'/'.join(where)}")
        return list(removed_identities(old, new, contract))
    if isinstance(old, dict):
        if not isinstance(new, dict):
            raise ValueError(f"container replaced: {rel}/{'/'.join(where)}")
        out = []
        for key, value in old.items():
            if key not in new:
                raise ValueError(f"field removal outside rotating lists: {rel}/{'/'.join(where + (key,))}")
            out.extend(allowed_removals(rel, value, new[key], policy, where + (key,)))
        return out
    if isinstance(old, list):
        if not isinstance(new, list):
            raise ValueError(f"list replaced: {rel}/{'/'.join(where)}")
        if removed_identities(old, new, contract):
            raise ValueError(f"identity removal outside rotating lists: {rel}/{'/'.join(where)}")
        field = identity(old + new, contract["identity_fields"])
        if field:
            rows = {str(r[field]): r for r in new}
            out = []
            for r in old:
                out.extend(allowed_removals(rel, r, rows[str(r[field])], policy, where + (str(r[field]),)))
            return out
    return []


def update(root: Path, paths: list[str]) -> dict:
    root = Path(root).absolute()
    policy = json.loads((root / POLICY).read_text(encoding="utf-8"))
    mpath = root / MANIFEST
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {"schema_version": 1, "deletions": []}
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("deletions"), list):
        raise ValueError("publish deletion manifest malformed")
    result = deepcopy(manifest)
    report = {}
    for rel in paths:
        if rel not in ROTATING:
            raise ValueError(f"not a declared rotating snapshot: {rel}")
        base = head_bytes(root, rel)
        local_path = root / rel
        result["deletions"] = [r for r in result["deletions"]
                               if not (r.get("path") == rel and r.get("policy_ref") == POLICY_REF)]
        if base is None or not local_path.exists():
            report[rel] = "no_base_or_local"
            continue
        local = local_path.read_bytes()
        if local == base:
            report[rel] = "unchanged"
            continue
        ids = sorted(set(str(x) for x in allowed_removals(rel, json.loads(base), json.loads(local), policy)))
        if not ids:
            report[rel] = "no_removals"
            continue
        entry = {"path": rel, "base_sha256": sha(base), "replacement_sha256": sha(local), "ids": ids,
                 "reason": "Rotating ranking/search snapshot replaced by a newer capture; exact prior bytes remain in git at base_sha256.",
                 "policy_ref": POLICY_REF, "delete_file": False}
        result["deletions"].append(entry)
        if not deletion_authorized(rel, base, ids, result, replacement=local):
            raise ValueError(f"manifest entry does not satisfy removal contract: {rel}")
        report[rel] = f"authorized {len(ids)} rotated ids"
    if result != manifest:
        mpath.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> int:
    paths = [p for p in sys.argv[1:] if p in ROTATING]
    try:
        report = update(ROOT, paths)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"COLLECTOR_SNAPSHOT_BLOCKED {exc}")
        return 1
    print("COLLECTOR_SNAPSHOT_OK " + json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
