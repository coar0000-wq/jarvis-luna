#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS 두뇌(옵시디언 볼트)에 팀·카테고리 전담팀·S상품·Shopify 상태를 데이터로 기록한다.

왜 (2026-10-11 사용자 지시)
  "옵시디언 그래프뷰는 자비스 두뇌다. 모든 데이터가 그래프뷰에 왔다가 나가야 한다."
  지금까지 볼트에는 수집 지식(레코드)만 들어갔고, 팀 활동·S상품·법률/가격 게이트·Shopify 등록은
  JSON 에만 있었다. 팀 노트(Knowledge/Teams)는 10-03 이후 갱신되지 않았다.

무엇을
  obsidian/JARVIS_LUNA/Brain/ 아래에
    JARVIS Brain.md            허브 (전담팀·팀·스토어·지식 인덱스로 연결)
    Desks/<전담팀>.md          스킨케어·메이크업·바디 전담팀 - 담당 S상품과 다음 작업
    Products/<pd_no>.md        S상품 - 속성(등급·점수·공개 가능·막힌 이유·Shopify 상태·가격)
    Teams/<팀>.md              11개 팀과 비서실장 - 마지막 활동·상태·다음 작업
    Shopify Store.md           Shopify 에 등록된 상품
  를 쓰고, 같은 내용을 data/jarvis_brain.json 으로 내보낸다(두뇌에서 나가는 데이터).
  링크는 데이터로 확인되는 관계(담당 전담팀, 등록 여부, 같은 팀의 지식 허브)만 만든다. 추정 링크는 없다.
  내용이 같으면 파일을 다시 쓰지 않는다(updated_at 만 다른 경우 포함).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
BRAIN = VAULT / "Brain"
OUT = DATA / "jarvis_brain.json"
DESK_NAME = {"skincare": "스킨케어 전담팀", "makeup": "메이크업 전담팀", "body": "바디 전담팀"}
UPDATED_RE = re.compile(r"^updated_at: .*$", re.M)
SAFE_RE = re.compile(r"[\\/:*?\"<>|#^\[\]]+")


def load(rel: str, default):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def safe(name: str, limit: int = 60) -> str:
    return re.sub(r"\s+", " ", SAFE_RE.sub(" ", str(name or ""))).strip()[:limit].strip() or "noname"


