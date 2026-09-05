#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""배포 전 기계적 검증.

왜 만들었나 (2026-09-04)
  하루 작업하며 실제로 겪은 실패들이다. 전부 우연히 발견해서 잡았다.
    1. 마운트 쓰기 잘림으로 .py 와 .json 이 중간에 끊김
       (score_shopify_demand.py, build_market_team.py, collection_status.json)
    2. git checkout 이 경로 하나 없다고 통째로 실패했는데 2>/dev/null 로 삼켜짐
    3. 지웠던 가짜 데이터가 다른 커밋으로 되살아남
       (google_trends_us 의 growth "+" momentum "High" 상수)
    4. 시장가를 검색 결과로 착각했는데 실제로는 베스트셀러 목록이었음
    5. 푸시가 밀렸는데 성공한 줄 알았음
  사람이 매번 기억해서 확인할 수 없다. 기계가 해야 한다.

사용
  python scripts/preflight.py            작업 트리 검사 (CI·윈도우에서 실행)
  python scripts/preflight.py --git      git 블롭 기준 검사 (샌드박스에서 실행)
  python scripts/preflight.py --quick    파일 무결성만

중요
  샌드박스 마운트에서 파일을 읽으면 중간이 잘려 보이는 일이 잦다.
  샌드박스에서 돌릴 때는 반드시 --git 을 붙여 git 이 보관한 원본을 읽어야 한다.
  작업 트리 기준 검사는 GitHub Actions 나 윈도우에서 돌린다.
종료 코드
  0 통과, 1 실패(FAIL 존재), 2 경고만 존재
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAIL, WARN, OK = [], [], []


def fail(cat, msg): FAIL.append((cat, msg))
def warn(cat, msg): WARN.append((cat, msg))
def ok(cat, msg): OK.append((cat, msg))


SKIP_DIRS = {".git", "archive", "legacy", "completed", "__pycache__",
             "node_modules", "stuffed-extracted"}
# 사람이 넣는 투입 폴더. Gemini 가 HTML 로 주는 경우가 있어 JSON 검사 대상이 아니다.
SKIP_JSON = {"data/manual"}
GIT_MODE = False
GIT_REF = "origin/main"


def read(p: Path) -> str | None:
    """--git 이면 git 블롭에서, 아니면 디스크에서 읽는다."""
    if GIT_MODE:
        rel = p.relative_to(ROOT).as_posix()
        r = subprocess.run(["git", "show", f"{GIT_REF}:{rel}"], cwd=ROOT,
                           capture_output=True)
        if r.returncode:
            return None
        return r.stdout.decode("utf-8-sig", errors="replace")
    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def walk(pattern):
    for p in ROOT.rglob(pattern):
        if any(d in p.parts for d in SKIP_DIRS):
            continue
        yield p


# ── 1. 파일 무결성 ────────────────────────────────────────────
def check_integrity():
    npy = 0
    for p in walk("*.py"):
        t = read(p)
        if t is None:
            continue
        npy += 1
        try:
            ast.parse(t)
        except SyntaxError as e:
            hint = ("BOM/인코딩 문제" if e.lineno == 1 and "U+FEFF" in (e.msg or "")
                    else "파일 잘림 의심")
            fail("무결성", f"{p.relative_to(ROOT)} 구문 오류 line {e.lineno}: "
                          f"{e.msg} ({hint})")
    ok("무결성", f"파이썬 {npy}개 구문 검사 완료")

    njson = 0
    for p in walk("*.json"):
        rel = p.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in SKIP_JSON):
            continue
        t = read(p)
        if t is None or not t.strip():
            warn("무결성", f"{rel} 빈 파일")
            continue
        njson += 1
        try:
            json.loads(t)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            fail("무결성", f"{rel} JSON 파싱 실패: {str(e)[:80]}")
    ok("무결성", f"JSON {njson}개 파싱 검사 완료")

    idx = ROOT / "index.html"
    h = read(idx) if idx.exists() else None
    if h:
        if not h.rstrip().endswith("</html>"):
            fail("무결성", "index.html 이 </html> 로 끝나지 않음 (잘림)")
        if re.search(r"^(<<<<<<<|>>>>>>>|=======)$", h, re.M):
            fail("무결성", "index.html 에 병합 충돌 마커 있음")
        Path("/tmp/_pf_index.html").write_text(h, encoding="utf-8")
        r = subprocess.run(["node", "-e",
            "const h=require('fs').readFileSync(process.argv[1],'utf8');"
            "const m=h.match(/<script>([\\s\\S]*?)<\\/script>/);"
            "if(m) new Function(m[1]);", "/tmp/_pf_index.html"],
            capture_output=True, text=True)
        if r.returncode:
            fail("무결성", f"index.html JS 구문 오류: {r.stderr.strip()[:100]}")
        else:
            ok("무결성", "index.html 구조·JS 정상")

    for p in walk("*.yml"):
        if ".github/workflows" not in str(p):
            continue
        t = read(p)
        if t is None:
            continue
        try:
            import yaml
            d = yaml.safe_load(t)
        except Exception as e:
            fail("무결성", f"{p.name} YAML 오류: {str(e)[:80]}")
            continue
        for job in (d.get("jobs") or {}).values():
            for st in job.get("steps") or []:
                run = st.get("run")
                if not run:
                    continue
                r = subprocess.run(["bash", "-n"], input=run,
                                   capture_output=True, text=True)
                if r.returncode:
                    fail("무결성", f"{p.name} [{st.get('name','?')}] "
                                  f"셸 문법 오류: {r.stderr.strip()[:80]}")


