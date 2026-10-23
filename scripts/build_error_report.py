#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""흩어져 있는 실패 기록을 한 곳에 모은다.

왜
  실패 기록이 산출물마다 다른 이름으로 흩어져 있다.
    not_collected / failures / errors / failed_queries / rejected /
    auto_failures / vision_failures / parse_fail_reasons
  그래서 "지금 뭐가 안 되고 있나" 를 한 번에 볼 수 없었다.
  사람이 파일 열 번 열어봐야 알 수 있는 건 보고가 아니다.

무엇을 구분하나
  막힌 것    robots.txt 나 규정 때문에 앞으로도 못 한다. 고칠 대상이 아니다.
  고장난 것  됐어야 하는데 안 된다. 이건 고쳐야 한다.
  대기       사람이 값을 줘야 진행된다.
  보류       기술적으로 가능하지만 안 하기로 정했다.

  이 넷을 섞어놓으면 "실패 20건" 이 되고, 그러면 아무도 안 본다.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "error_report.json"

BLOCKED = "막힘"      # robots·규정. 고칠 수 없다
BROKEN = "고장"       # 됐어야 하는데 안 된다. 지금도 데이터가 안 들어온다
REPLACED = "대체됨"   # 그 주소는 죽었지만 다른 경로로 받고 있다
WAITING = "대기"      # 사람이 값을 줘야 한다
HELD = "보류"         # 할 수 있지만 안 하기로 했다

# 대체 경로가 있다는 표시. 이게 있으면 고장이 아니다.
# 처음 만들 때 이걸 안 봐서 FDA 3건을 고장으로 세었다. 실제로는
# fda_failures 가 비어 있었고 법률팀은 116건을 받고 있었다.
HAS_ALTERNATIVE = ("대체", "만 수집", "논문만", "로 대신", "대신 ")


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def classify(reason: str) -> str:
    r = str(reason)
    low = r.lower()
    if "robots" in low or "disallow" in low:
        return BLOCKED
    # 대체 경로가 적혀 있으면 데이터는 들어오고 있다. 고장이 아니다.
    if any(k in r for k in HAS_ALTERNATIVE):
        return REPLACED
    if any(k in low for k in ("404", "403", "http")) or "실패" in r or "없음" in r or "0건" in r:
        return BROKEN
    return HELD


LABEL_FIELD_GUIDANCE = {
    "내용량": ("제품별 내용량 표기 근거 또는 라벨 초안이 미완료",
            "공식 포장·고시에서 수량과 단위·구성을 확인하고 제품별 라벨 초안을 검토한다"),
    "전성분": ("제품별 전성분 표기 근거 또는 영문 라벨 초안이 미완료",
            "공식 전성분 원문과 제품별 영문 표기를 대조·검토한다"),
    "제품 정체 표시": ("제품을 식별하는 영문 이름·용도 표기가 미완료",
                 "공식 제품 정보에 맞는 제품명·용도 표기를 검토한다"),
    "책임자 이름·주소": ("책임자 이름·주소 정보 또는 검토가 미완료",
                  "지정 책임자의 이름·주소와 승인 근거를 확인한다; 제조사와 동일하다고 추정하지 않는다"),
}
LEGAL_BLOCKER_GUIDANCE = {
    "label_fields": "누락·플레이스홀더·오래된 영문 라벨 필드를 공식 근거와 대조·검토",
    "actual_label_review": "제품별 실제 라벨 근거와 사람의 검토 기록 확인",
    "responsible_person": "명시적 책임자 이름·주소와 사람의 승인 근거 확인",
    "manufacturer_product_safety": "제품별 제조사 안전 근거와 사람의 검토 기록 확인",
    "human_legal_approval": "권한 있는 사람의 제품별 법률 검토·승인 기록 확인",
    "banned_claim": "표시·광고 문구의 차단 사유와 원문을 검토",
    "otc_sunscreen": "OTC·자외선차단 관련 분류와 표시 요건을 담당자가 검토",
}


def label_field_guidance(need):
    return LABEL_FIELD_GUIDANCE.get(str(need),
        (f"라벨 준비 보고서의 미완료 항목: {need}", "해당 항목의 원본 근거와 제품별 검토 기록을 확인한다"))


