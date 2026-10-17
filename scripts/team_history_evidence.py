#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11팀 자기개선 추가 근거: 같은 측정을 과거 커밋 시점의 실제 파일에 적용한 일별 시계열.

왜 (2026-10-17 사용자: "11팀 자가개선 증거 추가근거검토 마련하라고")
  team_baselines.json 은 기준선 1개와 현재값 1개뿐이다. 현재값은 Core·Deep 자동화가
  돌 때만 갱신되는데 둘 다 안전 검사 교착으로 실패하고 있어 10-16 12:48 에 멈췄다.
  그래서 11팀 대부분이 '기준선 설정·추적 중' 또는 '근거 낡음' 으로만 보였다.

  커밋 이력은 이미 있는 독립된 근거다. 같은 측정 함수(build_team_baselines.measure)를
  날짜별 마지막 커밋의 파일 바이트에 그대로 적용하면, 지표를 새로 정의하지 않고도
  "어제의 우리 숫자보다 나은가" 를 날짜·커밋 SHA·근거 파일 시각과 함께 보일 수 있다.
  사람은 커밋 URL 을 열어 같은 파일을 직접 확인할 수 있다.

판정 (지표 정의는 바꾸지 않는다. 방향은 build_team_baselines 의 direction)
  improved / same / worse          최신 값과 비교 시점 값의 차이
  source_not_refreshed             두 시점의 근거 파일 시각(source_clock)이 같다.
                                   값이 같아도 '개선 없음' 이 아니라 '다시 재지 않음' 이다.
  insufficient_history             비교 시점에 그 팀 근거 파일이 없었다
  조용히 통과하지 않는다: 측정 실패·파일 없음은 사유와 함께 남는다.

하지 않는 것
  - 매출·사업 성과 검증이 아니다 (verified_gain 아님).
  - 값을 보간·추정하지 않는다. 그날 커밋이 없으면 그날은 비운다.

사용
  python scripts/team_history_evidence.py               # 최근 14일, 기준 ref=HEAD
  python scripts/team_history_evidence.py --days 21 --ref origin/main
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_team_baselines as tb  # noqa: E402

OUT = ROOT / "data" / "self_improve" / "team_history_evidence.json"
REPO_URL = "https://github.com/coar0000-wq/jarvis-luna"
KST = timezone(timedelta(hours=9))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def commit_before(ref: str, moment: datetime) -> tuple[str, str] | None:
    out = git("rev-list", "-1", f"--before={moment.isoformat()}", "--first-parent", ref).strip()
    if not out:
        return None
    when = git("show", "-s", "--format=%cI", out).strip()
    return out, when


def loader_at(commit: str):
    cache: dict[str, object] = {}

    def load(rel: str):
        if rel not in cache:
            try:
                raw = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=ROOT, capture_output=True,
                                     check=True).stdout
                cache[rel] = json.loads(raw.decode("utf-8-sig"))
            except (subprocess.CalledProcessError, ValueError, UnicodeDecodeError):
                cache[rel] = None
        return cache[rel]
    return load


def verdict(direction: str, new: dict | None, old: dict | None) -> dict:
    if not new or not old:
        return {"verdict": "insufficient_history"}
    a, b = old["value"], new["value"]
    out = {"from": old["date"], "to": new["date"], "from_value": a, "to_value": b, "change": b - a,
           "from_commit": old["commit"], "to_commit": new["commit"]}
    if old.get("source_clock") and old.get("source_clock") == new.get("source_clock"):
        return {**out, "verdict": "source_not_refreshed",
                "note": f"근거 파일 시각이 두 시점 모두 {old['source_clock']} 이다. 다시 재지 않은 값이다."}
    da, db = old.get("denominator"), new.get("denominator")
    if da != db:
        # 2026-10-17 실측: 가격팀 10/10 → 3/7. 대상 S 목록이 10개에서 7개로 바뀐 것이라 개수만
        # 비교하면 '악화' 가 과장된다. 분모가 둘 다 있으면 비율로, 하나라도 없으면 판정하지 않는다.
        out.update(from_denominator=da, to_denominator=db, denominator_changed=True)
        if not da or not db:
            return {**out, "verdict": "not_comparable",
                    "note": "분모가 한쪽에만 있다. 대상 범위가 바뀌어 개수를 그대로 비교하지 않는다."}
        ra, rb = a / da, b / db
        out.update(from_ratio=round(ra, 4), to_ratio=round(rb, 4))
        if abs(ra - rb) < 1e-9:
            return {**out, "verdict": "same"}
        better = (rb > ra) if direction == "increase" else (rb < ra)
        return {**out, "verdict": "improved" if better else "worse"}
    if b == a:
        return {**out, "verdict": "same"}
    better = (b > a) if direction == "increase" else (b < a)
    return {**out, "verdict": "improved" if better else "worse"}


