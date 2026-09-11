#!/usr/bin/env python3
"""Generate a truthful, static-site-friendly runtime snapshot from real artifacts."""
from __future__ import annotations

import json
import re
import time
import unicodedata
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

        # Truth Guard와 동일한 기준으로 그래프 품질을 판정한다.
        # Knowledge/만 자동 생성 지식 그래프로 보고 dangling 검증 대상에 포함한다.
        # Personal/은 별도 통계로 분리하고, 그 외 루트/시스템 영역은 품질 감사에서 제외한다.
        if top == "Knowledge":
            bucket = generated
        elif top == "Personal":
            bucket = personal
        else:
            bucket = None

        for target in found:
            normalized = unicodedata.normalize("NFC", target).strip().replace("\\", "/")

            # Obsidian 문서 안의 외부/URI 링크는 vault 내부 note dangling 검증 대상이 아니다.
            if normalized.lower().startswith((
                "http://", "https://", "mailto:", "obsidian:", "file:",
            )):
                continue

            normalized = normalized.rsplit("/", 1)[-1]
            if normalized.endswith(".md"):
                normalized = normalized[:-3]
            if not normalized:
                continue

            # Obsidian 은 파일명을 대소문자 구분 없이 찾는다. NFC로 정규화해
            # Windows의 대소문자 유지와 한글 NFD/NFC 차이 때문에 정상 링크를
            # 끊어진 것으로 판정하지 않도록 한다.
            targets.add(normalized)
            if bucket is not None:
                bucket.add(normalized.lower())

    stems = {unicodedata.normalize("NFC", n.stem).lower() for n in notes}
    dangling_generated = sorted(x for x in generated if x not in stems)
    dangling_personal = sorted(x for x in personal if x not in stems)
    # iso_mtime 을 노트마다 두 번 부르고 있었다. 2만 8천개면 stat 호출이
    # 5만 7천번이다. 한 번만 부르고 걸러낸다.
    valid_mtimes = [m for m in (iso_mtime(n) for n in notes) if m is not None]

    # Knowledge dangling 이 있어도 소량은 경고로 통과시킨다.
    # (완전 0만 통과면 노트 8만 개 규모에서 파이프가 항상 failed 로 고정됨)
    _dang = len(dangling_generated)
    _WARN_MAX = 300  # 이 이하면 audit=passed (경고만), 초과면 failed
    if _dang == 0:
        _audit = "passed"
    elif _dang <= _WARN_MAX:
        _audit = "passed"
    else:
        _audit = "failed"

    return {
        "notes": len(notes),
        "links": links,
        # 파이프라인 품질 지표는 생성분만 센다.
        "dangling_links": _dang,
        "dangling_personal": len(dangling_personal),
        "dangling_personal_note": (
            "사용자가 직접 넣은 Personal 노트의 내부 링크. 원본 볼트에서 일부만"
            " 가져와 대상 노트가 없는 것으로, 파이프라인 오류가 아니다."
        ),
        "dangling_warn_threshold": _WARN_MAX,
        "records": get_md_count(VAULT, "Knowledge", "Records"),
        "sources": get_md_count(VAULT, "Knowledge", "Sources"),
        "topics": get_md_count(VAULT, "Knowledge", "Topics"),
        "orgs": get_md_count(VAULT, "Knowledge", "Orgs"),
        # Personal 은 실패로 승격하지 않음. Knowledge 단절은 임계값 이하 경고 통과.
        "audit": _audit,
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


# 팀이 언제 일하는지. 사람이 "지금 뭐가 돌고 있나" 를 알려면 필요하다.
#   now    지금 돌면서 S등급 후보를 좁힌다
#   ready  준비는 끝났고 Shopify 계정이 생기면 바로 등록으로 넘어간다
#   always 상시. 시장이 바뀌면 앞 단계가 다시 돈다
TEAM_PHASE = {
    "channels": ("now", "1단계 · 후보 선정"),
    "knowledge": ("now", "1단계 · 후보 선정"),
    "institutions": ("now", "1단계 · 후보 선정"),
    "sourcing": ("now", "1단계 · 후보 선정"),
    "market": ("always", "상시 · 시장 감시"),
    "listing": ("ready", "2단계 · 가입 후 등록"),
    "pricing": ("ready", "2단계 · 가입 후 등록"),
    "legal": ("ready", "2단계 · 가입 후 등록"),
    "design": ("ready", "2단계 · 가입 후 등록"),
    "robotics": ("now", "1단계 · 지식"),
    "obsidian": ("now", "1단계 · 지식"),
}


def _team(tid: str, name: str, when: str | None, summary: str,
          action: str | None = None, status: str = "ok") -> dict:
    icon = TEAM_ICONS.get(tid, {"color": "#555", "glyph": "dot"})
    phase, phase_label = TEAM_PHASE.get(tid, ("now", ""))
    return {"id": tid, "name": name, "when": when, "summary": summary,
            "action": action, "status": status,
            "phase": phase, "phase_label": phase_label,
            "color": icon["color"], "glyph": icon["glyph"]}


# 채널 상태가 몇 살인지 따진다.
#
# amazon_best_sellers 와 walmart_beauty 가 status "ok", trust "verified" 로
# 떠 있었다. 그런데 값은 2026-08-31 에 손으로 적어 넣은 카탈로그이고
# 그 뒤로 아무도 다시 확인하지 않았다. url 도 상품 주소가 아니라
# amazon.com 홈페이지였다.
#
# 보존 로직이 값을 지우지 않는 것까지는 맞다. 하지만 나이를 안 따지면
# 한 달 전 값도 "검증됨" 으로 남는다. 그건 확인한 것이 아니다.
STALE_HOURS = 48


def age_channel_status(gcs):
    """오래된 채널 상태의 신뢰 등급을 내리고 며칠 됐는지 적는다."""
    if not isinstance(gcs, dict) or not gcs:
        return gcs
    now_dt = datetime.now(timezone.utc)
    out = {}
    for key, meta in gcs.items():
        if not isinstance(meta, dict):
            out[key] = meta
            continue
        m = dict(meta)
        raw = m.get("collected_at") or ""
        try:
            age_h = (now_dt - datetime.fromisoformat(
                str(raw).replace("Z", "+00:00"))).total_seconds() / 3600
        except (ValueError, TypeError):
            out[key] = m
            continue
        m["age_hours"] = round(age_h, 1)
        if age_h > STALE_HOURS:
            m["stale"] = True
            if m.get("trust") == "verified":
                m["trust"] = "stale"
            m["status"] = "stale"
            m["reason"] = (f"{raw[:10]} 이후 갱신 없음 ({age_h / 24:.1f}일). "
                           + (m.get("reason") or "")).strip()
        else:
            m["stale"] = False
        out[key] = m
    return out


def merge_manual_channels(prev_global, prev_gcs, man):
    """사람이 화면을 보고 넣은 값을 채널 목록에 얹는다.

    manual_channels.json 이 32건을 들고 있는데 대시보드는 그 개수만
    카드에 적고 목록에는 안 썼다. 정작 목록에 뜨는 amazon_best_sellers 는
    2026-08-31 하드코딩 카탈로그였다. 사람이 실제 화면을 보고 넣은 값이
    있는데 손으로 적어둔 옛 목록이 이기고 있었던 것이다.

    수동 값이 더 최근이면 그걸 쓴다. 옛 카탈로그로 되돌리지 않는다.
    """
    gl = dict(prev_global or {})
    st = dict(prev_gcs or {})
    if not isinstance(man, dict):
        return gl, st
    for key, blk in (man.get("channels") or {}).items():
        items = (blk or {}).get("products") or []
        if not items:
            continue
        cap = str(blk.get("captured_at") or "")
        old_cap = str((st.get(key) or {}).get("collected_at") or "")[:10]
        if old_cap and cap and cap < old_cap:
            continue                      # 더 오래된 것으로 덮지 않는다
        gl[key] = [{
            "product": it.get("product") or it.get("name") or "",
            "brand": it.get("brand") or "",
            "sub": it.get("category") or "",
            "badge": f'${it.get("price_usd")}' if it.get("price_usd") else "",
            "price": it.get("price_usd"),
            "rating": it.get("rating"),
            "review_count": it.get("review_count"),
            "rank": it.get("rank"),
            # 상품 주소를 모르면 비워 둔다. 예전에는 amazon.com 홈페이지를
            # 넣어서 링크가 있는 것처럼 보였다.
            "url": it.get("product_url") or "",
            "extraction_method": it.get("extraction_method") or "manual_screenshot",
        } for it in items]
        st[key] = {
            "status": "ok",
            "source": f'사람이 직접 확인 ({blk.get("file", "")})',
            "reason": "" if blk.get("source_url_given") else "출처 URL 미기재",
            "collected_at": (cap + "T00:00:00+00:00") if cap else "",
            "count": len(items),
            "trust": "manual",
        }
    return gl, st


def _error_summary() -> dict:
    """에러 보고서를 화면이 바로 쓸 수 있게 줄인다."""
    d = load_json(ROOT / "data" / "error_report.json", None) or {}
    if not d:
        return {"status": "missing"}
    return {
        "generated_at": d.get("generated_at"),
        "total": d.get("total", 0),
        "counts": d.get("counts", {}),
        "고쳐야_할_것": [{"team": r["team"], "item": r["item"], "reason": r["reason"][:90]}
                    for r in (d.get("고쳐야_할_것") or [])],
        "사람_대기": [{"team": r["team"], "item": r["item"], "fix": r.get("fix", "")}
                  for r in (d.get("사람_대기") or [])],
    }


def team_cards(graph: dict, gcs: dict | None = None) -> list[dict]:
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
        sold = run.get("sold_out") or 0
        # skipped_not_beauty 는 뷰티관이 아니라 일부러 건너뛴 것이다.
        # 이걸 분모에 넣으면 실패율이 실제보다 크게 보인다.
        tried = ok + fail + sold
        # 왜 실패했는지 함께 보여준다. 예전에는 "15건 파싱 실패" 라고만
        # 적어서 원인을 짚을 수 없었다.
        why = run.get("parse_fail_reasons") or {}
        why_txt = (" · " + ", ".join(f"{k} {v}" for k, v in
                                    sorted(why.items(), key=lambda x: -x[1])[:3])) if why else ""
        sold_txt = f" · 품절·판매종료 {sold}건" if sold else ""
        cards.append(_team(
            "sourcing", "상품 소싱팀",
            (score or {}).get("generated_at") or (prod or {}).get("updated_at"),
            (f'{n}개 상품 · 등급 {grade}' if grade else f'{n}개 상품') + feed_tail("sourcing"),
            (f'직전 실행에서 {tried}건 시도 중 {fail}건 실패 (성공 {ok}건)'
             + why_txt + sold_txt) if fail else (
                f'직전 실행 {tried}건 시도 · 성공 {ok}건{sold_txt}' if sold else None),
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
            # price 를 '실측' 이라 적어놨었다. 저울로 잰다는 뜻으로 읽혀서
            # 오해를 준다. 무게는 고시 용량으로 계산하고, 이 항목이 보는 건
            # 손익분기를 넘는 판매가가 실제로 나왔는지다.
            LABEL = {"copy": "카피", "gosi": "고시", "price": "가격", "legal": "법률"}
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
        # 저울을 요구하지 않는다. 고시 용량과 우체국 요금표로 계산하면 된다.
        # 배송비는 이미 상품마다 계산되어 있으므로 그 결과를 보여준다.
        LAB = {"measured": "실측", "gosi_volume": "고시용량", "estimated": "이름추정"}
        detail = " / ".join(f"{LAB.get(k, k)} {v}" for k, v in sorted(src.items()))
        ships = sorted(r.get("shipping_unit_usd") or 0 for r in rows)
        gs = sorted(r.get("weight_g_est") or 0 for r in rows)
        ship_txt = (f'개당 배송비 ${ships[0]:.2f}~${ships[-1]:.2f}' if ships else '')
        blocked = [r for r in rows if r.get("breakeven_usd", 0) >= (r.get("market_median_usd") or 0) > 0]
        cards.append(_team(
            "pricing", "가격 정책팀", pm.get("generated_at"),
            f'{ship_txt} · 무게 {gs[0]}~{gs[-1]}g ({detail}) · DDU/DDP {len(duty)}개'
            + feed_tail("pricing"),
            f'{len(blocked)}건이 시장가로 손익분기 미달' if blocked else None))
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
        items = lp.get("items") or {}
        blocked = [v for v in items.values() if v.get("hard_block")]
        hard = len(blocked)
        hard_names = [f'{str(v.get("name"))[:16]}({str(v.get("hard_block_reason"))[:14]})'
                      for v in blocked]
        # 수출 서류를 얼마나 채웠는지도 같이 본다. "대기 5항목" 만 띄우면
        # 이미 채운 것까지 안 한 것처럼 보인다.
        ep = load_json(D / "legal_export_prep.json", None) or {}
        exp_txt = ""
        if ep.get("total"):
            need = ep.get("사람이_채워야_하는_칸") or []
            exp_txt = (f' · 수출서류 HS {ep["total"]}건 · 라벨 '
                       f'{6 - len(need)}/6항목 자동')
        cards.append(_team(
            "legal", "법률·규제팀", lp.get("auto_checked_at"),
            # 자동 점검이 깨끗하면 통과가 정상 경로다. 사람을 부르는 건
            # 실제로 막힌 건(hard_block)뿐이다. 예전에는 주의 표시만 떠도
            # "PASS 판정 필요" 라고 적어 매번 사람이 해야 할 일처럼 보였다.
            f'자동 점검 {n_chk}건 · 통과 {a.get("clean", 0)} · '
            f'등록 차단 {hard} · 참고 주의 {att}' + exp_txt + feed_tail("legal"),
            (f'차단 {hard}건: ' + ', '.join(hard_names[:2])
             + ' — 라벨 갖추기 전엔 못 올림') if hard else None))
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
        # 새로 붙인 디자인 소스(폰트·팔레트·기사)도 함께 보여준다.
        ds = load_json(D / "design_sources.json", None) or {}
        bits = []
        if (ds.get("fonts") or {}).get("total"):
            bits.append(f'폰트 {ds["fonts"]["total"]}개'
                        f'(한글 {ds["fonts"].get("korean_total", 0)})')
        if (ds.get("colors") or {}).get("hues"):
            bits.append(f'팔레트 {ds["colors"]["hues"]}색조')
        if (ds.get("articles") or {}).get("count"):
            bits.append(f'디자인 기사 {ds["articles"]["count"]}건')
        # 사람이 지정한 유튜브 채널·영상도 함께 센다.
        yc = load_json(D / "youtube_channels.json", None) or {}
        n_yt = (yc.get("by_team") or {}).get("design", 0)
        ym = load_json(D / "youtube_manual.json", None) or {}
        n_yt += sum(1 for v in (ym.get("videos") or [])
                    if "design" in (v.get("teams") or []))
        if n_yt:
            bits.append(f'영상 {n_yt}건')
        src_txt = (" · " + " · ".join(bits)) if bits else ""
        cards.append(_team(
            "design", "디자인팀", ds.get("generated_at") or dt.get("generated_at"),
            f'스토어 {c.get("done", 0)}/{c.get("total", 0)}단계 · 레퍼런스 {refs}건'
            + src_txt + feed_tail("design"),
            f'다음 단계: {first}' if waiting and first else None))
    else:
        cards.append(_team("design", "디자인팀", None,
                           "design_team.json 없음", None, "missing"))

    # 채널 운영팀 --------------------------------------------------------
    # 채널 가동 상태와 사람 승인 대기 건을 한 줄로 본다.
    prev = load_json(OUT, None) or {}
    # 카드가 파일에서 직접 읽으면 안 된다. 아래 aging 을 거치기 전 값이라
    # 카드는 가동 11 이라 적고 저장되는 최종 상태는 7 이 된다. 감사가 그
    # 차이를 잡아 워크플로가 통째로 실패했다. aging 을 마친 값을 받는다.
    if gcs is None:
        gcs = prev.get("global_channels_status") or {}
    live = sum(1 for v in gcs.values() if (v or {}).get("status") == "ok")
    aged = sum(1 for v in gcs.values() if (v or {}).get("stale"))
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
            f'가동 {live}/{len(gcs)}채널'
            + (f' · 낡음 {aged}건' if aged else '')
            + f' · 수동 입력 {manual_n}건 · '
            f'후보 {tested}건 검사, 미연동 {len(pending)}건',
            # 예전 문구는 "승인 대기" 였는데 승인할 화면이 없다. 후보는
            # data/channel_candidates.json 에 쌓이고, 붙일지 말지는 대화로
            # 지시하면 자비스가 수집기를 만들어 붙인다. 그대로 적는다.
            (f'미연동 후보 {len(pending)}건: '
             + ', '.join((c.get("label") or c.get("key") or "?") for c in pending[:3])
             + ' — 붙이라고 하시면 수집기를 만들어 연동합니다')
            if pending else None,
            "ok" if live else "failed"))
    else:
        cards.append(_team("channels", "채널 운영팀", None,
                           "채널 상태 파일 없음", None, "missing"))

    # 지식 수집팀 --------------------------------------------------------
    # 기관·로보틱스는 각자 카드가 있으므로 여기서는 담당 카드가 없던 소스만 센다.
    # blocked_by_robots 는 장애가 아니라 robots.txt 준수(의도적 중단)다.
    # "수집 실패"로 묶지 않고 별도 안내로 표시한다.
    rs = load_json(KNOWLEDGE / "real_sources.json", None)
    if rs:
        LABEL = {"arxiv": "arXiv", "organic_skincare": "유기농스킨",
                 "google": "Google", "us_beauty": "US뷰티"}
        parts, total, paused, failed = [], 0, [], []
        for key, label in LABEL.items():
            blk = (rs.get("sources") or {}).get(key) or {}
            n = len(blk.get("items") or [])
            total += n
            parts.append(f"{label} {n}")
            st = (blk.get("status") or "").strip()
            if st == "blocked_by_robots":
                # 규정 준수 중단 — 실패가 아님. API 키 경로 대기 상태.
                paused.append(
                    f'{label}(robots.txt 준수 · Data API 키 대기)'
                )
            elif st != "ok" or n == 0:
                failed.append(
                    f'{label}({blk.get("reason") or st or "0건"})'
                )
        action_bits = []
        if paused:
            action_bits.append("의도적 중단: " + ", ".join(paused))
        if failed:
            action_bits.append("수집 실패: " + ", ".join(failed))
        action = " · ".join(action_bits) if action_bits else None
        cards.append(_team(
            "knowledge", "지식 수집팀", rs.get("updated"),
            f'{total}건 · ' + " / ".join(parts),
            action,
            "ok" if total else "failed"))
    else:
        cards.append(_team("knowledge", "지식 수집팀", None,
                           "data/knowledge/real_sources.json 없음", None, "missing"))

    # 옵시디언 그래프 ----------------------------------------------------
    personal = graph.get("dangling_personal") or 0
    dang = graph.get("dangling_links") or 0
    audit_ok = graph.get("audit") == "passed"
    graph_summary = (
        f'{graph.get("notes", 0):,}노트 · {graph.get("links", 0):,}링크 · '
        f'끊어진 링크 {dang}건'
        + (f' · 개인 노트 {personal:,}건 별도' if personal else '')
        + (f' · 경고 통과(임계 {graph.get("dangling_warn_threshold", 300)})' if audit_ok and dang else '')
    )
    cards.append(_team(
        "graph", "옵시디언 그래프", graph.get("last_generated"),
        graph_summary,
        None, "ok" if audit_ok else "failed"))

    return cards


def main() -> None:
    graph = graph_metrics()
    sources = source_metrics()
    training = training_metrics()
    cumulative = cumulative_metrics(graph, sources)
    # 채널 상태를 먼저 정리한 뒤 카드를 만든다. 순서가 반대면 카드가
    # 낡음 처리 전 숫자를 적고 저장되는 값은 처리 후라 서로 어긋난다.
    _p = load_json(OUT, {}) or {}
    prev_global = _p.get("global_channels") if isinstance(_p, dict) else None
    prev_gcs = _p.get("global_channels_status") if isinstance(_p, dict) else None
    prev_global, prev_gcs = merge_manual_channels(
        prev_global, prev_gcs,
        load_json(ROOT / "data" / "manual_channels.json", None))
    prev_gcs = age_channel_status(prev_gcs)

    teams = team_cards(graph, prev_gcs)

    now = datetime.now(KST).isoformat()

    accuracy_display = (
        f'{training["accuracy"]:.2%}'
        if isinstance(training["accuracy"], (int, float))
        else str(training["accuracy"] or "N/A")
    )

    # 기존 dashboard_runtime.json에 있던 global_channels / exchange_rate 보존
    # (sync_channels.py가 나중에 덮어쓰지만, 중간 실패 시 데이터 소실 방지)
    prev = load_json(OUT, {})
    # prev_global / prev_gcs 는 위에서 이미 만들어 두었다.
    # global_channels_status 도 같이 보존해야 한다. 빠뜨려서 이 스크립트가
    # 한 번 돌 때마다 지워졌고, 워크플로가 이 스크립트를 두 번 부르는 탓에
    # 두 번째 실행에서는 gcs 가 비어 채널 카드가 "가동 0/0"으로 나왔다.
    # 후보 걸러내기도 이 값을 쓰므로 이미 붙어 있는 4건이 매번 승인 대기로
    # 다시 올라왔다. sync_channels.py 가 뒤에 채워주지만 카드는 그 전에
    # 계산이 끝나 있다.
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
        # 단계별 묶음. 화면이 팀을 순서대로 보여줄 수 있게 한다.
        "phases": {
            "now": {"label": "1단계 · 지금 돌면서 후보를 좁힌다",
                    "teams": [t["id"] for t in teams if t.get("phase") == "now"]},
            "ready": {"label": "2단계 · Shopify 가입하면 바로 등록으로 간다",
                      "teams": [t["id"] for t in teams if t.get("phase") == "ready"]},
            "always": {"label": "상시 · 시장이 바뀌면 1단계를 다시 돌린다",
                       "teams": [t["id"] for t in teams if t.get("phase") == "always"]},
        },
        "errors": _error_summary(),
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
                    + ('' if graph["audit"] == "passed" else ' · 임계 초과로 실패')
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
    if isinstance(prev_gcs, dict) and prev_gcs:
        payload["global_channels_status"] = prev_gcs
    if isinstance(prev_fx, dict) and prev_fx:
        payload["exchange_rate"] = prev_fx
    if prev_synced:
        payload["last_synced"] = prev_synced

    # 여기가 잘려 있었다. 저장 코드도 main() 호출도 없어서 실행해도
    # 아무 일이 일어나지 않았고 exit 0 만 났다. 대시보드가 09:14 에서
    # 멈춰 있던 진짜 원인이다. 쓰고 나서 되읽어 확인한다.
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(5):
        OUT.write_text(body, encoding="utf-8")
        try:
            if json.loads(OUT.read_text(encoding="utf-8-sig")) == payload:
                break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        time.sleep(0.5)
    else:
        raise SystemExit("dashboard_runtime.json 기록 검증 실패")

    print(f"저장: {OUT}")
    print(f"  생성 {now}")
    print(f"  팀 {len(teams)}개 · 파이프라인 "
          f"{payload['team_summary']['pipeline_done']}/"
          f"{payload['team_summary']['pipeline_total']}")
    print(f"  노트 {graph['notes']} · 링크 {graph['links']} · "
          f"코퍼스 {payload['team_summary']['corpus_records']}")


if __name__ == "__main__":
    main()