def legal_block_guidance(product):
    """Describe existing blockers only; never infer clearance or a legal classification."""
    blockers = product.get("auto_blockers") or []
    if not isinstance(blockers, list):
        blockers = []
    checks = product.get("auto_checks") or {}
    if isinstance(checks, dict):
        blockers = list(dict.fromkeys([str(b) for b in blockers] + [
            str(key) for key, value in checks.items()
            if isinstance(value, dict) and value.get("ok") is False]))
    else:
        blockers = [str(b) for b in blockers]
    guidance = [f"{key}: {LEGAL_BLOCKER_GUIDANCE.get(key, '기존 점검의 원본 사유와 검토 근거 확인')}"
                for key in blockers]
    return ("; ".join(guidance) if guidance else "기존 hard_block_reason과 제품별 근거를 담당자가 검토") + "; 검토 전 차단 유지, 자동 승인 없음"


def main() -> int:
    rows: list[dict] = []

    def add(team, item, why, kind, fix=""):
        rows.append({"team": team, "item": str(item)[:60], "reason": str(why)[:160],
                     "kind": kind, "fix": fix})

    # 기관 수집팀
    inst = load(DATA / "institution_sources.json") or {}
    for org, why in (inst.get("not_collected") or {}).items():
        add("기관 수집팀", org, why, classify(why),
            "OpenAlex 현재 수집 상태는 별도 실패 기록 확인" if "OpenAlex" in str(why) else "")
    for source, meta in (inst.get("sources") or {}).items():
        for failure in meta.get("failures") or []:
            add("기관 수집팀", f"{source}: {failure.get('org', '')}",
                failure.get("reason") or "수집 실패", BROKEN,
                "지난 자료와 원래 수집 시각 보존. 접근 제한·할당량은 복구 확인 후 재시도 필요")

    # 팀 피드. not_collected 는 "예전에 이 주소가 없더라" 는 기록이지
    # 지금 고장났다는 뜻이 아니다. 실제 실패는 fda_failures 에 담긴다.
    tf = load(DATA / "team_feeds.json") or {}
    live = (tf.get("summary") or {}).get("legal") or {}
    fda_ok = not (tf.get("fda_failures") or [])
    for name, why in (tf.get("not_collected") or {}).items():
        kind = classify(why)
        if fda_ok and kind == BROKEN:
            # 지금 데이터가 들어오고 있으면 그 기록은 과거형이다.
            kind = REPLACED
        add("법률·규제팀", name, why, kind,
            f'현재 법률 자료 {live.get("total", 0)}건 수신 중 (최근 {live.get("recent", 0)}건)')
    for f in (tf.get("fda_failures") or []):
        add("법률·규제팀", f.get("name") or f, f.get("error") or "호출 실패", BROKEN,
            "이건 지금 실제로 안 되는 것이다")

    # 디자인
    ds = load(DATA / "design_sources.json") or {}
    for src, why in (ds.get("rejected") or {}).items():
        k = BLOCKED if "robots" in str(why).lower() else HELD
        add("디자인팀", src, why, k)
    for b in (ds.get("failed_blocks") or []):
        add("디자인팀", b, "수집 블록 실패", BROKEN)

    # 채널
    mc = load(DATA / "manual_channels.json") or {}
    for ch in (mc.get("channels_without_source_url") or []):
        add("채널 운영팀", ch, "수동 입력분에 출처 URL 이 없다. 나중에 다시 확인할 수 없다",
            WAITING, "CSV 에 상품 URL 열을 추가하면 해결된다")
    cc = load(DATA / "channel_candidates.json") or {}
    for c in (cc.get("candidates") or []):
        if c.get("verdict") != "가능":
            add("채널 운영팀", c.get("label") or c.get("key"), c.get("reason"),
                classify(c.get("reason")))

    # 고시·비전
    gosi = load(DATA / "gosi.json") or {}
    for f in (gosi.get("auto_failures") or []):
        add("마케팅 조사팀", f.get("pd_no"), f.get("reason"), BROKEN)
    for f in (gosi.get("vision_failures") or []):
        add("마케팅 조사팀", f.get("pd_no"), f.get("reason"), BROKEN)
    for pd in (gosi.get("vision_deferred") or []):
        stops = [s for s in (gosi.get("provider_stops") or []) if isinstance(s, dict)]
        reason = ("공급자 중단 기록: " + ", ".join(
            f"{s.get('provider')} HTTP {s.get('code')}" for s in stops
        ) + " · 대기시간 경과 후 접근·할당량 복구 확인 필요") if stops else "이번 실행에서 판독 보류 · 다음 실행의 예산·접근 상태 확인 필요"
        add("마케팅 조사팀", pd, reason, HELD)

    # 소싱 파싱 실패
    st = load(DATA / "daiso_real" / "collection_status.json") or {}
    run = st.get("last_run") or {}
    for why, n in (run.get("parse_fail_reasons") or {}).items():
        add("상품 소싱팀", f"파싱 실패 {n}건", why, BROKEN)
    if run.get("parse_failed") and not run.get("parse_fail_reasons"):
        add("상품 소싱팀", f"파싱 실패 {run['parse_failed']}건",
            "사유가 기록되지 않은 옛 실행분. 다음 수집부터 사유가 남는다", BROKEN)

    # 지식 수집
    ks = load(DATA / "knowledge" / "real_sources.json") or {}
    for name, b in (ks.get("sources") or {}).items():
        if b.get("status") not in ("ok", None):
            k = BLOCKED if "robots" in str(b.get("status", "")) + str(b.get("reason", "")) else BROKEN
            add("지식 수집팀", name, b.get("reason") or b.get("status"), k,
                b.get("대안", ""))

    # 사람 대기
    ep = load(DATA / "legal_export_prep.json") or {}
    for need in (ep.get("사람이_채워야_하는_칸") or []):
        reason, fix = label_field_guidance(need)
        add("법률·규제팀", need, reason, WAITING, fix)
    bk = load(DATA / "brand_kit.json") or {}
    for need in (bk.get("사람이_해야_하는_것") or []):
        # Older brand kits hardcoded creation without checking whether a store exists.
        if need == "Shopify 스토어 개설 (계정·도메인)":
            add("디자인팀", "Shopify 스토어 연결·기본 설정 상태 확인",
                "이 보고서에는 스토어 개설 여부 확인 근거가 없음; 미개설로 단정하지 않음", WAITING,
                "기존 스토어의 연결·계정·도메인 설정 상태를 확인한다")
        else:
            add("디자인팀", need, "준비 보고서의 검토·입력 항목; 완료 여부 확인 필요", WAITING)
    lp = load(DATA / "legal_products.json") or {}
    for k, v in (lp.get("items") or {}).items():
        if v.get("hard_block"):
            add("법률·규제팀", v.get("name"), v.get("hard_block_reason"), BLOCKED,
                legal_block_guidance(v))

    by_kind: dict = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    by_team: dict = {}
    for r in rows:
        by_team.setdefault(r["team"], {"막힘": 0, "고장": 0, "대체됨": 0,
                                       "대기": 0, "보류": 0})
        by_team[r["team"]][r["kind"]] += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_error_report.py",
        "구분": {
            BLOCKED: "robots.txt 나 규정 때문에 앞으로도 못 한다. 고칠 대상이 아니다",
            BROKEN: "됐어야 하는데 안 된다. 지금도 데이터가 안 들어온다. 고쳐야 한다",
            REPLACED: "그 주소는 죽었지만 다른 경로로 받고 있다. 기록일 뿐 할 일이 아니다",
            WAITING: "사람이 값을 줘야 진행된다",
            HELD: "기술적으로 가능하지만 안 하기로 정했다",
        },
        "total": len(rows),
        "counts": {k: len(v) for k, v in sorted(by_kind.items())},
        "by_team": by_team,
        "고쳐야_할_것": by_kind.get(BROKEN, []),
        "사람_대기": by_kind.get(WAITING, []),
        "items": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            json.loads(OUT.read_text(encoding="utf-8-sig"))
            break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"총 {len(rows)}건 · " + " · ".join(f"{k} {len(v)}" for k, v in sorted(by_kind.items())))
    for r in by_kind.get(BROKEN, [])[:8]:
        print(f"  [고장] {r['team']} · {r['item']} — {r['reason'][:60]}")
    for r in by_kind.get(WAITING, [])[:6]:
        print(f"  [대기] {r['team']} · {r['item']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