def yv(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(yv(v) for v in value) + "]"
    return '"' + str(value if value is not None else "").replace('"', "'").replace("\n", " ") + '"'


def write(path: Path, title: str, kind: str, props: dict, body: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ["---", f"title: {yv(title)}", f"type: {kind}", "status: generated-from-jarvis-data",
            f"updated_at: {datetime.now(timezone.utc).isoformat()}"]
    head += [f"{k}: {yv(v)}" for k, v in props.items() if v not in (None, "", [])]
    text = "\n".join(head) + "\n---\n\n# " + title + "\n\n" + body.strip() + "\n"
    if path.exists():
        try:
            if UPDATED_RE.sub("", path.read_text(encoding="utf-8")) == UPDATED_RE.sub("", text):
                return False
        except (OSError, UnicodeDecodeError):
            pass
    path.write_text(text, encoding="utf-8")
    return True


def team_hub_link(name: str) -> str | None:
    stem = f"팀 · {name}"
    return f"[[{stem}]]" if (VAULT / "Knowledge" / "Teams" / f"{stem}.md").exists() else None


def review_text(value, limit: int = 1200) -> str:
    # Source text must not synthesize Obsidian relations.
    return str(value or "UNKNOWN").replace("[[", "［［").replace("]]", "］］").replace("\n", " ")[:limit]


def team_video_reviews(learning: dict, team_id: str) -> list[dict]:
    block = (learning.get("teams") or {}).get(team_id) or {}
    items = block.get("items") or ([block["this_week_action"]] if block.get("this_week_action") else [])
    return [{**item, "status": "shared-review-directive",
             "external_team_execution_verified": False, "business_approval": False}
            for item in items if isinstance(item, dict) and team_id in (item.get("teams") or [])][:10]


def video_review_body(items: list[dict]) -> str:
    if not items:
        return ""
    lines = ["", "", "## 영상 학습 공유 검토 지시", "",
             "상태: shared-review-directive · 외부 도구 실행·검증된 성과·사업 승인 아님. 검토 시각은 수집/출처 최신성 시각이 아닙니다."]
    for item in items:
        ev = item.get("evidence") or {}
        url = str(ev.get("url") or "")
        source = f"[외부 영상 원문](<{url}>)" if url.startswith(("https://", "http://")) and not any(c in url for c in "<>\n\r") else "UNKNOWN"
        lines += ["", f"- {review_text(item.get('tactic'), 200)} ({review_text(item.get('id'), 100)})",
                  f"  - 적용 검토 과제: {review_text(item.get('action'))}",
                  f"  - 근거: {source} · 영상 ID: {review_text(ev.get('video_id'), 100)}",
                  f"  - 타임스탬프: {review_text(ev.get('timestamp'), 200)} · 기준: {review_text(ev.get('timestamp_basis') or ev.get('timestamp_status'), 200)}",
                  f"  - 원본 검토 시각: {review_text(item.get('reviewed_at'), 100)}"]
        if ev.get("chapter_hint"):
            lines.append(f"  - 업로더 챕터 힌트 (자막 시각 아님): {review_text(ev['chapter_hint'], 300)}")
    return "\n".join(lines)


def build() -> dict:
    runtime = load("data/dashboard_runtime.json", {}) or {}
    learning = load("data/team_learning.json", {}) or {}
    score = load("data/daiso_real/shopify_demand_score.json", {}) or {}
    srec = load("data/daiso_real/shopify_s_recommendations.json", {}) or {}
    gate = {str(r.get("pd_no")): r for r in (load("data/listing_gate.json", {}) or {}).get("items") or []
            if isinstance(r, dict)}
    reg = {}
    for r in (load("data/shopify_daily_registry.json", {}) or {}).get("items") or []:
        if isinstance(r, dict) and r.get("pd_no"):
            reg[str(r["pd_no"])] = r
    scored = {str(r.get("pd_no")): r for r in score.get("all_scored") or [] if isinstance(r, dict)}

    products = []
    for rec in srec.get("recommendations") or []:
        pd = str(rec.get("pd_no") or "")
        if not pd:
            continue
        row, g, rg = scored.get(pd, {}), gate.get(pd, {}), reg.get(pd, {})
        if row.get("grade") != "S":
            continue
        desk = rec.get("desk") or row.get("desk") or "skincare"
        price = g.get("price") or {}
        blocked = list(g.get("public_blocked_by") or [])
        status = rg.get("status") or ("공개 가능" if g.get("public_ready") else "작업 중")
        nxt = ("공개 이력 기록, 현재 Shopify 상태는 별도 확인 필요" if rg.get("status") == "ACTIVE" else
               "다음 일일 등록 대상" if g.get("public_ready") and not rg else
               ("막힌 항목 해결: " + ", ".join(blocked)) if blocked else "게이트 판정 대기")
        products.append({
            "pd_no": pd, "name": rec.get("name"), "desk": desk, "desk_name": DESK_NAME.get(desk, desk),
            "bucket": rec.get("bucket"), "grade": "S", "score": rec.get("shopify_score"), "s_rule": rec.get("s_rule"),
            "public_ready": bool(g.get("public_ready")), "blocked_by": blocked,
            "shopify_status": rg.get("status"), "registered_at": rg.get("date"),
            "price_usd": rg.get("single_usd") or price.get("price_usd"),
            "margin_pct": rg.get("single_margin_pct") or price.get("margin_pct"),
            "daiso_url": rec.get("url"), "next_action": nxt, "status_label": status})

    desks = {}
    for d, name in DESK_NAME.items():
        mine = [p for p in products if p["desk"] == d]
        desks[d] = {"name": name, "s_count": len(mine),
                    "public_ready": sum(1 for p in mine if p["public_ready"] and p["shopify_status"] != "ACTIVE"),
                    "live": sum(1 for p in mine if p["shopify_status"] == "ACTIVE"),
                    "products": [p["pd_no"] for p in mine],
                    "quota": ((score.get("category_desks") or {}).get(d) or {}).get("s_quota")}

    analysis = ((runtime.get("brain_flow") or {}).get("executions") or {}).get("runtime") or {}
    analysis_at = analysis.get("completed_at") if analysis.get("input_read_from_vault") and analysis.get("output_stored") else None
    teams = []
    sec = runtime.get("secretary") or {}
    if sec:
        teams.append({"id": "secretary", "name": "비서실장", "status": sec.get("status") or "ok",
                      "source_reported_at": sec.get("when"), "summary": sec.get("summary"), "next_action": sec.get("action")})
    for t in runtime.get("teams") or []:
        if isinstance(t, dict):
            teams.append({"id": t.get("id"), "name": t.get("name"), "status": t.get("status"),
                          "source_reported_at": t.get("when"), "summary": t.get("summary"),
                          "next_action": t.get("action") or t.get("waiting")})
    for team in teams:
        team["analysis_completed_at"] = analysis_at
        team["external_team_execution_verified"] = False
        team["video_learning"] = team_video_reviews(learning, team.get("id"))
    store = [dict(pd_no=pd, **{k: r.get(k) for k in ("title", "category", "date", "status", "single_usd", "single_margin_pct")})
             for pd, r in reg.items()]
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "dashboard_runtime + shopify_demand_score + shopify_s_recommendations + listing_gate + shopify_daily_registry + team_learning",
            "desks": desks, "products": products, "teams": teams, "shopify_store": store}


def write_vault(doc: dict) -> int:
    changed = 0
    prod_stem = {p["pd_no"]: safe(f"{p['pd_no']} {p['name']}") for p in doc["products"]}
    for p in doc["products"]:
        links = [f"- 담당: [[{p['desk_name']}]]"]
        if p["shopify_status"]:
            links.append("- 등록: [[Shopify Store]]")
        body = (f"다음 작업: **{p['next_action']}**\n\n" + "\n".join(links) +
                (f"\n\n원문: [다이소몰]({p['daiso_url']})" if p.get("daiso_url") else ""))
        props = {k: p[k] for k in ("pd_no", "desk", "grade", "score", "s_rule", "public_ready", "blocked_by",
                                   "shopify_status", "registered_at", "price_usd", "margin_pct")}
        changed += write(BRAIN / "Products" / f"{prod_stem[p['pd_no']]}.md", prod_stem[p["pd_no"]], "product", props, body)
    for d, info in doc["desks"].items():
        rows = [p for p in doc["products"] if p["desk"] == d]
        table = ["| 상품 | 점수 | 공개 가능 | Shopify | 다음 작업 |", "|---|---|---|---|---|"]
        table += [f"| [[{prod_stem[p['pd_no']]}]] | {p['score']} | {'예' if p['public_ready'] else '아니오'} | "
                  f"{p['shopify_status'] or '-'} | {p['next_action']} |" for p in rows]
        if not rows:
            table.append("| (S 후보 없음) | | | | |")
        body = (f"S 후보 **{info['s_count']}개** · 공개 대기 {info['public_ready']}개 · Shopify 공개 {info['live']}개\n\n"
                "상위 팀: [[상품 소싱팀]]\n\n" + "\n".join(table))
        changed += write(BRAIN / "Desks" / f"{info['name']}.md", info["name"], "category-desk",
                         {"desk": d, "s_count": info["s_count"], "public_ready": info["public_ready"],
                          "live": info["live"], "quota": info["quota"]}, body)
    for t in doc["teams"]:
        hub = None  # Title/name matches are not evidence relations.
        extra = ""
        if t["id"] == "sourcing":
            extra = "\n\n카테고리 전담팀: " + " · ".join(f"[[{n}]]" for n in DESK_NAME.values())
        body = (f"상태 **{t['status']}** · 원본 보고 시각/표시 {t['source_reported_at'] or 'UNKNOWN'}\n\n로컬 분석 완료: {t.get('analysis_completed_at') or 'UNKNOWN'} (외부 팀 실행 증명 아님)\n\n"
                f"{t.get('summary') or ''}\n\n다음 작업: {t.get('next_action') or '-'}"
                + (f"\n\n지식 허브: {hub}" if hub else "") + extra
                + video_review_body(t.get("video_learning") or []))
        changed += write(BRAIN / "Teams" / f"{safe(t['name'])}.md", safe(t["name"]), "team-status",
                         {"team_id": t["id"], "team_status": t["status"], "source_reported_at": t["source_reported_at"], "analysis_completed_at": t.get("analysis_completed_at"), "external_team_execution_verified": False}, body)
    store_rows = ["| 상품 | 카테고리 | 등록일 | 상태 | 가격 | 마진 |", "|---|---|---|---|---|---|"]
    for s in doc["shopify_store"]:
        stem = prod_stem.get(s["pd_no"])
        label = f"[[{stem}]]" if stem else (s.get("title") or s["pd_no"])
        store_rows.append(f"| {label} | {s.get('category')} | {s.get('date')} | {s.get('status')} | "
                          f"{s.get('single_usd') or '-'} | {s.get('single_margin_pct') or '-'} |")
    changed += write(BRAIN / "Shopify Store.md", "Shopify Store", "store",
                     {"live": sum(1 for s in doc["shopify_store"] if s.get("status") == "ACTIVE"),
                      "registered_total": len(doc["shopify_store"])},
                     "등록 이력 원장의 기록입니다. 현재 Shopify 상태나 매출을 검증한 자료가 아닙니다.\n\n" + "\n".join(store_rows))
    hub = ["## 카테고리 전담팀", ""] + [f"- [[{i['name']}]] · S {i['s_count']} · 공개 {i['live']}" for i in doc["desks"].values()]
    hub += ["", "## 팀", ""] + [f"- [[{safe(t['name'])}]] · {t['status']} · {t['source_reported_at'] or '-'}" for t in doc["teams"]]
    hub += ["", "## 등록 이력", "", "- [[Shopify Store]]"]
    changed += write(BRAIN / "JARVIS Brain.md", "JARVIS Brain", "brain-hub",
                     {"desks": len(doc["desks"]), "teams": len(doc["teams"]), "s_products": len(doc["products"])},
                     "공개 운영 상태의 요약 뷰입니다. 실행 증빙과 실제 입출력은 로컬 BrainRuntime에 별도로 저장합니다. 수집 시각과 분석 시각은 다릅니다.\n\n" + "\n".join(hub))
    return changed


def main() -> int:
    doc = build()
    changed = write_vault(doc)
    body = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    strip = lambda s: re.sub(r'"generated_at": "[^"]*"', "", s)
    if strip(old) != strip(body):
        OUT.write_text(body, encoding="utf-8")
    print(f"JARVIS_BRAIN_OK notes_changed={changed} desks={ {k: v['s_count'] for k, v in doc['desks'].items()} } "
          f"products={len(doc['products'])} teams={len(doc['teams'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
