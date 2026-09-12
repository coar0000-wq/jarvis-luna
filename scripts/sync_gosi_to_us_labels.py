#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge collected Daiso notice fields into the US label registry.

Source:
  data/gosi.json

Target:
  data/daiso_real/daiso_us_labels.json

Only empty target fields are filled.
Existing verified label values are never overwritten.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

GOSI = DATA / "gosi.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"

REQUIRED_LABEL_FIELDS = (
    "net_contents",
    "ingredients_inci",
    "manufacturer",
    "country_of_origin",
)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8-sig")
        )
    except (
        OSError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise RuntimeError(
            f"JSON 읽기 실패: {path}: {exc}"
        ) from exc


def text(value: Any) -> str:
    return str(value or "").strip()


def main() -> int:
    gosi_doc = load_json(GOSI, {})
    labels = load_json(LABELS, {})

    items = gosi_doc.get("items") or {}

    if isinstance(items, list):
        items = {
            str(row.get("product_id")): row
            for row in items
            if (
                isinstance(row, dict)
                and row.get("product_id")
            )
        }

    if not isinstance(items, dict):
        raise RuntimeError(
            "data/gosi.json의 items는 "
            "object 또는 list여야 합니다."
        )

    if not isinstance(labels, dict):
        raise RuntimeError(
            "data/daiso_real/daiso_us_labels.json은 "
            "object여야 합니다."
        )

    changed = 0
    complete = 0
    now = datetime.now(timezone.utc).isoformat()

    for raw_id, source in items.items():
        if not isinstance(source, dict):
            continue

        pd_no = str(
            source.get("product_id") or raw_id
        )

        target = labels.setdefault(pd_no, {})

        if (
            not text(target.get("product_name_kr"))
            and text(source.get("name"))
        ):
            target["product_name_kr"] = text(
                source["name"]
            )
            changed += 1

        mappings = {
            "net_contents": "volume",
            "manufacturer": "maker",
            "country_of_origin": "origin",
        }

        for target_key, source_key in mappings.items():
            if (
                not text(target.get(target_key))
                and text(source.get(source_key))
            ):
                target[target_key] = text(
                    source[source_key]
                )
                changed += 1

        if (
            not text(target.get("warnings_source"))
            and text(source.get("warnings"))
        ):
            target["warnings_source"] = text(
                source["warnings"]
            )
            changed += 1

        if (
            not text(target.get("ingredients_source"))
            and text(source.get("ingredients"))
        ):
            target["ingredients_source"] = text(
                source["ingredients"]
            )
            target["ingredients_source_type"] = (
                "daiso_product_notice"
            )
            changed += 1

        if (
            not text(target.get("ingredients_inci"))
            and text(source.get("ingredients_inci"))
            and source.get("ingredients_language") == "en"
        ):
            target["ingredients_inci"] = text(
                source["ingredients_inci"]
            )
            target["ingredients_source_type"] = (
                "verified_english_inci"
            )
            changed += 1

        if not text(target.get("source_url")):
            target["source_url"] = source.get(
                "source_url",
                "",
            )

        target["gosi_ok"] = all(
            text(target.get(field))
            for field in REQUIRED_LABEL_FIELDS
        )

        target["last_gosi_sync_at"] = now

        target.setdefault(
            "source_type",
            "daiso_product_notice",
        )

        if target["gosi_ok"]:
            complete += 1

    LABELS.write_text(
        json.dumps(
            labels,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        "고시→영문 라벨 동기화 완료: "
        f"변경 {changed}개 필드, "
        f"완성 라벨 {complete}개"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
