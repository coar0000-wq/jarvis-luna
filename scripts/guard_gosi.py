#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data/gosi.json 은 화장품 고시 전용이다. 다른 것이 들어오면 막는다.

무슨 일이 있었나 (2026-09-12 실측)

  data/gosi.json 이 공무원 시험 합격자 발표 1건으로 덮여 있었다.
  git log 로 30개 커밋을 되짚어 보니 하루 종일 이러고 있었다.

    4d023476f  시험 1건   feat: JARVIS Deep Analysis - auto
    4770a60b4  다이소 14건 고시 표 비전 추출 및 게이트 재계산
    1bb8ef6f3  다이소 14건 Update gosi.json
    29f7c0e71  시험 1건   fix: auto-fix FAIL
    56afd5e96  시험 1건   fix: auto-fix FAIL
    ...

  두 워크플로가 같은 파일을 서로 덮고 있었다.
  gosi-vision 이 다이소 14건을 채우면 jarvis_deep_analysis 가 시험 1건으로 지웠다.

범인은 .github/workflows/jarvis_deep_analysis.yml 이다.
JARVIS-Deep-Analysis.yml (대문자·하이픈) 이 아니다. 둘은 다른 파일이고
name: 이 둘 다 "JARVIS Deep Analysis" 라 Actions 화면에서 구분이 안 됐다.

그 워크플로가 부르는 gosi_collector.py 는 수집기가 아니었다.
합격자 5,432명 과 공고 제2026-123호 가 파이썬 소스에 박혀 있었고
collected_at 은 그냥 utcnow() 였다. 수집한 시각이 아니라 실행한 시각이다.
CLAUDE.md 의 '가짜 데이터 금지' 에 정면으로 걸린다.

그래서 이 파일을 둔다. 다시 같은 일이 나면 커밋 전에 멈춘다.

사용
  python scripts/guard_gosi.py             검사만. 어기면 종료코드 1
  python scripts/guard_gosi.py --restore   어겼으면 직전 정상 커밋에서 되살린다
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOSI = ROOT / "data" / "gosi.json"

# 화장품 고시 항목이 가진 칸. 하나라도 있으면 화장품으로 본다.
COSMETIC_FIELDS = ("name", "ingredients", "volume", "maker", "origin",
                   "expiry", "warnings", "functional", "usage")

# 시험 공고가 가진 칸. 이게 보이면 남의 데이터다.
EXAM_FIELDS = ("agency", "category", "published_at")


def git(*args) -> tuple[str, int]:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return r.stdout.decode("utf-8", "replace"), r.returncode


def judge(text: str) -> tuple[bool, str]:
    """화장품 고시가 맞는지 본다. (통과여부, 사유)"""
    try:
        d = json.loads(text)
    except Exception as e:
        return False, f"JSON 을 못 읽는다: {str(e)[:60]}"

    if not isinstance(d, dict):
        return False, f"최상위가 dict 가 아니다 ({type(d).__name__})"

    items = d.get("items")

    if isinstance(items, list):
        titles = [str(x.get("title", ""))[:40]
                  for x in items if isinstance(x, dict)][:3]
        return False, ("items 가 배열이다. 화장품 고시는 pdNo 를 키로 쓰는 "
                       f"객체여야 한다. 들어 있는 것: {titles}")

    if not isinstance(items, dict):
        return False, f"items 가 없거나 객체가 아니다 (keys={list(d)[:6]})"

    if not items:
        # 빈 것은 막지 않는다. 아직 안 모은 상태일 수 있다.
        return True, "items 가 비어 있다 (아직 수집 전)"

    for key, val in items.items():
        if not isinstance(val, dict):
            return False, f"항목 {key} 가 객체가 아니다"
        hit = [f for f in EXAM_FIELDS if val.get(f)]
        if hit and not any(val.get(f) for f in COSMETIC_FIELDS):
            return False, (f"항목 {key} 에 시험 공고 칸 {hit} 이 있고 "
                           "화장품 칸은 하나도 없다")

    digit_keys = sum(1 for k in items if str(k).isdigit())
    if digit_keys == 0:
        return False, f"키가 하나도 pdNo(숫자) 가 아니다: {list(items)[:5]}"

    has_cosmetic = any(
        any(v.get(f) for f in COSMETIC_FIELDS)
        for v in items.values() if isinstance(v, dict)
    )
    if not has_cosmetic:
        return False, "화장품 고시 칸이 채워진 항목이 하나도 없다"

    src = str(d.get("source") or "")
    if "gosi.kr" in src:
        return False, f"source 가 시험 사이트다: {src}"

    return True, f"화장품 고시 {len(items)}건"


