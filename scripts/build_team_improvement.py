#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""팀마다 스스로 나아지고 있는지 회차별로 잰다.

왜 만들었나 (2026-09-17)

  사용자가 물었다.  "모든팀들이 자기개선 하는지 없으면 개선해줘"

  찾아보니 없었다. 있는 것은 이랬다.

    coaching_loop.json   상품 한 건씩 체크리스트. 팀 단위가 아니다.
    ops_plan.json        오늘 할 일 다섯 가지. 지금 상태지 흐름이 아니다.
    audit_team_reports   숫자가 서로 맞는지 본다. 나아졌는지는 안 본다.
    cumulative_history   노트·링크 총계. 팀별이 아니다.

  전부 '지금 어떤가' 를 본다. '나아지고 있나' 를 보는 것이 없었다.

  그래서 며칠씩 같은 조치가 걸려 있어도 아무도 세지 않았다.
  실제로 그랬다.

    고시 표 5건 필요        이틀 걸려 있었다
    us_label 5건            낡은 법률 판정 때문에 계속 떠 있었다
    수집 실패: arXiv         2026-09-14 부터 사흘 걸려 있었다

  사람이 화면을 보고 "저거 어제도 있었는데" 하고 알아채야 했다.
  그건 자기개선이 아니다.

무엇을 재나

  팀 카드의 자동조치(action)와 사람·외부 대기(waiting)를 읽는다.
  종류를 함께 저장해 자동조치와 승인 대기를 섞지 않고 비교한다.

    조치가 없다가 생김        후퇴
    조치가 있다가 없어짐      개선
    같은 조치가 계속 있음     정체 (며칠째인지 센다)
    처음부터 없음            양호

  숫자를 지어내지 않는다. 팀이 이미 내놓은 조치 문구를 그대로 쓴다.
  각 팀이 무엇을 재야 하는지는 그 팀 카드가 이미 알고 있다.

정체가 길어지면 올린다

  같은 조치가 stale_after 회차를 넘기면 '오래됨' 으로 표시한다.
  그 목록이 비어 있으면 모든 팀이 굴러가고 있다는 뜻이다.

되돌아볼 수 있게 남긴다

  회차 기록을 history 에 쌓는다. 어떤 팀이 언제부터 막혔고 언제
  풀렸는지 나중에 되짚을 수 있다. 최근 max_history 회차만 둔다.

쓰는 법
  python -u scripts/build_team_improvement.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RUNTIME = DATA / "dashboard_runtime.json"
OUT = DATA / "team_improvement.json"

