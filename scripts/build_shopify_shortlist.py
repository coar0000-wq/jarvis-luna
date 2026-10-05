#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shopify 스토어에 올릴 상품 목록(shortlist)을 정한다 (2026-09-29).

왜
  S등급 10개를 매번 그대로 스토어에 올리면 점수가 흔들릴 때마다 스토어 전체가
  바뀐다. 무엇을 추가·수정했는지 알 수 없고 업데이트가 의미를 잃는다.
  스토어 대상은 따로 고른 작은 목록이어야 하고, 한 번 들어간 상품은
  점수 순위가 조금 바뀌어도 빠지지 않아야 한다.

정본 순서
  1) data/manual/shopify_shortlist.json  사람이 확정한 목록 (있으면 이것만 쓴다)
  2) 없으면 아래 규칙으로 만든 '제안' 목록. status 가 proposed 로 남는다.

제안 규칙 (추측 없이 저장소 데이터만 쓴다)
  - 게이트 초안 준비(ready)인 S등급만
  - 판매 단위는 Variant 그룹 (리들샷 100/300 은 한 상품의 두 옵션)
  - 미국 매칭 근거가 같은 형태여야 한다. 립·아이·바디·헤어 제품과
    얼굴용 제품을 서로 수요 근거로 쓰지 않는다
  - 같은 미국 상품 하나를 두 상품의 근거로 쓰지 않는다 (점수 높은 쪽만)
  - 매칭 유사도 0.70 이상
  - 최대 MAX_UNITS 단위. 1차 테스트 규모
  - 이미 목록에 있는 단위는 새 후보 점수가 더 높아도 밀어내지 않는다 (sticky)
    빈 자리만 새 후보로 채운다. 기존 선정·관측 대상은 법적 보류로 지우지 않는다.
    ready/eligible_pd_nos 는 초안 자격일 뿐이며 외부 실행 권한은 부여하지 않는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "shopify_shortlist.json"