def count_items(text: str) -> int:
    try:
        return len(json.loads(text).get("items") or {})
    except Exception:
        return 0


# 통과하는 커밋 몇 개까지 후보로 볼지.
# 최근 것 하나만 보면 적게 담긴 스냅샷을 집을 수 있다. 실제로 겪었다.
CANDIDATES = 10


def find_last_good(verbose: bool = True) -> tuple[str, str, str] | None:
    """이력에서 검사를 통과하면서 항목이 가장 많은 커밋을 찾는다.

    처음에는 '가장 최근 통과 커밋' 을 집었다. 그런데 실제로 돌려 보니
    14건짜리를 두고 7건짜리를 집었다. 고시는 하루에도 여러 번 다시 쓰이고
    비전 추출이 몇 건만 건진 실행도 커밋으로 남기 때문이다.

    되살리는 일에서 적게 담긴 쪽을 고르면 조용히 7건을 잃는다.
    그래서 통과한 후보 여러 개를 모아 항목 수가 가장 많은 것을 집는다.
    같으면 더 최근 것을 집는다.
    """
    out, _ = git("log", "--format=%H|%ad|%s", "--date=short",
                 "-60", "--", "data/gosi.json")

    picks: list[tuple[int, int, str, str, str]] = []  # (건수, -순번, sha, when, why)
    for order, line in enumerate(out.splitlines()):
        if not line.strip():
            continue
        sha, date, subj = (line.split("|", 2) + ["", ""])[:3]
        blob, rc = git("show", f"{sha}:data/gosi.json")
        if rc != 0:
            continue
        good, why = judge(blob)
        if not good or "수집 전" in why:
            continue
        picks.append((count_items(blob), -order, sha,
                      f"{date} {subj[:50]}", why))
        if len(picks) >= CANDIDATES:
            break

    if not picks:
        return None

    picks.sort(reverse=True)
    best = picks[0]

    if verbose and len(picks) > 1:
        newest = max(picks, key=lambda x: x[1])
        if newest[2] != best[2]:
            print(f"           가장 최근 통과본은 {newest[2][:9]} {newest[0]}건인데")
            print(f"           {best[2][:9]} 이 {best[0]}건으로 더 많아 그쪽을 쓴다")

    return best[2], best[3], best[4]


def main() -> int:
    restore = "--restore" in sys.argv

    if not GOSI.exists():
        print("FAIL [고시] data/gosi.json 이 없다")
        return 1

    good, why = judge(GOSI.read_text(encoding="utf-8-sig", errors="replace"))

    if good:
        print(f"OK [고시] data/gosi.json 정상 — {why}")
        return 0

    print("FAIL [고시] data/gosi.json 이 화장품 고시가 아니다")
    print(f"           사유: {why}")
    print("           이 파일은 scripts/collect_daiso_gosi.py 와")
    print("           scripts/extract_gosi_vision.py 전용이다.")
    print("           시험 공고는 data/civil_service_gosi.json 으로 간다.")

    if not restore:
        return 1

    found = find_last_good()
    if not found:
        print("           되살릴 정상 커밋을 이력 60개 안에서 못 찾았다. 사람이 봐야 한다.")
        return 1

    sha, when, what = found
    out, rc = git("checkout", sha, "--", "data/gosi.json")
    if rc != 0:
        print(f"           복구 실패: {out[:120]}")
        return 1

    again, why2 = judge(GOSI.read_text(encoding="utf-8-sig", errors="replace"))
    if not again:
        print(f"           복구했는데 여전히 어긋난다: {why2}")
        return 1

    print(f"           복구함 <- {sha[:9]} ({when})")
    print(f"           내용: {why2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
