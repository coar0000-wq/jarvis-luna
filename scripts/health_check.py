"""전체 점검. 짐작하지 않고 세어서 적는다. (2026-09-14)

보는 것
  1. 저장소 - 로컬이 원격보다 뒤인지
  2. 워크플로 - 몇 개고, 예약이 걸렸는지, 마지막으로 언제 커밋을 남겼는지
  3. 산출물 - 파일이 얼마나 묵었는지
  4. 등록 게이트 - 몇 건이 막혀 있고 무엇이 막는지
  5. 수집 - 큐와 방문 기록
  6. 규정 - robots 를 어기는 코드가 남아 있는지
  7. 열쇠 - 코드가 찾는데 저장소에 없는 값

쓰는 법  python scripts/health_check.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(__file__).resolve().parents[1]
D = R / "data"
WF = R / ".github" / "workflows"
NOW = datetime.now(timezone.utc)


def git(*a) -> str:
    p = subprocess.run(("git",) + a, cwd=R, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "").strip()


def load(rel, default=None):
    try:
        return json.loads((R / rel).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def age(ts: str | None) -> float | None:
    """ISO 문자열 -> 몇 시간 전인지."""
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (NOW - d).total_seconds() / 3600


def hours(h: float | None) -> str:
    if h is None:
        return "모름"
    if h < 1:
        return f"{int(h * 60)}분 전"
    if h < 48:
        return f"{h:.1f}시간 전"
    return f"{h / 24:.1f}일 전"


def head(t: str) -> None:
    print(f"\n{'=' * 60}\n{t}\n{'=' * 60}")


# ---------------------------------------------------------------- 1. 저장소
head("1. 저장소")
git("fetch", "-q", "origin", "main")
local = git("rev-parse", "--short", "HEAD")
remote = git("rev-parse", "--short", "origin/main")
behind = git("rev-list", "--count", "HEAD..origin/main")
ahead = git("rev-list", "--count", "origin/main..HEAD")
print(f"로컬 {local} · 원격 {remote}")
print(f"로컬이 뒤진 커밋 {behind}개 · 앞선 커밋 {ahead}개")
# -uno 를 꼭 붙인다. 그냥 status 는 추적 안 된 파일까지 훑느라
# 이 저장소(74,000개 넘음)에서 8분이 지나도 안 끝난다. 2026-09-13 에 겪었다.
dirty = [l for l in git("status", "--porcelain", "-uno").splitlines() if l.strip()]
print(f"추적 중인 파일 중 손댄 것 {len(dirty)}개")
print("\n최근 원격 커밋 8개")
for line in git("log", "--oneline", "-8", "origin/main").splitlines():
    print("  " + line)

# ------------------------------------------------------------- 2. 워크플로
head("2. 워크플로")
cron_re = re.compile(r"cron:\s*['\"]([^'\"]+)['\"]")
# 커밋 메시지는 publish 액션의 message: 입력으로 들어간다. 따옴표가 없다.
# 전에 -m '...' 만 찾다가 10개 전부 "모름" 이 나왔다. 검사기가 틀렸던 것이다.
msg_re = re.compile(r"^\s*message:\s*['\"]?(.+?)['\"]?\s*$", re.M)
rows = []
for f in sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml")):
    txt = f.read_text(encoding="utf-8", errors="replace")
    crons = cron_re.findall(txt)
    manual = "workflow_dispatch" in txt
    uses_publish = "actions/publish" in txt
    rows.append((f.name, crons, manual, uses_publish, txt))

print(f"워크플로 {len(rows)}개")
print(f"  예약 있음 {sum(1 for r in rows if r[1])}개 · "
      f"수동만 {sum(1 for r in rows if not r[1] and r[2])}개")
print(f"  발행 액션 씀 {sum(1 for r in rows if r[3])}개 / {len(rows)}개")
for name, crons, manual, pub, _ in rows:
    tag = ", ".join(crons) if crons else ("수동만" if manual else "트리거 없음")
    flag = "" if pub else "   << 발행 액션 안 씀"
    print(f"  {name:<34} {tag}{flag}")

# 워크플로가 실제로 커밋을 남기고 있나 - 원격 로그에서 찾는다
head("3. 워크플로가 실제로 커밋을 남기나")
log = git("log", "--pretty=%H%x09%cI%x09%s", "-400", "origin/main")
commits = [l.split("\t") for l in log.splitlines() if "\t" in l]
print(f"원격 최근 커밋 {len(commits)}개를 훑는다")
seen: dict[str, str] = {}
for _, when, subject in commits:
    seen.setdefault(subject.strip(), when)

for name, crons, manual, pub, txt in rows:
    if not crons:
        continue
    msgs = {m.strip() for m in msg_re.findall(txt)}
    best = None
    for m in msgs:
        for subject, when in seen.items():
            if m[:24] and m[:24] in subject:
                a = age(when)
                if a is not None and (best is None or a < best):
                    best = a
    mark = ""
    if best is None:
        mark = "   << 이 메시지의 커밋을 최근 400개에서 못 찾음"
    elif best > 48:
        mark = "   << 이틀 넘게 조용함"
    print(f"  {name:<34} {hours(best)}{mark}")

# ------------------------------------------------------------- 4. 산출물
head("4. 산출물이 얼마나 묵었나")
ARTIFACTS = [
    ("등록 게이트", "data/listing_gate.json", "generated_at"),
    ("대시보드", "data/dashboard_runtime.json", "generated_at"),
    ("고시", "data/gosi.json", None),
    ("영문 라벨", "data/daiso_real/daiso_us_labels.json", "generated_at"),
    ("라벨 동기화 보고", "data/daiso_real/us_label_sync_report.json", "generated_at"),
    ("법률 검토", "data/legal_products.json", "generated_at"),
    # 경로는 짐작하지 않는다. build_listing_gate.py 가 실제로 읽는 것과 같게 둔다.
    ("가격", "data/pricing_model.json", "generated_at"),
    ("리스팅 카피", "data/shopify_listing_copy.json", "generated_at"),
    ("S등급 추천", "data/daiso_real/shopify_s_recommendations.json", "generated_at"),
    ("수요 점수", "data/daiso_real/shopify_demand_score.json", "generated_at"),
    ("상품 목록", "data/daiso_real/products.json", "generated_at"),
    ("제외 보관", "data/daiso_real/excluded_products.json", "generated_at"),
]
# 수집 상태 파일은 이름이 여러 번 바뀌었다. 짐작하지 말고 찾는다.
for cand in sorted((D / "daiso_real").glob("*status*.json")):
    ARTIFACTS.append((f"수집상태 {cand.stem[:14]}",
                      str(cand.relative_to(R)).replace("\\", "/"),
                      "generated_at"))
for label, rel, key in ARTIFACTS:
    p = R / rel
    if not p.exists():
        print(f"  {label:<16} 파일 없음  {rel}")
        continue
    doc = load(rel, {})
    ts = None
    if key and isinstance(doc, dict):
        ts = doc.get(key)
    a = age(ts)
    if a is None:
        a = (NOW.timestamp() - p.stat().st_mtime) / 3600
        src = "파일시각"
    else:
        src = "본문"
    mark = "   << 하루 넘게 안 갱신" if a > 24 else ""
    print(f"  {label:<16} {hours(a):<12} ({src}){mark}")

# ------------------------------------------------------------- 5. 게이트
head("5. 등록 게이트")
g = load("data/listing_gate.json", {}) or {}
print(f"생성 {g.get('generated_at')}")
print(f"등록 가능 {g.get('ready')}/{g.get('total')}")
print(f"막는 칸 {json.dumps(g.get('blockers'), ensure_ascii=False)}")
items = g.get("items")
if isinstance(items, list):
    for it in items:
        if not isinstance(it, dict):
            continue
        bb = it.get("blocked_by") or []
        state = "등록가능" if not bb else "막힘: " + ", ".join(map(str, bb))
        print(f"  {str(it.get('pdNo') or it.get('pd_no')):<10} "
              f"{str(it.get('name'))[:32]:<34} {state}")

# ------------------------------------------------------------- 6. 수집
head("6. 수집")
cs = load("data/daiso_real/collect_status.json", {}) or {}
for k in ("generated_at", "url_source", "queue_size", "visited",
          "collected", "skipped_already_visited", "excluded_not_beauty"):
    if k in cs:
        print(f"  {k:<26} {cs[k]}")
prod = load("data/daiso_real/products.json", {}) or {}
plist = prod.get("items") or prod.get("products") or []
print(f"  상품 목록                   {len(plist)}건")
park = (load("data/daiso_real/excluded_products.json", {}) or {}).get("items") or {}
print(f"  제외 보관                   {len(park)}건")
gosi = (load("data/gosi.json", {}) or {}).get("items") or {}
print(f"  고시 보유                   {len(gosi)}건")
need = [k for k, v in gosi.items() if isinstance(v, dict) and not all(
    str(v.get(f) or "").strip()
    for f in ("ingredients", "volume", "maker", "origin"))]
print(f"  고시 4칸 미완성              {len(need)}건 {need[:8]}")

# ------------------------------------------------------------- 7. 규정
head("7. 규정 - robots 를 어기는 코드가 남아 있나")
BAD = {
    "export.arxiv.org": "robots 가 Disallow: / 다. 쓰면 안 된다",
    "/api/timedtext": "youtube 자막. robots 가 /api/ 를 막는다",
    "threads.com/": "robots 가 Disallow: / 다",
    "pinterest.com/": "robots 가 Disallow: / 다",
    "styles.refero.design": "ClaudeBot 을 명시적으로 막는다",
}
hits: dict[str, list[str]] = {}
for p in (R / "scripts").rglob("*.py"):
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    for bad in BAD:
        if bad in t:
            hits.setdefault(bad, []).append(str(p.relative_to(R)))
if not hits:
    print("  걸리는 것 없음")
for bad, files in hits.items():
    print(f"  [{bad}] {BAD[bad]}")
    for f in files:
        print(f"      {f}")

# ------------------------------------------------------------- 8. 열쇠
head("8. 코드가 찾는 비밀값")
secret_re = re.compile(r"secrets\.([A-Z0-9_]+)")
want: set[str] = set()
for p in WF.glob("*.y*ml"):
    want |= set(secret_re.findall(p.read_text(encoding="utf-8", errors="ignore")))
want.discard("GITHUB_TOKEN")
print("  워크플로가 쓰는 값:", ", ".join(sorted(want)) or "없음")
print("  (실제로 들어 있는지는 저장소 Settings 에서만 보입니다. "
      "키는 저에게 보내지 마시고 Settings 에서 직접 넣으시면 됩니다.)")

print("\n점검 끝")