MANUAL = D / "manual" / "shopify_shortlist.json"
MAX_UNITS = 5
MIN_SIMILARITY = 0.70
FORMS = {
    "lip": ("lip", "립"),
    "eye": ("eye", "아이크림", "아이 크림", "눈가"),
    "body": ("body", "바디"),
    "hair": ("hair", "헤어", "두피", "scalp"),
    "nail": ("nail", "네일"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def forms_of(text: str) -> set[str]:
    low = (text or "").lower()
    return {f for f, words in FORMS.items() if any(w in low for w in words)}


def _context() -> dict:
    recs = (load(D / "daiso_real" / "shopify_s_recommendations.json", {}) or {}).get("recommendations") or []
    gate = {str(x.get("pd_no")): x for x in (load(D / "listing_gate.json", {}) or {}).get("items") or []
            if isinstance(x, dict)}
    master = load(D / "product_master.json", {}) or {}
    pm = {str(x.get("pd_no")): x for x in master.get("products") or [] if isinstance(x, dict)}
    return {"recs": recs, "gate": gate, "pm": pm}


def unit_of(pd_no: str, pm: dict) -> str:
    p = pm.get(pd_no) or {}
    return str((p.get("variant") or {}).get("group_id") or f"VG-{p.get('canonical_product_id') or pd_no}")


def build() -> dict:
    ctx = _context()
    recs, gate, pm = ctx["recs"], ctx["gate"], ctx["pm"]
    previous = load(OUT, {}) or {}
    manual = load(MANUAL, None)

    # 판매 단위(Variant 그룹)별로 S 멤버를 묶는다
    units: dict[str, dict] = {}
    for r in sorted(recs, key=lambda x: -(x.get("shopify_score") or 0)):
        pd_no = str(r.get("pd_no"))
        uid = unit_of(pd_no, pm)
        u = units.setdefault(uid, {"unit_id": uid, "members": [], "score": r.get("shopify_score") or 0,
                                   "evidence": r.get("matched_global") or {}})
        u["members"].append({"pd_no": pd_no, "cp": r.get("canonical_product_id"), "name": r.get("name"),
                             "ready": bool((gate.get(pd_no) or {}).get("ready")),
                             "blocked_by": (gate.get(pd_no) or {}).get("blocked_by") or []})

    def ready_members(u):
        return [m for m in u["members"] if m["ready"]]

    # 규칙 판정: 단위마다 통과/탈락과 사유를 남긴다
    judged, used_evidence = [], {}
    for uid, u in sorted(units.items(), key=lambda kv: -kv[1]["score"]):
        ev = u["evidence"]
        names = " ".join(str(m["name"] or "") for m in u["members"])
        reason = ""
        if not ready_members(u):
            reason = "게이트 초안 미준비: " + ", ".join(sorted({b for m in u["members"] for b in m["blocked_by"]}))
        elif float(ev.get("similarity") or 0) < MIN_SIMILARITY:
            reason = f"미국 매칭 유사도 {ev.get('similarity')} < {MIN_SIMILARITY}"
        elif forms_of(names) != forms_of(str(ev.get("global_product") or "")):
            reason = (f"매칭 근거 형태 불일치: 우리 {sorted(forms_of(names)) or ['얼굴']} vs 미국 "
                      f"{sorted(forms_of(str(ev.get('global_product') or ''))) or ['얼굴']} "
                      f"({str(ev.get('global_product') or '')[:40]})")
        else:
            key = str(ev.get("global_product") or "").strip().lower()
            if key and key in used_evidence:
                reason = f"같은 미국 상품 근거 중복 (이미 {used_evidence[key]} 가 사용)"
            elif key:
                used_evidence[key] = uid
        judged.append({"unit_id": uid, "eligible": not reason, "reason": reason, **u})

    # 이전 목록 유지 (sticky)
    prev_units = {x["unit_id"]: x for x in previous.get("units") or [] if isinstance(x, dict)}
    active: list[dict] = []
    paused: list[dict] = []
    by_id = {j["unit_id"]: j for j in judged}
    for uid, prev in prev_units.items():
        if prev.get("status") not in ("active", "paused"):
            continue
        j = by_id.get(uid)
        retained = prev.get('pd_nos') or []
        retained_current = bool(j and retained and set(retained) <= {m['pd_no'] for m in j['members']})
        if j and (ready_members(j) or (prev.get('status') == 'active' and retained_current)):
            note = "" if j["eligible"] else f"규칙상 근거 약화 · 유지하되 검토: {j['reason']}"
            if not ready_members(j):
                note = '선정·가격 관측 대상 유지; 초안·판매 자격 차단: ' + j['reason']
            row = _unit_row(j, selected_pd_nos=retained if retained_current else None)
            active.append({**row, "added_at": prev.get("added_at"), "status": "active", "note": note})
        else:
            why = (j or {}).get("reason") or "S등급·게이트 대상에서 빠짐"
            paused.append({**(_unit_row(j) if j else {"unit_id": uid, "pd_nos": prev.get("pd_nos", [])}),
                           "added_at": prev.get("added_at"), "status": "paused",
                           "note": f"스토어 대상에서 일시 제외: {why}"})
    for j in judged:
        if len(active) >= MAX_UNITS:
            break
        if j["eligible"] and j["unit_id"] not in prev_units:
            active.append({**_unit_row(j), "added_at": now(), "status": "active", "note": "규칙 제안으로 새로 추가"})

    status, source = "proposed", "rules"
    if isinstance(manual, dict) and manual.get("units"):
        want = {str(x) for x in manual["units"]}
        # pd_no 로 적어도 그 단위를 찾는다
        want |= {unit_of(x, pm) for x in list(want) if x in pm}
        active = [{**_unit_row(by_id[u], selected_pd_nos=[m['pd_no'] for m in by_id[u]['members']]), "added_at": manual.get("confirmed_at"), "status": "active",
                   "note": "사람의 선정 확정만; 초안·판매는 별도 gate 및 L4 승인 필요"} for u in sorted(want) if u in by_id]
        status, source = "confirmed", "data/manual/shopify_shortlist.json"

    active_pd = sorted({m for u in active for m in u["pd_nos"]})
    return {
        "schema_version": 1,
        "generated_at": now(),
        "generator": "scripts/build_shopify_shortlist.py",
        "status": status,
        "source": source,
        "confirmed_by": (manual or {}).get("confirmed_by") if status == "confirmed" else None,
        "rules": {
            "max_units": MAX_UNITS, "min_similarity": MIN_SIMILARITY,
            "unit": "Variant 그룹", "form_match": "립·아이·바디·헤어·네일 형태가 같아야 함",
            "dedupe": "미국 근거 상품 하나당 단위 하나", "sticky": "기존 단위는 밀려나지 않음",
        },
        "active_unit_count": len(active),
        "active_pd_nos": active_pd,
        "eligible_pd_nos": sorted(pd for pd in active_pd if bool((gate.get(pd) or {}).get('ready'))),
        "business_authority": False,
        "selection_scope": 'retained_candidate_and_price_watchlist_not_business_clearance',
        "units": active + paused,
        "not_selected": [{"unit_id": j["unit_id"], "pd_nos": [m["pd_no"] for m in j["members"]],
                          "names": [m["name"] for m in j["members"]], "score": j["score"],
                          "reason": j["reason"] or f"자리 없음 (최대 {MAX_UNITS})"}
                         for j in judged if j["unit_id"] not in {u["unit_id"] for u in active}],
        "how_to_confirm": ("data/manual/shopify_shortlist.json 에 "
                           "{\"units\": [\"VG-...\" 또는 pd_no], \"confirmed_by\": \"이름\", "
                           "\"confirmed_at\": \"YYYY-MM-DD\"} 를 적으면 그 목록만 쓴다."),
    }


def _unit_row(j: dict, selected_pd_nos=None) -> dict:
    ev = j.get("evidence") or {}
    members = [m for m in j['members'] if m['ready']] if selected_pd_nos is None else [m for m in j['members'] if m['pd_no'] in set(selected_pd_nos)]
    return {
        "unit_id": j["unit_id"],
        "pd_nos": [m["pd_no"] for m in members],
        "canonical_product_ids": [m["cp"] for m in members],
        "names": [m["name"] for m in members],
        "eligible_pd_nos": [m['pd_no'] for m in members if m['ready']],
        "business_ready": bool(members) and all(m['ready'] for m in members),
        "score": j["score"],
        "evidence": {"global_product": ev.get("global_product"), "channel": ev.get("channel"),
                     "similarity": ev.get("similarity")},
    }


def active_pd_nos() -> set[str]:
    """export·Action 큐·검증기가 쓰는 스토어 대상 pd_no. 파일이 없으면 빈 집합."""
    doc = load(OUT, {}) or {}
    return {str(x) for x in doc.get("active_pd_nos") or []}


def main() -> int:
    doc = build()
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Shopify shortlist {doc['status']} · 단위 {doc['active_unit_count']}개 · "
          f"SKU {len(doc['active_pd_nos'])}개 · 제외 {len(doc['not_selected'])}개")
    for u in doc["units"]:
        print(f"  [{u['status']}] {u['unit_id']} {u.get('names')} {u.get('note', '')}")
    for x in doc["not_selected"]:
        print(f"  [제외] {x['unit_id']} {x['names'][0][:24]} · {x['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
