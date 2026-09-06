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
BROKEN = "고장"       # 됐어야 하는데 안 된다
WAITING = "대기"      # 사람이 값을 줘야 한다
HELD = "보류"         # 할 수 있지만 안 하기로 했다


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def classify(reason: str) -> str:
    r = str(reason).lower()
    if "robots" in r or "disallow" in r:
        return BLOCKED
    if "404" in r or "403" in r or "http" in r or "실패" in r or "없음" in r or "0건" in r:
        return BROKEN
    return HELD


def main() -> int:
    rows: list[dict] = []

    def add(team, item, why, kind, fix=""):
        rows.append({"team": team, "item": str(item)[:60], "reason": str(why)[:160],
                     "kind": kind, "fix": fix})

    # 기관 수집팀
    inst = load(DATA / "institution_sources.json") or {}
    for org, why in (inst.get("not_collected") or {}).items():
        add("기관 수집팀", org, why, classify(why),
            "OpenAlex 논문 경로는 살아 있다" if "OpenAlex" in str(why) else "")

    # 팀 피드
    tf = load(DATA / "team_feeds.json") or {}
    for name, why in (tf.get("not_collected") or {}).items():
        add("법률·규제팀", name, why, classify(why),
            "openFDA 다른 엔드포인트로 대체 중" if "openFDA" in str(name) else "")

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
        add("마케팅 조사팀", pd, "비전 예산 초과로 다음 회차로 미룸", HELD)

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
        add("법률·규제팀", need, "MoCRA 책임자 정보. 회사명과 주소가 필요하다", WAITING,
            "한 번 알려주면 라벨과 정책 페이지 양쪽에 들어간다")
    bk = load(DATA / "brand_kit.json") or {}
    for need in (bk.get("사람이_해야_하는_것") or []):
        add("디자인팀", need, "사람만 할 수 있는 일", WAITING)
    lp = load(DATA / "legal_products.json") or {}
    for k, v in (lp.get("items") or {}).items():
        if v.get("hard_block"):
            add("법률·규제팀", v.get("name"), v.get("hard_block_reason"), BLOCKED,
                "Drug Facts 라벨을 갖추면 다시 볼 수 있다")

    by_kind: dict = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    by_team: dict = {}
    for r in rows:
        by_team.setdefault(r["team"], {"막힘": 0, "고장": 0, "대기": 0, "보류": 0})
        by_team[r["team"]][r["kind"]] += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_error_report.py",
        "구분": {
            BLOCKED: "robots.txt 나 규정 때문에 앞으로도 못 한다. 고칠 대상이 아니다",
            BROKEN: "됐어야 하는데 안 된다. 고쳐야 한다",
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