# ── 2. 가짜 데이터 재발 감시 ──────────────────────────────────
FAKE_CODE = [
    (r'random\.randint\([^)]*\)\s*\)?\s*["\']?\s*,?\s*$', "무작위 생성 흔적"),
    (r'후보\s*\(\{?random', "'후보 (N)' 자동 생성"),
    (r'^FALLBACK\s*=', "FALLBACK 상수 딕셔너리"),
]
# 값이 모든 항목에서 동일하면 조작 상수로 본다
CONSTANT_KEYS = ("growth", "momentum", "trend", "views", "loves", "status")


def check_fake():
    for p in walk("*.py"):
        txt = read(p) or ""
        for pat, label in FAKE_CODE:
            if re.search(pat, txt, re.M):
                warn("가짜데이터", f"{p.relative_to(ROOT)}: {label} 발견 - 확인 필요")

    rt = ROOT / "data" / "dashboard_runtime.json"
    t = read(rt) if rt.exists() else None
    if not t:
        return
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        return
    gc = d.get("global_channels") or {}
    st = d.get("global_channels_status") or {}

    for name, items in gc.items():
        if not isinstance(items, list) or len(items) < 3:
            continue
        for key in CONSTANT_KEYS:
            vals = [i.get(key) for i in items if isinstance(i, dict) and i.get(key)]
            if len(vals) >= 3 and len(set(vals)) == 1:
                fail("가짜데이터",
                     f"채널 {name}: 모든 항목의 '{key}' 가 '{vals[0]}' 로 동일. "
                     "실측이 아니라 상수로 채운 값일 가능성이 높다")

    for name, meta in st.items():
        c = meta.get("count", 0)
        if c > 0:
            if not meta.get("source") or meta["source"] == "-":
                fail("출처", f"채널 {name}: 데이터 {c}건인데 출처가 없음")
            if not meta.get("trust"):
                warn("출처", f"채널 {name}: 신뢰 등급(trust) 미표기")
        else:
            if not meta.get("reason"):
                fail("출처", f"채널 {name}: 비어 있는데 사유가 없음")
    ok("가짜데이터", f"채널 {len(st)}개 출처·신뢰등급 검사 완료")


