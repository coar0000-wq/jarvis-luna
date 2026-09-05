#!/usr/bin/env python3
"""Generate a truthful, static-site-friendly runtime snapshot from real artifacts."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 기준 경로 설정
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "dashboard_runtime.json"
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
KNOWLEDGE = ROOT / "data" / "knowledge"
HISTORY = KNOWLEDGE / "cumulative_history.json"

# 한국 시간(KST)
KST = timezone(timedelta(hours=9))


def load_json(path: Path, default: any) -> any:
    """안전하게 JSON 파일을 로드합니다."""
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def iso_mtime(path: Path) -> str | None:
    """파일의 수정 시간을 KST ISO 8601 포맷으로 반환합니다."""
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, KST).isoformat()
    except OSError:
        pass
    return None


def get_md_count(base: Path, *subdirs: str) -> int:
    """특정 하위 디렉토리 내부의 마크다운 파일 개수를 효율적으로 계산합니다."""
    target_dir = base.joinpath(*subdirs)
    if target_dir.exists() and target_dir.is_dir():
        return sum(1 for _ in target_dir.glob("*.md"))
    return 0


def graph_metrics() -> dict:
    """Obsidian Vault 내의 마크다운 노트 및 링크 연결 상태를 분석합니다."""
    notes = list(VAULT.rglob("*.md")) if VAULT.exists() else []
    links = 0
    targets: set[str] = set()

    link_pattern = re.compile(r"\[\[([^\]|#]+)")

    # 링크 대상을 폴더별로 나눠 담는다. 파이프라인이 만든 노트(Knowledge/)와
    # 사용자가 직접 넣은 노트(Personal/)는 성격이 달라 같은 기준으로 볼 수 없다.
    generated: set[str] = set()
    personal: set[str] = set()

    for note in notes:
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
            found = link_pattern.findall(text)
            links += len(found)
        except OSError:
            continue

        try:
            top = note.relative_to(VAULT).parts[0]
        except ValueError:
            top = ""
        bucket = personal if top == "Personal" else generated

        for target in found:
            normalized = target.strip().replace("\\", "/")
            normalized = normalized.rsplit("/", 1)[-1]
            if normalized.endswith(".md"):
                normalized = normalized[:-3]
            if normalized:
                # Obsidian 은 파일명을 대소문자 구분 없이 찾는다. 여기서 구분하면
                # Windows 가 기존 파일명 대소문자를 유지하는 탓에 멀쩡한 링크가
                # 끊어진 것으로 잡힌다. (ASML-reports... vs Asml-Reports...)
                targets.add(normalized)
                bucket.add(normalized.lower())

    stems = {p.stem.lower() for p in notes}
    dangling_generated = sorted(x for x in generated if x not in stems)
    dangling_personal = sorted(x for x in personal if x not in stems)
    valid_mtimes = [iso_mtime(p) for p in notes if iso_mtime(p) is not None]

    return {
        "notes": len(notes),
        "links": links,
        # 파이프라인 품질 지표는 생성분만 센다.
        "dangling_links": len(dangling_generated),
        "dangling_personal": len(dangling_personal),
        "dangling_personal_note": (
            "사용자가 직접 넣은 Personal 노트의 내부 링크. 원본 볼트에서 일부만"
            " 가져와 대상 노트가 없는 것으로, 파이프라인 오류가 아니다."
        ),
        "records": get_md_count(VAULT, "Knowledge", "Records"),
        "sources": get_md_count(VAULT, "Knowledge", "Sources"),
        "topics": get_md_count(VAULT, "Knowledge", "Topics"),
        "orgs": get_md_count(VAULT, "Knowledge", "Orgs"),
        "audit": "failed" if dangling_generated else "passed",
        "last_generated": max(valid_mtimes, default=None),
    }


def source_metrics() -> dict:
    """수집된 코퍼스 및 데이터 소스 메트릭을 로드합니다."""
    data = load_json(KNOWLEDGE / "real_sources.json", {})
    record_count = 0
    corpus_path = KNOWLEDGE / "training_corpus.jsonl"

    if corpus_path.exists():
        try:
            with corpus_path.open("r", encoding="utf-8", errors="ignore") as f:
                record_count = sum(1 for line in f if line.strip())
        except OSError:
            record_count = 0

    labels = {}
    if isinstance(data, dict):
        labels = data.get("source_counts") or data.get("counts") or {}

    return {
        "status": "completed" if corpus_path.exists() and record_count > 0 else "waiting",
        "record_count": record_count,
        "source_counts": labels,
        "updated_at": iso_mtime(KNOWLEDGE / "real_sources.json"),
    }


def training_metrics() -> dict:
    """MoE 모델의 최신 학습 상태 및 메트릭을 로드합니다."""
    status = load_json(KNOWLEDGE / "training_status.json", {})
    trained = bool(status.get("training_performed") and status.get("weights_updated"))

    return {
        "status": "completed" if trained else "not_verified",
        "training_performed": bool(status.get("training_performed")),
        "weights_updated": bool(status.get("weights_updated")),
        "records": status.get("real_records", 0),
        "model_type": status.get("model_type", "확인 필요"),
        "experts": status.get("experts", 0),
        "accuracy": status.get("training_accuracy_on_corpus"),
        "validation_accuracy": status.get("tuning_validation_accuracy"),
        "final_loss": status.get("tuning_final_loss"),
        "gate_load_std": status.get("tuning_gate_load_std"),
        "tuning_promoted": bool(status.get("tuning_promoted")),
        "tuning_steps": status.get("tuning_steps"),
        "updated_at": status.get("updated_at") or iso_mtime(KNOWLEDGE / "training_status.json"),
    }


FIELDS = ("records", "notes", "links")


def cumulative_metrics(graph: dict, sources: dict) -> dict:
    """과거 실행 내역과 비교하여 누적 메트릭을 계산하고 저장합니다."""
    now = datetime.now(KST).isoformat()

    current = {
        "records": int(sources.get("record_count") or 0),
        "notes": int(graph.get("notes") or 0),
        "links": int(graph.get("links") or 0),
    }

    hist = load_json(HISTORY, None)

    if not isinstance(hist, dict) or "totals" not in hist:
        hist = {
            "schema_version": 1,
            "note": (
                "누적 집계는 이 파일이 처음 생성된 시점부터 시작합니다. "
                "그 이전 실행 기록이 없으므로 과거 수치는 추정하지 않습니다."
            ),
            "baseline": {**current, "recorded_at": now},
            "totals": dict(current),
            "last_snapshot": {**current, "recorded_at": now},
            "runs": [],
        }
        added = {k: 0 for k in FIELDS}
    else:
        prev = hist.get("last_snapshot") or {}
        added = {}

        for k in FIELDS:
            before = prev.get(k)
            before = current[k] if before is None else int(before)
            added[k] = max(0, current[k] - before)
            hist["totals"][k] = int(hist["totals"].get(k, 0)) + added[k]

        hist["last_snapshot"] = {**current, "recorded_at": now}

    hist["runs"] = (hist.get("runs", []) + [{"at": now, **current, "added": added}])[-90:]
    hist["updated_at"] = now

    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"Warning: 누적 히스토리 저장 실패 - {e}")

    return {
        "totals": {k: int(hist["totals"].get(k, 0)) for k in FIELDS},
        "prior_totals": {k: int(hist["totals"].get(k, 0)) - added[k] for k in FIELDS},
        "added_this_run": added,
        "current_snapshot": current,
        "since": hist["baseline"].get("recorded_at"),
        "runs_recorded": len(hist["runs"]),
    }


# ---------------------------------------------------------------------------
# 팀 카드
# ---------------------------------------------------------------------------
# 각 팀의 숫자는 전부 실제 산출 파일에서 읽는다. 파일이 없으면 그 팀은
# status "missing" 으로 두고 값을 지어내지 않는다.
TEAM_ICONS = {
    "institutions": {"color": "#2f7d6b", "glyph": "bank"},
    "market": {"color": "#c2410c", "glyph": "chart"},
    "pricing": {"color": "#7c3aed", "glyph": "tag"},
    "legal": {"color": "#b91c1c", "glyph": "scale"},
    "robotics": {"color": "#1d4ed8", "glyph": "robot"},
    "sourcing": {"color": "#15803d", "glyph": "box"},
    "listing": {"color": "#be185d", "glyph": "doc"},
    "channels": {"color": "#0369a1", "glyph": "antenna"},
    "knowledge": {"color": "#a16207", "glyph": "book"},
    "design": {"color": "#0ea5e9", "glyph": "design"},
    "graph": {"color": "#0f766e", "glyph": "graph"},
}


def _team(tid: str, name: str, when: str | None, summary: str,
          action: str | None = None, status: str = "ok") -> dict:
    icon = TEAM_ICONS.get(tid, {"color": "#555", "glyph": "dot"})
    return {"id": tid, "name": name, "when": when, "summary": summary,
            "action": action, "status": status,
            "color": icon["color"], "glyph": icon["glyph"]}


def team_cards(graph: dict) -> list[dict]:
    """팀별 한 줄 현황. 숫자는 산출 파일 실측값만 쓴다."""
    cards: list[dict] = []
    D = ROOT / "data"

    # 팀마다 최근에 들어온 자료 건수. 요약 뒤에 덧붙인다.
    feeds = (load_json(D / "team_feeds.json", None) or {}).get("summary") or {}

    def feed_tail(team_id: str) -> str:
        s = feeds.get(team_id) or {}
        n = s.get("recent") or 0
        return f" · 새 자료 {n}건" if n else ""

    # 상품 소싱팀 --------------------------------------------------------
    # 사업의 출발점이라 맨 앞에 둔다. 수집이 멈추면 여기서 먼저 드러나야 한다.
    prod = load_json(D / "daiso_real" / "products.json", None)
    score = load_json(D / "daiso_real" / "shopify_demand_score.json", None)
    stat = load_json(D / "daiso_real" / "collection_status.json", None)
    if prod or score:
        n = (prod or {}).get("count") or len((prod or {}).get("products") or [])
        gs = (score or {}).get("grade_summary") or {}
        grade = " / ".join(f"{g} {gs[g]}" for g in ("S", "A", "B", "C") if g in gs)
        run = (stat or {}).get("last_run") or {}
        fail = (run.get("parse_failed") or 0) + (run.get("http_error") or 0)
        ok = run.get("ok") or 0
        # skipped_not_beauty 는 뷰티관이 아니라 일부러 건너뛴 것이다.
        # 이걸 분모에 넣으면 실패율이 실제보다 크게 보인다.
        tried = ok + fail
        cards.append(_team(
            "sourcing", "상품 소싱팀",
            (score or {}).get("generated_at") or (prod or {}).get("updated_at"),
            (f'{n}개 상품 · 등급 {grade}' if grade else f'{n}개 상품') + feed_tail("sourcing"),
            f'직전 실행에서 {tried}건 시도 중 {fail}건 파싱 실패 (성공 {ok}건)'
            if fail else None,
            "ok" if n else "failed"))
    else:
        cards.append(_team("sourcing", "상품 소싱팀", None,
                           "data/daiso_real/products.json 없음", None, "missing"))

    # 기관 수집팀 --------------------------------------------------------
    inst = load_json(D / "institution_sources.json", None)
    if inst:
        cards.append(_team(
            "institutions", "기관 수집팀", inst.get("collected_at"),
            f'{inst.get("organizations", 0)}곳 {inst.get("total", 0):,}건 · '
            f'미수집 {len(inst.get("not_collected") or {})}건 사유 기록' + feed_tail("institutions")))
    else:
        cards.append(_team("institutions", "기관 수집팀", None,
                           "institution_sources.json 없음", None, "missing"))

    # 마케팅 조사팀 ------------------------------------------------------
    mt = load_json(D / "market_team.json", None)
    if mt:
        s_grade = mt.get("s_grade_priority") or []
        # 수동 입력 폴더에 pd_no 가 등장하는 상품만 고시표가 들어온 것으로 본다
        # 고시는 gosi.json 이 정본이다. data/manual 을 뒤지던 옛 방식은
        # 고시 수집기가 생긴 뒤로 실제 상태와 맞지 않는다.
        gosi = (load_json(D / "gosi.json", None) or {}).get("items") or {}
        REQ = ("ingredients", "volume", "maker", "origin")
        entered = {k for k, v in gosi.items()
                   if all(str(v.get(f) or "").strip() for f in REQ)}
        pending = [p for p in s_grade if str(p.get("pd_no")) not in entered]
        cards.append(_team(
            "market", "마케팅 조사팀", iso_mtime(D / "market_team.json"),
            f'S등급 {len(s_grade)}개 · 고시표 입력 대기 {len(pending)}건' + feed_tail("market"),
            f'다이소 상세페이지 고시 표 {len(pending)}건 캡처 필요' if pending else None))
    else:
        cards.append(_team("market", "마케팅 조사팀", None,
                           "market_team.json 없음", None, "missing"))

    # 리스팅 제작팀 ------------------------------------------------------
    copy = load_json(D / "shopify_listing_copy.json", None)
    rep = load_json(D / "shopify_import_report.json", None)
    if copy:
        made = copy.get("ok") or len(copy.get("items") or [])
        bad = copy.get("failed") or 0
        rows = (rep or {}).get("rows") or 0
        # 개수만 빼면 안 된다. S등급 목록이 바뀌면 이미 만든 카피가
        # 지금 S등급이 아닐 수 있어 미생성 건수가 실제보다 적게 나온다.
        # 상품번호를 직접 대조한다.
        s_rows = [p for p in ((score or {}).get("all_scored") or [])
                  if p.get("grade") == "S"]
        have = {str(i.get("pd_no")) for i in (copy.get("items") or [])}
        miss = [p for p in s_rows if str(p.get("pd_no")) not in have]
        s_total = len(s_rows) or (((score or {}).get("grade_summary") or {}).get("S") or 0)
        # 등록 가능 여부는 게이트가 한 곳에서 계산한다.
        gate = load_json(D / "listing_gate.json", None)
        if gate:
            c = gate.get("counts") or {}
            blk = gate.get("blockers") or {}
            LABEL = {"copy": "카피", "gosi": "고시", "price": "실측", "legal": "법률"}
            detail = " · ".join(f'{LABEL.get(k, k)} {c.get(k, 0)}'
                                for k in ("copy", "gosi", "price", "legal"))
            top = ", ".join(f'{LABEL.get(k, k)} {v}건' for k, v in list(blk.items())[:3])
            cards.append(_team(
                "listing", "리스팅 제작팀", gate.get("generated_at"),
                f'등록 가능 {gate.get("ready", 0)}/{gate.get("total", 0)} · {detail}',
                f'{top} 이 막고 있음' if top else None,
                "ok" if gate.get("total") else "failed"))
        else:
            cards.append(_team(
                "listing", "리스팅 제작팀", copy.get("generated_at"),
                f'영문 카피 {made}건 · 임포트 CSV {rows}행'
                + (f' · 실패 {bad}건' if bad else ''),
                f'S등급 {s_total}개 중 {len(miss)}건 카피 미생성' if miss else None,
                "ok" if made else "failed"))
    else:
        cards.append(_team("listing", "리스팅 제작팀", None,
                           "data/shopify_listing_copy.json 없음", None, "missing"))

    # 가격 정책팀 --------------------------------------------------------
    pm = load_json(D / "pricing_model.json", None)
    if pm:
        duty = pm.get("duty_scenarios") or {}
        rows = (pm.get("scenarios") or {}).get("1개_묶음배송") or []
        src = {}
        for r in rows:
            k = r.get("weight_source") or "estimated"
            src[k] = src.get(k, 0) + 1
        # 100g 경계에 걸린 것만 저울이 필요하다. 전부 재라고 하지 않는다.
        need = [r for r in rows if r.get("weigh_needed")]
        LAB = {"measured": "실측", "gosi_volume": "고시용량", "estimated": "이름추정"}
        detail = " / ".join(f"{LAB.get(k, k)} {v}" for k, v in sorted(src.items()))
        cards.append(_team(
            "pricing", "가격 정책팀", pm.get("generated_at"),
            f'DDU/DDP {len(duty)}개 시나리오 · 무게 {detail}' + feed_tail("pricing"),
            f'{len(need)}건만 저울 필요 (100g 경계 ±15g)' if need else None))
    else:
        cards.append(_team("pricing", "가격 정책팀", None,
                           "pricing_model.json 없음", None, "missing"))

    # 상품별 자동 점검이 정본이다. 옛 legal_team.json 은 사람에게 상품 정보를
    # 내놓으라고 요구하던 구조라 현황을 반영하지 못한다.
    lp = load_json(D / "legal_products.json", None)
    if lp and (lp.get("auto_summary") or lp.get("items")):
        a = lp.get("auto_summary") or {}
        n_chk = a.get("checked") or len(lp.get("items") or {})
        att = a.get("needs_attention") or 0
        cards.append(_team(
            "legal", "법률·규제팀", lp.get("auto_checked_at"),
            f'자동 점검 {n_chk}건 · 통과 {a.get("clean", 0)} · 주의 {att} · '
            f'사람 PASS {a.get("pass", 0)}' + feed_tail("legal"),
            f'주의 {att}건 확인 후 PASS 판정 필요' if att
            else (f'{n_chk}건 PASS 판정 필요' if not a.get("pass") else None)))
    else:
        cards.append(_team("legal", "법률·규제팀", None,
                           "legal_products.json 없음", None, "missing"))
    # 로보틱스 수집 ------------------------------------------------------
    rb = load_json(D / "robotics_sources.json", None)
    if rb:
        src = rb.get("sources") or {}
        parts = " / ".join(f'{k} {len((v or {}).get("items") or [])}' for k, v in src.items())
        cards.append(_team(
            "robotics", "로보틱스 수집", rb.get("generated_at"),
            f'{rb.get("total", 0)}건 · {parts}' + feed_tail("robotics")))
    else:
        cards.append(_team("robotics", "로보틱스 수집", None,
                           "robotics_sources.json 없음", None, "missing"))

    # 디자인팀 ------------------------------------------------------------
    dt = load_json(D / "design_team.json", None)
    if dt:
        c = dt.get("checklist") or {}
        refs = (dt.get("references") or {}).get("count", 0)
        waiting = c.get("waiting", 0)
        first = next((s.get("label") for s in (c.get("steps") or [])
                      if s.get("status") != "완료"), "")
        cards.append(_team(
            "design", "디자인팀", dt.get("generated_at"),
            f'스토어 {c.get("done", 0)}/{c.get("total", 0)}단계 · 레퍼런스 {refs}건' + feed_tail("design"),
            f'다음 단계: {first}' if waiting and first else None))
    else:
        cards.append(_team("design", "디자인팀", None,
                           "design_team.json 없음", None, "missing"))

    # 채널 운영팀 --------------------------------------------------------
    # 채널 가동 상태와 사람 승인 대기 건을 한 줄로 본다.
    prev = load_json(OUT, None) or {}
    gcs = prev.get("global_channels_status") or {}
    live = sum(1 for v in gcs.values() if (v or {}).get("status") == "ok")
    cand = load_json(D / "channel_candidates.json", None)
    man = load_json(D / "manual_channels.json", None)
    if gcs or cand:
        tested = (cand or {}).get("tested") or 0
        manual_n = (man or {}).get("total") or 0

        # discover_channels 는 이미 붙인 소스도 계속 후보로 다시 올린다.
        # 키 이름이 서로 달라(wikipedia_pageviews vs wikipedia_interest)
        # 단순 비교로는 안 걸러지므로 의미 있는 낱말이 겹치는지로 판정한다.
        STOP = {"new", "daily", "rss", "us", "beauty", "drug", "otc", "api"}
        def words(key):
            return {w for w in str(key).lower().split("_") if w and w not in STOP}
        livewords = [words(k) for k, v in gcs.items() if (v or {}).get("status") == "ok"]
        pending = []
        for c in (cand or {}).get("candidates") or []:
            if c.get("verdict") != "가능":
                continue
            if any(words(c.get("key")) & lw for lw in livewords):
                continue          # 이미 붙어 있는 소스
            pending.append(c)

        cards.append(_team(
            "channels", "채널 운영팀",
            (cand or {}).get("generated_at") or prev.get("generated_at"),
            f'가동 {live}/{len(gcs)}채널 · 수동 입력 {manual_n}건 · '
            f'후보 {tested}건 검사, 미연동 {len(pending)}건',
            f'후보 {len(pending)}건 승인 대기 (연동은 사람이 승인한 뒤에 한다)'
            if pending else None,
            "ok" if live else "failed"))
    else:
        cards.append(_team("channels", "채널 운영팀", None,
                           "채널 상태 파일 없음", None, "missing"))

    # 지식 수집팀 --------------------------------------------------------
    # 기관·로보틱스는 각자 카드가 있으므로 여기서는 담당 카드가 없던 소스만 센다.
    rs = load_json(KNOWLEDGE / "real_sources.json", None)
    if rs:
        LABEL = {"arxiv": "arXiv", "youtube": "YouTube",
                 "google": "Google", "us_beauty": "US뷰티"}
        parts, total, bad = [], 0, []
        for key, label in LABEL.items():
            blk = (rs.get("sources") or {}).get(key) or {}
            n = len(blk.get("items") or [])
            total += n
            parts.append(f"{label} {n}")
            if blk.get("status") != "ok" or n == 0:
                bad.append(f'{label}({blk.get("reason") or blk.get("status") or "0건"})')
        cards.append(_team(
            "knowledge", "지식 수집팀", rs.get("updated"),
            f'{total}건 · ' + " / ".join(parts),
            f'수집 실패: {", ".join(bad)}' if bad else None,
            "ok" if total else "failed"))
    else:
        cards.append(_team("knowledge", "지식 수집팀", None,
                           "data/knowledge/real_sources.json 없음", None, "missing"))

    # 옵시디언 그래프 ----------------------------------------------------
    personal = graph.get("dangling_personal") or 0
    cards.append(_team(
        "graph", "옵시디언 그래프", graph.get("last_generated"),
        f'{graph.get("notes", 0):,}노트 · {graph.get("links", 0):,}링크 · '
        f'끊어진 링크 {graph.get("dangling_links", 0)}건'
        + (f' · 개인 노트 {personal:,}건 별도' if personal else ''),
        None, "ok" if graph.get("audit") == "passed" else "failed"))

    return cards


def main() -> None:
    graph = graph_metrics()
    sources = source_metrics()
    training = training_metrics()
    cumulative = cumulative_metrics(graph, sources)
    teams = team_cards(graph)

    now = datetime.now(KST).isoformat()

    accuracy_display = (
        f'{training["accuracy"]:.2%}'
        if isinstance(training["accuracy"], (int, float))
        else str(training["accuracy"] or "N/A")
    )

    # 기존 dashboard_runtime.json에 있던 global_channels / exchange_rate 보존
    # (sync_channels.py가 나중에 덮어쓰지만, 중간 실패 시 데이터 소실 방지)
    prev = load_json(OUT, {})
    prev_global = prev.get("global_channels") if isinstance(prev, dict) else None
    prev_fx = prev.get("exchange_rate") if isinstance(prev, dict) else None
    prev_synced = prev.get("last_synced") if isinstance(prev, dict) else None

    payload = {
        "schema_version": 1,
        "generated_at": now,
        "truth_note": (
            "상태는 저장소에 존재하는 실제 산출물 기준이며, "
            "실행 기록이 없는 작업은 진행중으로 표시하지 않음."
        ),
        "teams": teams,
        # 특정 팀에 속하지 않는 전체 값. 팀 섹션 머리말에 쓴다.
        "team_summary": {
            "corpus_records": ((cumulative.get("totals") or {}).get("records")
                               or sources.get("record_count") or 0),
            "pipeline_done": 0,
            "pipeline_total": 0,
        },
        "pipeline": [
            {
                "id": "collect",
                "title": "실제 데이터 수집",
                "status": sources["status"],
                "detail": f'{sources["record_count"]}개 코퍼스 레코드',
            },
            {
                "id": "graph",
                "title": "Obsidian 그래프 반영·검증",
                "status": "completed" if graph["audit"] == "passed" else "failed",
                "detail": (
                    f'{graph["notes"]}개 노트 · '
                    f'{graph["links"]}개 링크 · '
                    f'끊어진 링크 {graph["dangling_links"]}개'
                    + (f' · 개인 노트 {graph["dangling_personal"]}개 별도'
                       if graph.get("dangling_personal") else '')
                ),
            },
            {
                "id": "dashboard",
                "title": "GitHub Pages 대시보드 데이터",
                "status": "generated",
                "detail": "dashboard_runtime.json 생성 완료",
            },
            {
                "id": "train",
                "title": "실제 데이터 MoE 학습",
                "status": training["status"],
                "detail": (
                    f'{training["records"]}건 · '
                    f'{training["experts"]} experts · '
                    f'정확도 {accuracy_display}'
                ),
            },
            {
                "id": "publish",
                "title": "저장소·Pages 반영",
                "status": (
                    "pending_workflow"
                    if training["status"] != "completed"
                    else "ready_for_pages"
                ),
                "detail": "GitHub Actions Pages 배포 워크플로에서 반영",
            },
        ],
        "sources": sources,
        "graph": graph,
        "training": training,
        "cumulative": cumulative,
    }

    # 파이프라인 진행도는 payload 의 pipeline 을 세어 채운다
    DONE = ("completed", "generated", "ready_for_pages")
    _steps = payload.get("pipeline") or []
    payload["team_summary"]["pipeline_done"] = sum(1 for st in _steps if st.get("status") in DONE)
    payload["team_summary"]["pipeline_total"] = len(_steps)

    # 이전 global_channels / 환율 데이터가 있으면 유지
    if isinstance(prev_global, dict) and prev_global:
        payload["global_channels"] = prev_global
    if isinstance(prev_fx, dict) and prev_fx:
        payload["exchange_rate"] = prev_fx
    if prev_synced:
        payload["last_synced"] = pr
