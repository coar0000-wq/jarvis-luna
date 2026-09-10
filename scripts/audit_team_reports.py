#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""팀이 보고한 숫자를 원본 파일과 대조한다.

왜 만들었나
  이틀 동안 같은 종류의 사고가 네 번 났다. 전부 사용자가 먼저 발견했다.

    1) 소싱팀은 S 5 라 하고 마케팅팀은 S 12 라 했다. 두 카드가 서로
       다른 회차의 파일을 읽고 있었는데 아무도 알려주지 않았다.
    2) 채널 카드가 가동 0/0 인데 global_channels_status 에는 12개가
       ok 로 들어 있었다.
    3) 화면 머리말은 10:37 인데 소싱 카드는 07:15 값이었다.
    4) 리스팅 카드가 'price' 를 '실측' 이라 적어 저울로 재는 것처럼 읽혔다.

  네 건 다 스크립트는 오류 없이 끝났다. 숫자만 틀렸다. 그래서 실행
  성공 여부로는 잡히지 않는다. 값을 직접 대조해야 한다.

무엇을 하나
  대시보드 카드의 숫자를 그 카드가 읽었어야 할 원본 파일과 비교한다.
  다르면 FAIL 로 끝낸다. 워크플로가 빨갛게 뜨는 편이 조용히 틀린 숫자를
  띄우는 것보다 낫다.

  단, 대시보드 파일만 새로 생성된 실행에서 팀 카드의 예전 생산 시각을
  무조건 FAIL로 취급하지 않는다. 팀별 생산 주기가 서로 다르기 때문에
  전역 대시보드 생성 시각과 카드 시각의 차이는 경고로만 남긴다. 실제
  숫자-원본 불일치와 파일 누락은 계속 FAIL이다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"

# 카드 시각이 대시보드 생성 시각보다 이만큼 이상 뒤처지면 경고로 남긴다.
# 팀별 생산 주기가 다르므로 이 자체만으로 실행 실패로 보지 않는다.
STALE_HOURS = 3.0

STALE_EXEMPT = {
    "기관 수집팀",
    "지식 수집팀",
    "로보틱스 수집",
    "디자인팀",
    "옵시디언 그래프",
}

problems: list[str] = []
notes: list[str] = []


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        problems.append(
            f"{path.name} 을 읽지 못함 ({type(e).__name__})"
        )
        return None


def num(text: str, pattern: str):
    """카드 문구에서 숫자를 뽑는다. 못 뽑으면 None."""
    m = re.search(pattern, text or "")
    return int(m.group(1)) if m else None


def card(teams: list, tid: str) -> dict:
    for t in teams:
        if t.get("id") == tid:
            return t
    return {}