# ── 3. 산출물 정합성 ──────────────────────────────────────────
def check_consistency():
    sc = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"
    if sc.exists():
        try:
            d = json.loads(read(sc) or "")
        except json.JSONDecodeError:
            d = None
        if d:
            # 점수 계산과 같은 규칙으로 더해야 한다.
            #  1) *_reference_only 항목은 참고용이라 총점에 넣지 않는다.
            #     (글로벌 유사도는 가짜 채널을 참조해 참고용으로 강등했다)
            #  2) 총점은 max(5, min(100, ...)) 로 잘린다.
            #     score_shopify_demand.py 의 total 계산과 같다.
            bad = 0
            for x in d.get("all_scored") or []:
                b = x.get("score_breakdown")
                if not b:
                    continue
                tot = sum(v for k, v in b.items()
                          if k != "max_possible"
                          and not k.endswith("reference_only")
                          and isinstance(v, (int, float)))
                expected = max(5, min(100, round(tot)))
                if abs(expected - x["shopify_score"]) > 1:
                    bad += 1
            if bad:
                fail("정합성", f"점수 내역 합계가 총점과 다른 항목 {bad}건")
            else:
                ok("정합성", f"점수 내역 합계 일치 ({len(d.get('all_scored') or [])}건)")

            S = [x for x in (d.get("all_scored") or []) if x.get("grade") == "S"]
            n = len(d.get("all_scored") or [])
            if n and len(S) / n > 0.15:
                warn("정합성", f"S등급이 {len(S)}/{n} ({len(S)/n*100:.0f}%) 로 과다. "
                              "변별력 확인 필요")

    pm = ROOT / "data" / "pricing_model.json"
    if pm.exists():
        try:
            d = json.loads(read(pm) or "")
        except json.JSONDecodeError:
            d = None
        if d:
            if not (d.get("market_benchmark") or {}).get("n"):
                fail("정합성", "pricing_model 에 시장 벤치마크가 없음")
            for label, rows in (d.get("scenarios") or {}).items():
                for r in rows[:5]:
                    calc = (r.get("unit_cost_usd", 0) + r.get("shipping_unit_usd", 0)
                            + r.get("tariff_usd", 0))
                    if abs(calc - r.get("landed_cost_usd", 0)) > 0.05:
                        fail("정합성", f"{label} {r.get('name','')[:20]}: "
                                      f"착지원가 불일치 {calc:.2f} vs {r.get('landed_cost_usd')}")
                        break
            ok("정합성", "가격 모델 계산 검증 완료")


# ── 4. 배포 상태 ──────────────────────────────────────────────
def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def check_deploy():
    r = git("status", "--short")
    if r.returncode:
        fail("배포", f"git 상태 확인 불가: {r.stderr.strip()[:80]} "
                    "(.git/index 손상 의심 - index 삭제 후 git reset)")
        return
    git("fetch", "-q", "origin", "main")
    local = git("rev-parse", "HEAD").stdout.strip()
    remote = git("rev-parse", "origin/main").stdout.strip()
    if not local or not remote:
        warn("배포", "HEAD 또는 origin/main 을 읽지 못함")
    elif local != remote:
        behind = git("rev-list", "--count", "HEAD..origin/main").stdout.strip()
        ahead = git("rev-list", "--count", "origin/main..HEAD").stdout.strip()
        warn("배포", f"로컬과 원격이 다름 (앞선 커밋 {ahead}, 뒤진 커밋 {behind}). "
                    "푸시가 누락됐는지 확인")
    else:
        ok("배포", f"로컬 == 원격 ({local[:9]})")

    if not GIT_MODE:
        for p in walk("*.json"):
            try:
                if p.read_bytes().startswith(b"\xef\xbb\xbf"):
                    warn("배포", f"{p.relative_to(ROOT)} UTF-8 BOM 있음")
            except OSError:
                pass


def main() -> int:
    global GIT_MODE
    GIT_MODE = "--git" in sys.argv
    quick = "--quick" in sys.argv
    print(f"검사 대상: {'git 블롭 (' + GIT_REF + ')' if GIT_MODE else '작업 트리'}\n")
    check_integrity()
    if not quick:
        check_fake()
        check_consistency()
        check_deploy()

    print(f"통과 {len(OK)} · 경고 {len(WARN)} · 실패 {len(FAIL)}\n")
    for cat, m in OK:
        print(f"  OK   [{cat}] {m}")
    for cat, m in WARN:
        print(f"  WARN [{cat}] {m}")
    for cat, m in FAIL:
        print(f"  FAIL [{cat}] {m}")

    if FAIL:
        print("\n배포하면 안 됩니다. 위 FAIL 을 먼저 해결하세요.")
        return 1
    if WARN:
        print("\n경고가 있습니다. 의도한 것인지 확인 후 배포하세요.")
        return 2
    print("\n배포 가능합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
