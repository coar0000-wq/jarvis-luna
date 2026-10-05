#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline Korean-notice to US-label data adapter, not a safety/legal approval.

Only registry-issued product IDs can be added. Human-owned values and approval
artifacts are preserved. Derived INCI whose upstream disappears or changes is
archived and explicitly ineligible until it can be recomputed.
"""
from __future__ import annotations

import json
import hashlib
from copy import deepcopy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inci_resolver import InciResolver, load_manual_overrides  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

GOSI = DATA / "gosi.json"
DICT = DATA / "inci_dictionary.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"
MASTER = DATA / "product_master.json"

REQUIRED_LABEL_FIELDS = (
    "net_contents",
    "ingredients_inci",
    "manufacturer",
    "country_of_origin",
)

# 이 스크립트가 고시에서 옮겨 쓰는 칸이다. 사람이 넣는 칸은 여기 없다.
MACHINE_FIELDS = (
    "product_name_kr",
    "net_contents",
    "manufacturer",
    "country_of_origin",
    "ingredients_inci",
)

# 사람이 나중에 채우라고 넣어 둔 안내문. 값이 아니라 빈 칸으로 본다.
# build_listing_gate.py 의 _PLACEHOLDER_RE 와 같은 규칙을 쓴다.
# 두 곳이 다르면 한쪽은 통과시키고 한쪽은 막아서 원인을 못 찾는다.
PLACEHOLDER_RE = re.compile(
    r"(실제\s*확인|실제\s*포장|실제\s*제품|실제\s*상품|placeholder|TODO|TBD"
    r"|미입력|확인\s*필요|작성\s*필요|상세페이지\s*참조"
    r"|입력\s*필요|추후\s*(?:입력|확인)|not\s*(?:available|provided|verified)"
    r"|to\s*be\s*(?:confirmed|filled|verified)|pending|unknown|미확인"
    r"|\bTBC\b|unverified|fill\s*(?:in|out)|replace\s*with|enter\s+(?:your|the)"
    r"|needs?\s*(?:review|verification)|미정|없음)",
    re.I,
)

ORIGIN_EN = {
    "대한민국": "Korea",
    "한국": "Korea",
    "korea": "Korea",
    "republic of korea": "Korea",
    "중국": "China",
    "일본": "Japan",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"JSON 읽기 실패: {path}: {exc}") from exc


def text(value: Any) -> str:
    return str(value or "").strip()


def split_ingredients(raw: str) -> list[str]:
    """한국어 전성분을 성분 단위로 나눈다.

    1,2-헥산다이올 처럼 이름 안에 쉼표가 든 성분이 있다.
    그래서 그냥 쉼표로 자르면 두 조각이 난다. 먼저 보호한다.
    """
    s = text(raw)
    if not s:
        return []

    # 고시 원문에는 성분이 아닌 것이 섞여 들어온다 (2026-09-13).
    # 이런 것들을 성분 이름으로 알고 사전을 뒤지다 못 찾아서 상품이 막혔다.
    #   "베타-글루칸\n\n구) 정제수"
    #   "향료\n* 제품 리뉴얼로 전성분이 일부 변경되었습니다"
    # 사전에 없는 성분이 아니라 내 파서가 덜 다듬은 것이었다.
    s = "\n".join(l for l in s.split("\n")
                  if not l.strip().startswith(("*", "※")))

    # 숫자,숫자 형태의 쉼표는 성분 이름 안의 것이다
    s = re.sub(r"(\d),(\d)", r"\1\2", s)
    parts = []
    # 줄바꿈도 성분 구분이다. 쉼표만 보면 두 성분이 한 덩이로 붙는다.
    for chunk in re.split(r"[,·\n]", s):
        c = chunk.replace("", ",").strip()
        # 괄호 안 비율 표기는 INCI 에 넣지 않는다
        c = re.sub(r"\([^)]*\)", "", c).strip()
        # 구) 신) 같은 개정 표기가 앞에 붙는다
        c = re.sub(r"^[구신]\s*\)\s*", "", c).strip()
        c = c.strip(" .;·")
        if c:
            parts.append(c)
    return parts


def _nospace(s: str) -> str:
    return re.sub(r"\s+", "", s)


_NOSPACE_CACHE: dict[int, dict] = {}


def nospace_index(table: dict) -> dict:
    """공백을 둔 색인을 한 번만 만든다.

    정본은 학명을 속과 종 사이에 공백을 두고 적는다.
      정본   '클로렉라 불가리스추출물'
      라벨   '클로렉라불가리스추출물'
    제조사가 공백을 빼고 인쇄하는 일이 흔하다. 그것 하나 때문에
    상품 하나가 통째로 막혔다. 같은 성분을 못 찾은 것이지 사전에
    없던 것이 아니다.

    공백만 무시한다. 다른 글자는 건드리지 않는다. 임의로 닮은 것을
    찾아 이으면 다른 성분을 적게 된다.
    """
    key = id(table)
    idx = _NOSPACE_CACHE.get(key)
    if idx is None:
        idx = {}
        for k, v in table.items():
            idx.setdefault(_nospace(k), v)
        _NOSPACE_CACHE[key] = idx
    return idx


def to_inci(raw: str, resolver: InciResolver) -> tuple[str, list[str], list[dict], list[dict]]:
    """한국어 전성분을 영문 INCI 로 바꾼다.

    하나라도 정본으로 못 이으면 빈 문자열을 돌려준다.
    일부만 영문인 성분표는 쓸 수 없다. 미국에서 라벨 위반이다.

    그대로 못 찾으면 공백, 표기 규칙, 한두 글자 차이, 앞뒤 순서까지
    본다. 판단은 inci_resolver 가 하고 여기서는 결과만 모은다.
    지어내는 것이 아니라 같은 이름을 알아보는 것이다. 되돌린 자리는
    전부 남겨 사람이 뒤집을 수 있게 한다.
    """
    parts = split_ingredients(raw)
    if not parts:
        return "", [], [], []

    out: list[str] = []
    missing: list[str] = []
    fixed: list[dict] = []
    review: list[dict] = []

    for p in parts:
        r = resolver.resolve(p)
        if r.ok:
            out.append(r.value)
            if r.method not in ("exact", "nospace"):
                fixed.append(r.as_record())
            continue
        missing.append(p)
        review.append(r.as_record())

    if missing:
        return "", missing, fixed, review
    return ", ".join(out), [], fixed, review


# Only these fields may be machine-derived. Everything else is human-owned.
HUMAN_FIELDS = (
    "responsible_person", "responsible_person_address", "address",
    "product_name_en", "directions_en", "warnings_en",
    "actual_label_evidence", "product_safety_evidence", "responsible_person_evidence",
)
_NULL_VALUES = {"n/a", "na", "none", "null", "nan", "-", "--", "?", "0"}
_CP_RE = re.compile(r"^CP\d{6}$")


def real(value: Any) -> bool:
    # Containers, booleans and instructional strings are never required label text.
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().lower() not in _NULL_VALUES
            and not PLACEHOLDER_RE.search(value))


def rows_by_id(doc: Any, key: str = "items") -> dict[str, dict]:
    """Read wrapped dict/list or a legacy map without mutating its wrapper."""
    rows = doc.get(key) if isinstance(doc, dict) and key in doc else doc
    if not isinstance(rows, (dict, list)):
        raise ValueError(f"{key} must be an object or list")
    result = {}
    pairs = rows.items() if isinstance(rows, dict) else enumerate(rows)
    for raw_id, row in pairs:
        if not isinstance(row, dict):
            continue
        pd_no = text(row.get("pd_no") or row.get("product_id"))
        if not pd_no and isinstance(rows, dict):
            pd_no = str(raw_id)
        if pd_no:
            if pd_no in result:
                raise ValueError("duplicate product ID")
            result[pd_no] = row
    return result


def canonical_registry(master: Any) -> dict[str, str]:
    registry = master.get("pd_no_to_cp", {}) if isinstance(master, dict) else {}
    if not isinstance(registry, dict):
        raise ValueError("canonical registry must be an object")
    result = {str(k): str(v) for k, v in registry.items() if _CP_RE.fullmatch(str(v))}
    if len(result) != len(registry) or len(set(result.values())) != len(result):
        raise ValueError("invalid or duplicate canonical IDs")
    return result


def current_s_registry(score: Any, master: Any) -> dict[str, str]:
    """Stable union of current score/master S rows, only already-issued CP IDs."""
    registry = canonical_registry(master)
    ids = set()
    if not registry and any(row.get("grade") == "S"
            for doc, key in ((score, "all_scored"), (master, "products"))
            for row in rows_by_id(doc.get(key, []) if isinstance(doc, dict) else []).values()):
        raise ValueError("current S rows require an existing canonical registry")
    for doc, key in ((score, "all_scored"), (master, "products")):
        for pd_no, row in rows_by_id(doc.get(key, []) if isinstance(doc, dict) else []).items():
            if row.get("grade") == "S" and pd_no in registry:
                if row.get("canonical_product_id") not in (None, "", registry[pd_no]):
                    raise ValueError("canonical product ID mismatch")
                ids.add(pd_no)
    return {pd_no: registry[pd_no] for pd_no in sorted(ids)}


def human_owned(target: dict, key: str, pd_no: str = "") -> bool:
    provenance = target.get("field_provenance") or {}
    record = provenance.get(key, {}) if isinstance(provenance, dict) else {}
    artifact = target.get("actual_label_evidence") or {}
    approved_actual = (isinstance(artifact, dict) and artifact.get("human_approved") is True
                       and artifact.get("source_type") in ("actual_packaging", "approved_us_label")
                       and text(artifact.get("product_id") or artifact.get("pd_no")) == pd_no
                       and all(real(artifact.get(f)) for f in ("evidence_ref", "reviewed_by", "reviewed_at"))
                       and key in artifact.get("approved_fields", MACHINE_FIELDS))
    return (key not in MACHINE_FIELDS or approved_actual or
            (isinstance(record, dict) and (record.get("owner") == "human"
             or record.get("human_approved") is True)) or
            target.get("manual_approved") is True or target.get("human_verified") is True)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def field_current(label: dict, field: str) -> bool:
    provenance = label.get("field_provenance") or {}
    record = provenance.get(field, {}) if isinstance(provenance, dict) else {}
    if isinstance(record, dict) and (record.get("status") in ("stale", "missing")
                                   or record.get("eligible") is False):
        return False
    if field == "ingredients_inci":
        return (label.get("ingredients_inci_status") not in ("stale", "missing")
                and label.get("ingredients_inci_eligible") is not False)
    return True


def sync_labels(gosi_doc: Any, labels_doc: Any, score_doc: Any, master_doc: Any,
                resolver: InciResolver, timestamp: str) -> tuple[dict, dict]:
    """Pure offline adapter. Parsed notices never grant legal/safety approval."""
    if not isinstance(labels_doc, dict):
        raise ValueError("labels must be an object")
    payload = deepcopy(labels_doc)
    wrapped = "items" in payload
    registry = rows_by_id(payload)
    sources = rows_by_id(gosi_doc)
    cp = canonical_registry(master_doc)
    current_s = current_s_registry(score_doc, master_doc)
    # Existing labels are retained. New IDs must already belong to the CP registry.
    for pd_no in sorted(set(current_s) | (set(sources) & set(cp))):
        registry.setdefault(pd_no, {})
    report = {"generated_at": timestamp, "current_s_count": len(current_s),
              "filled": 0, "replaced": 0, "complete": 0, "items": {}}
    for pd_no, target in registry.items():
        source = sources.get(pd_no, {})
        if pd_no in cp:
            target.setdefault("canonical_product_id", cp[pd_no])
        provenance = target.get("field_provenance")
        if provenance is not None and not isinstance(provenance, dict):
            raise ValueError("field provenance must be an object")
        if not isinstance(provenance, dict):
            provenance = {}
            target["field_provenance"] = provenance
        derived = [f for f in target.get("_자동으로_채운_칸", [])
                   if f in MACHINE_FIELDS] if isinstance(target.get("_자동으로_채운_칸"), list) else []
        # A derivation marker proves only INCI ownership, not ownership of other fields.
        if target.get("ingredients_inci_source") == "kr_notice_via_dictionary":
            if "ingredients_inci" not in derived:
                derived.append("ingredients_inci")
        declared_inci_derived = "ingredients_inci" in derived
        inci_ownership = provenance.get("ingredients_inci") or {}
        explicit_human_inci = (isinstance(inci_ownership, dict) and
            (inci_ownership.get("owner") == "human" or inci_ownership.get("human_approved") is True))
        explicit_human_inci = (explicit_human_inci or target.get("manual_approved") is True
                               or target.get("human_verified") is True)
        derived = [f for f in derived if not human_owned(target, f, pd_no)]
        for f, record in provenance.items():
            if (f in MACHINE_FIELDS and isinstance(record, dict)
                    and record.get("owner") == "machine" and not human_owned(target, f, pd_no)
                    and f not in derived):
                derived.append(f)

        def stale(key: str, reason: str) -> None:
            record = provenance.setdefault(key, {"owner": "machine"})
            record.update(status="stale", eligible=False, stale_reason=reason,
                          human_verified=False)
            if key == "ingredients_inci":
                target["ingredients_inci_status"] = "stale"
                target["ingredients_inci_eligible"] = False

        def put(key: str, value: Any, raw: Any = None) -> bool:
            if human_owned(target, key, pd_no) or (real(target.get(key)) and key not in derived):
                return False
            if not real(value):
                if key in derived:
                    stale(key, "upstream_missing_or_placeholder")
                return False
            if text(target.get(key)) != value.strip():
                report["replaced" if text(target.get(key)) and not real(target.get(key)) else "filled"] += 1
                target[key] = value.strip()
            if key not in derived:
                derived.append(key)
            provenance[key] = {"owner": "machine", "status": "current", "eligible": True,
                               "source_type": "daiso_product_notice", "human_verified": False,
                               "source_fingerprint": fingerprint(text(raw if raw is not None else value))}
            return True

        put("product_name_kr", source.get("name"))
        put("net_contents", source.get("volume"))
        put("manufacturer", source.get("maker"))
        origin = text(source.get("origin"))
        put("country_of_origin", ORIGIN_EN.get(origin.lower(), origin), origin)
        new_source = text(source.get("ingredients")) if real(source.get("ingredients")) else ""
        old_source = text(target.get("ingredients_source"))
        inci_machine = ("ingredients_inci" in derived or
                        (declared_inci_derived and not explicit_human_inci))
        old_record = provenance.get("ingredients_inci") or {}
        changed = not new_source or old_source != new_source
        if (inci_machine and real(target.get("ingredients_inci")) and
                (changed or old_record.get("source_fingerprint") not in (None, fingerprint(new_source)))):
            history = target.setdefault("ingredients_inci_history", [])
            if not isinstance(history, list):
                raise ValueError("INCI history must be a list")
            fact = {"value": target["ingredients_inci"], "ingredients_source": old_source,
                    "source_fingerprint": fingerprint(old_source), "status": "historical_stale",
                    "eligible": False}
            if not any(all(h.get(k) == fact[k] for k in fact) for h in history if isinstance(h, dict)):
                history.append({**fact, "observed_at": timestamp})
            stale("ingredients_inci", "upstream_missing" if not new_source else "upstream_changed")
        inci, missing, fixed, review = to_inci(new_source, resolver)
        if inci and put("ingredients_inci", inci, new_source):
            target["ingredients_source"] = new_source
            target["ingredients_source_type"] = "daiso_product_notice"
            target["ingredients_inci_source"] = "kr_notice_via_dictionary"
            target["ingredients_inci_status"] = "current_derived"
            target["ingredients_inci_eligible"] = True
        elif inci_machine and not inci:
            stale("ingredients_inci", "upstream_unresolved" if new_source else "upstream_missing")
        # Do not relabel a human INCI value as dictionary-derived or change its evidence.
        if real(source.get("warnings")) and not real(target.get("warnings_source")):
            target["warnings_source"] = source["warnings"].strip()
        missing_fields = [f for f in REQUIRED_LABEL_FIELDS
                          if not real(target.get(f)) or not field_current(target, f)]
        target["gosi_ok"] = not missing_fields  # data completeness only, never human approval
        target["gosi_ok_scope"] = "machine_notice_completeness_not_US_or_safety_approval"
        target["_자동으로_채운_칸"] = derived
        target["last_gosi_sync_at"] = timestamp
        target.setdefault("source_type", "daiso_product_notice")
        report["complete"] += int(not missing_fields)
        report["items"][pd_no] = {"missing_fields": missing_fields,
                                  "unresolved_ingredients": missing,
                                  "resolved_spellings": fixed, "needs_review": review}
    if wrapped:
        payload["items"] = registry
        payload["updated_at"] = timestamp
    else:
        # Keep non-row legacy metadata instead of silently discarding it.
        payload.update(registry)
    return payload, report


def main() -> int:
    dictionary = load_json(DICT, {}).get("kr_to_inci") or {}
    resolver = InciResolver(dictionary, load_manual_overrides(ROOT))
    timestamp = datetime.now(timezone.utc).isoformat()
    payload, report = sync_labels(load_json(GOSI, {}), load_json(LABELS, {}),
                                  load_json(SCORE, {}), load_json(MASTER, {}),
                                  resolver, timestamp)
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LABELS.parent / "us_label_sync_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Current S coverage {report['current_s_count']}; machine-complete {report['complete']}; not legal approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