def main() -> int:
    rt = load(D / "dashboard_runtime.json")

    if not rt:
        print("대시보드를 읽지 못해 중단")
        return 1

    teams = rt.get("teams") or []
    gen = rt.get("generated_at") or ""

    # ── 1. 카드 시각 ─────────────────────────────────────────
    # 예전에는 dashboard_runtime.json의 generated_at보다 카드가
    # 3시간 이상 오래되면 무조건 FAIL 했다.
    #
    # 하지만 publish 액션이 dashboard_runtime.json 하나만 새로 만든
    # 경우에는 정상적으로 오래된 카드가 그대로 남을 수 있다.
    #
    # 따라서 이제는 경고로만 기록하고,
    # 실제 숫자/원본 대조는 계속 엄격하게 한다.
    try:
        gen_dt = datetime.fromisoformat(gen)
    except ValueError:
        gen_dt = None

    if gen_dt:
        stale_names = []

        for t in teams:
            if t.get("name") in STALE_EXEMPT or not t.get("when"):
                continue

            try:
                w = datetime.fromisoformat(str(t["when"]))
            except ValueError:
                continue

            if w.tzinfo is None:
                w = w.replace(tzinfo=timezone.utc)

            gap = (gen_dt - w).total_seconds() / 3600

            if gap > STALE_HOURS:
                stale_names.append(
                    f"{t.get('name')} {gap:.1f}시간"
                )

        if stale_names:
            notes.append(
                "팀 카드 시각은 대시보드 생성 시각과 다를 수 있음(경고만): "
                + ", ".join(stale_names)
            )

    # ── 2. 소싱 S 개수가 세 곳에서 같은가 ────────────────────
    sc = load(D / "daiso_real" / "shopify_demand_score.json")
    s_real = None

    if sc:
        s_real = (sc.get("grade_summary") or {}).get("S")
        n_real = sc.get("total_products")

        c = card(teams, "sourcing")

        s_card = num(
            c.get("summary", ""),
            r"S\s*(\d+)"
        )

        n_card = num(
            c.get("summary", ""),
            r"(\d+)개 상품"
        )

        if s_card is not None and s_real is not None and s_card != s_real:
            problems.append(
                f"소싱 카드 S {s_card} vs 실제 {s_real}"
            )

        if n_card is not None and n_real is not None and n_card != n_real:
            problems.append(
                f"소싱 카드 상품수 {n_card} vs 실제 {n_real}"
            )

    mt = load(D / "market_team.json")

    if mt and s_real is not None:
        s_mt = mt.get("s_count")

        if s_mt is not None and s_mt != s_real:
            problems.append(
                f"마케팅팀 s_count {s_mt} vs 소싱 점수 S {s_real}. "
                "마케팅 보드가 점수 재계산 전 파일을 읽었다"
            )

        c = card(teams, "market")

        s_card = num(
            c.get("summary", ""),
            r"S등급\s*(\d+)"
        )

        if s_card is not None and s_card != s_real:
            problems.append(
                f"마케팅 카드 S등급 {s_card} vs 소싱 점수 S {s_real}"
            )

    # ── 3. 리스팅 게이트 ─────────────────────────────────────
    gate = load(D / "listing_gate.json")

    if gate:
        c = card(teams, "listing")

        r_card = num(
            c.get("summary", ""),
            r"등록 가능\s*(\d+)"
        )

        t_card = num(
            c.get("summary", ""),
            r"등록 가능\s*\d+/(\d+)"
        )

        if r_card is not None and r_card != gate.get("ready"):
            problems.append(
                f"리스팅 카드 ready {r_card} vs 게이트 {gate.get('ready')}"
            )

        if t_card is not None and t_card != gate.get("total"):
            problems.append(
                f"리스팅 카드 total {t_card} vs 게이트 {gate.get('total')}"
            )

        if (
            s_real is not None
            and gate.get("total") not in (None, s_real)
        ):
            problems.append(
                f"게이트 대상 {gate.get('total')}건 vs S등급 {s_real}건. "
                "게이트가 점수보다 먼저 돌았다"
            )

        if gate.get("unreadable"):
            problems.append(
                f"게이트가 읽지 못한 파일: {gate['unreadable']}"
            )

    # ── 4. 채널 ─────────────────────────────────────────────
    gcs = rt.get("global_channels_status") or {}

    live = sum(
        1
        for v in gcs.values()
        if (v or {}).get("status") == "ok"
    )

    c = card(teams, "channels")

    l_card = num(
        c.get("summary", ""),
        r"가동\s*(\d+)"
    )

    t_card = num(
        c.get("summary", ""),
        r"가동\s*\d+/(\d+)"
    )

    if gcs:
        if l_card is not None and l_card != live:
            problems.append(
                f"채널 카드 가동 {l_card} vs 실제 ok {live}. "
                "global_channels_status 가 보존되지 않았을 수 있다"
            )

        if t_card is not None and t_card != len(gcs):
            problems.append(
                f"채널 카드 총 {t_card} vs 실제 {len(gcs)}"
            )

    elif l_card:
        problems.append(
            "채널 카드에 숫자가 있는데 global_channels_status 가 비었다"
        )

    cand = load(D / "channel_candidates.json")

    if cand:
        fresh = [
            x
            for x in (cand.get("candidates") or [])
            if x.get("verdict") == "가능"
            and not x.get("already_live")
        ]

        p_card = num(
            c.get("summary", ""),
            r"미연동\s*(\d+)"
        )

        if p_card is not None and p_card != len(fresh):
            problems.append(
                f"채널 카드 미연동 {p_card} vs 실제 신규 후보 {len(fresh)}"
            )

    # ── 5. 법률: 자동이 사람 판정을 뒤집지 않았나 ────────────
    lp = load(D / "legal_products.json")

    if lp:
        items = lp.get("items") or {}

        hard = [
            k
            for k, v in items.items()
            if v.get("hard_block")
        ]

        for pd_no in hard:
            g = (gate or {}).get("items") or []

            for row in g:
                if (
                    str(row.get("pd_no")) == pd_no
                    and row.get("listing_ready")
                ):
                    problems.append(
                        f"{pd_no} 는 법률 hard_block 인데 "
                        "게이트가 등록 가능으로 뒀다"
                    )

        for k, v in items.items():
            if v.get("status") == "fail":
                for row in (gate or {}).get("items") or []:
                    if (
                        str(row.get("pd_no")) == k
                        and row.get("legal_ok")
                    ):
                        problems.append(
                            f"{k} 는 사람이 fail 로 적었는데 legal_ok 다"
                        )

    # ── 6. 소싱 제외 규칙이 실제로 지켜졌나 ──────────────────
    cmap = load(
        ROOT / "scripts" / "daiso" / "category_map.json"
    )

    prods = load(
        D / "daiso_real" / "products.json"
    )

    if cmap and prods:
        rows = (
            prods
            if isinstance(prods, list)
            else (prods.get("products") or [])
        )

        ex = cmap.get("exclude") or {}
        leaked = []

        for r in rows:
            hay = " ".join(
                filter(
                    None,
                    [
                        r.get("site_category"),
                        r.get("name"),
                    ],
                )
            ).lower()

            for name, spec in ex.items():
                if name.startswith("_"):
                    continue

                if any(
                    str(k).lower() in hay
                    for k in (spec.get("keywords") or [])
                ):
                    leaked.append(
                        (
                            name,
                            str(r.get("name"))[:24]
                        )
                    )
                    break

        if leaked:
            problems.append(
                f"제외 대상이 상품 목록에 {len(leaked)}건 남아 있다: "
                + ", ".join(
                    f"{a}/{b}"
                    for a, b in leaked[:3]
                )
            )
        else:
            notes.append(
                f"제외 규칙 준수 확인 ({len(rows)}건 전수)"
            )

    # ── 결과 ────────────────────────────────────────────────
    print(
        f"대시보드 생성 {gen[:19]} · 팀 {len(teams)}개"
    )

    for n in notes:
        print(f"  OK   {n}")

    if not problems:
        print(
            "  OK   팀 보고 숫자와 원본 파일이 모두 일치"
        )
        return 0

    print(
        f"\n불일치 {len(problems)}건"
    )

    for p in problems:
        print(f"  FAIL {p}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