MAX_HISTORY = 120
STALE_AFTER = 3          # 같은 조치가 이 회차를 넘기면 오래된 것으로 본다


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def main() -> int:
    rt = load(RUNTIME, {})
    teams = rt.get("teams") or []
    if not teams:
        print("dashboard_runtime.json 에 팀 카드가 없다. 대시보드를 먼저 만든다.")
        return 1

    prev = load(OUT, {})
    prev_teams = (prev.get("teams") or {})
    history = prev.get("history") or []

    # 같은 대시보드를 두 번 읽으면 회차가 부풀어 오른다.
    #
    # 한 파이프라인 안에서 이 스크립트가 두 번 돌 수 있다(발행 직전 재생성 등).
    # 그때 정체 회차가 2로 올라가면 '이틀째 막혀 있다' 처럼 보인다.
    # 회차는 대시보드가 새로 만들어졌을 때만 센다.
    runtime_at = str(rt.get("generated_at") or rt.get("updated_at") or "")
    same_runtime = bool(runtime_at) and runtime_at == str(prev.get("runtime_at") or "")

    now = datetime.now(timezone.utc).isoformat()
    out_teams: dict[str, dict] = {}
    improved, regressed, stuck, clean = [], [], [], []

    for card in teams:
        tid = str(card.get("id") or "").strip()
        if not tid:
            continue
        name = norm(card.get("name"))
        raw_action = card.get("action")
        raw_waiting = card.get("waiting")
        action = norm(raw_action or raw_waiting)
        kind = norm(card.get("action_kind") if raw_action else card.get("waiting_kind"))
        summary = norm(card.get("summary"))
        status = norm(card.get("status"))

        old = prev_teams.get(tid) or {}
        old_action = norm(old.get("open_action"))
        old_kind = norm(old.get("open_kind"))
        old_streak = int(old.get("streak") or 0)
        old_since = old.get("since") or ""

        if action and not old_action:
            state, streak, since = "후퇴", 1, now
            regressed.append((tid, name, action))
        elif action and old_action:
            if action == old_action and kind == old_kind:
                bump = 0 if same_runtime else 1
                state = "정체"
                streak = max(old_streak + bump, 1)
                since = old_since or now
                stuck.append((tid, name, action, streak, since))
            else:
                # 막힌 내용이 바뀐 것은 앞의 것이 풀린 것이다
                state, streak, since = "일부개선", 1, now
                improved.append((tid, name, f"{old_action} → {action}"))
        elif not action and old_action:
            state, streak, since = "개선", 0, ""
            improved.append((tid, name, f"해소: {old_action}"))
        else:
            state, streak, since = "양호", 0, ""
            clean.append((tid, name))

        out_teams[tid] = {
            "name": name,
            "state": state,
            "open_action": action,
            "open_kind": kind,
            "streak": streak,
            "since": since,
            # 사람 승인·외부 조건 대기는 오래 걸려도 자동화 장애가 아니다.
            "stale": bool(action and kind in {"auto_remediable", "revalidate_only"}
                          and streak > STALE_AFTER),
            "status": status,
            "summary": summary,
            "checked_at": now,
        }

    if not same_runtime:
        history.append({
            "at": now,
            "runtime_at": runtime_at,
            "teams": len(out_teams),
            "양호": len(clean),
            "개선": len(improved),
            "정체": len(stuck),
            "후퇴": len(regressed),
            "막힌_팀": sorted(
                {t for t, *_ in stuck} | {t for t, *_ in regressed}),
        })
        history = history[-MAX_HISTORY:]

    stale = sorted(
        ((v["streak"], t, v["name"], v["open_action"], v["since"])
         for t, v in out_teams.items() if v["stale"]),
        reverse=True,
    )

    doc = {
        "generated_at": now,
        "runtime_at": runtime_at,
        "generator": "scripts/build_team_improvement.py",
        "무엇을_재나": (
            "팀 카드의 자동조치(action)와 사람·외부 대기(waiting)를 종류와 함께 "
            "회차마다 비교한다. 없다가 생기면 후퇴, 있다가 없어지면 개선, 같은 "
            "것이 계속 있으면 정체로 센다. 승인 대기는 자동화 장애로 승격하지 않는다."
        ),
        "정체_기준": f"같은 조치가 {STALE_AFTER}회차를 넘으면 오래된 것으로 표시한다",
        "왜_필요했나": (
            "지금 어떤가를 보는 것은 여럿 있었는데 나아지고 있나를 보는 것이 없었다. "
            "그래서 고시 5건이 이틀, arXiv 실패가 사흘 걸려 있어도 아무도 세지 않았다."
        ),
        "summary": {
            "teams": len(out_teams),
            "양호": len(clean),
            "개선": len(improved),
            "정체": len(stuck),
            "후퇴": len(regressed),
            "오래_막힘": len(stale),
        },
        "오래_막힌_팀": [
            {"team": t, "name": n, "회차": s, "조치": a, "처음_막힌_시각": since}
            for s, t, n, a, since in stale
        ],
        "teams": out_teams,
        "history": history,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"팀 {len(out_teams)}개 · 양호 {len(clean)} · 개선 {len(improved)} "
          f"· 정체 {len(stuck)} · 후퇴 {len(regressed)}")
    for tid, name, act in improved:
        print(f"  개선  {name}: {act[:90]}")
    for tid, name, act in regressed:
        print(f"  후퇴  {name}: {act[:90]}")
    for tid, name, act, streak, since in stuck:
        mark = " (오래됨)" if streak > STALE_AFTER else ""
        print(f"  정체  {name} {streak}회차{mark}: {act[:80]}")
    if stale:
        print(f"\n{len(stale)}개 팀이 {STALE_AFTER}회차 넘게 같은 자리에 막혀 있다.")
    print(f"저장 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("::error::팀 자기개선 집계가 예상 못한 예외로 멈췄다.",
              file=sys.stderr)
        sys.exit(1)