def build(days: int, ref: str, today: datetime | None = None) -> dict:
    today = (today or datetime.now(KST)).astimezone(KST)
    series: dict[str, list[dict]] = {}
    meta: dict[str, tuple[str, str]] = {}
    errors: list[dict] = []
    seen: set[str] = set()
    for back in range(days, -1, -1):
        day = (today - timedelta(days=back)).date()
        end = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=KST)
        if end > today:
            end = today
        hit = commit_before(ref, end)
        if hit is None:
            continue
        commit, when = hit
        try:
            measured = tb.measure_with(loader_at(commit))
        except Exception as exc:  # noqa: BLE001  하루 측정 실패는 그날만 비우고 사유를 남긴다
            errors.append({"date": day.isoformat(), "commit": commit, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        for tid, (metric, unit, direction, value, denom, src, source_clock) in measured.items():
            meta[tid] = (metric, direction)
            series.setdefault(tid, []).append({
                "date": day.isoformat(), "commit": commit, "committed_at": when,
                "commit_url": f"{REPO_URL}/commit/{commit}", "value": value, "denominator": denom,
                "source_path": src, "source_clock": source_clock,
                "repeat_commit": commit in seen})
        seen.add(commit)
    teams = {}
    for tid, pts in sorted(series.items()):
        metric, direction = meta[tid]
        latest = pts[-1]
        by_date = {p["date"]: p for p in pts}
        d1 = (datetime.fromisoformat(latest["date"]) - timedelta(days=1)).date().isoformat()
        d7 = (datetime.fromisoformat(latest["date"]) - timedelta(days=7)).date().isoformat()
        refreshed = sorted({p["source_clock"] for p in pts if p.get("source_clock")})
        teams[tid] = {
            "metric": metric, "direction": direction,
            "latest": latest,
            "vs_previous_day": verdict(direction, latest, by_date.get(d1)),
            "vs_7_days": verdict(direction, latest, by_date.get(d7)),
            "vs_window_start": verdict(direction, latest, pts[0]),
            "source_refreshes_in_window": len(refreshed),
            "series": pts,
        }
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": "scripts/team_history_evidence.py", "ref": ref,
            "ref_commit": git("rev-parse", ref).strip(), "window_days": days,
            "method": "build_team_baselines.measure() applied to the exact file bytes of the last first-parent "
                      "commit of each KST day (git show <commit>:<path>). No interpolation.",
            "not_business_verification": True,
            "errors": errors, "teams": teams}


def history_covers(days: int, ref: str) -> bool:
    """얕은 clone(fetch-depth 1)이면 창 전체 이력이 없다. 그때 다시 쓰면 풍부한 근거를
    '이력 부족' 으로 덮는다. 발행 재생성(runtime_commands)은 모든 워크플로에서 돌기 때문이다."""
    if git("rev-parse", "--is-shallow-repository").strip() != "true":
        return True
    oldest = git("log", "--first-parent", "--reverse", "--format=%cI", ref).splitlines()
    if not oldest:
        return False
    start = datetime.now(KST) - timedelta(days=days)
    return datetime.fromisoformat(oldest[0]) <= start


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--output", type=Path, default=OUT)
    ap.add_argument("--keep-if-shallow", action="store_true",
                    help="이력이 창보다 짧으면 기존 파일을 그대로 둔다")
    a = ap.parse_args(argv)
    if a.keep_if_shallow and not history_covers(a.days, a.ref):
        print(f"TEAM_HISTORY_KEPT shallow history shorter than {a.days} days; existing file unchanged")
        return 0
    doc = build(a.days, a.ref)
    out = a.output if a.output.is_absolute() else ROOT / a.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for tid, t in doc["teams"].items():
        v7 = t["vs_7_days"]
        print(f"{tid:13s} {t['latest']['value']:>7} 7일전대비 {v7.get('verdict'):22s} "
              f"{v7.get('from_value', '-')}->{v7.get('to_value', '-')}  갱신 {t['source_refreshes_in_window']}회")
    if doc["errors"]:
        print("errors", doc["errors"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
