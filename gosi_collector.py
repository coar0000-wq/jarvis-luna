#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공무원 시험 공고 수집기.

두 가지를 고쳤다 (2026-09-12).

1) 쓰는 파일을 바꿨다. data/gosi.json -> data/civil_service_gosi.json

   data/gosi.json 은 화장품 고시 전용이다. 다이소 상품의 전성분·용량·
   제조국이 들어가고 scripts/collect_daiso_gosi.py 와
   scripts/extract_gosi_vision.py 가 채운다. 미국 MoCRA 신고에 쓰는 값이다.

   이 파일이 그 자리에 시험 공고를 써 왔다. git log 30개를 실측한 결과
   하루 동안 두 워크플로가 같은 파일을 서로 덮고 있었다.

     4d023476f  시험 1건    feat: JARVIS Deep Analysis - auto
     4770a60b4  다이소 14건  고시 표 비전 추출 및 게이트 재계산
     1bb8ef6f3  다이소 14건  Update gosi.json
     29f7c0e71  시험 1건    fix: auto-fix FAIL
     ...

   다이소 14건이 채워지면 시험 1건이 지우고, 다시 채워지면 또 지웠다.

   이제 이 파일은 data/gosi.json 을 건드리지 않는다.
   실수로 되돌리는 것을 막으려고 아래에 경로 빗장을 넣었다.

2) 박혀 있던 예시 데이터를 뺐다.

   전에는 이런 값이 파이썬 소스에 그대로 있었다.

     "raw_snippet": "2026년도 9급 공채 필기시험 합격자 5,432명 발표
                     - 인사혁신처 공고 제2026-123호"
     "collected_at": datetime.utcnow()

   5,432명 과 제2026-123호 는 어디서 받아온 값이 아니다. 사람이 적은 값이다.
   collected_at 도 수집한 시각이 아니라 그냥 실행한 시각이었다.
   그런데 validate_gosi_evidence 는 형식만 보므로 이것을 통과시켰다.
   형식이 맞는 지어낸 값이 제일 위험하다. 검증기를 통과해서 진짜로 보인다.

   CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지.
   그래서 뺐다. 지금 이 수집기는 아무것도 모으지 않는다.
   빈 결과와 '아직 수집기가 없다' 는 사유를 적는다.

   진짜로 붙이려면 gosi.kr 의 robots.txt 를 먼저 보고
   허용된 경로만 읽는 코드를 fetch_announcements() 에 넣으면 된다.
   그 전까지는 빈 채로 두는 것이 맞다. 없는 것을 있다고 하지 않는다.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "civil_service_gosi.json"

# 화장품 고시 파일을 절대 건드리지 않는다. 위 1) 의 사고를 막는 빗장이다.
FORBIDDEN = ROOT / "data" / "gosi.json"
if DATA_PATH.resolve() == FORBIDDEN.resolve():
    raise SystemExit(
        "gosi_collector.py 가 data/gosi.json 을 쓰려고 한다. "
        "그 파일은 화장품 고시 전용이다. DATA_PATH 를 되돌린 사람이 있다."
    )


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def validate_evidence(item: dict) -> bool:
    """증거 3종이 다 있는지 본다.

    주의: 이것은 형식 검사일 뿐이다. 값이 진짜인지는 못 본다.
    예전에 지어낸 값이 이 검사를 그대로 통과했다.
    그러니 이 함수를 통과했다고 해서 실측이라는 뜻이 아니다.
    실측 보장은 fetch_announcements() 가 실제로 HTTP 로 받아오는 것뿐이다.
    """
    ev = item.get("evidence") or {}
    for k in ("source_url", "collected_at", "raw_snippet"):
        if not ev.get(k):
            print(f"제외: {item.get('title', '제목없음')} — 증거 {k} 없음")
            return False
    if not str(ev["source_url"]).startswith("http"):
        print(f"제외: {item.get('title', '제목없음')} — source_url 형식 오류")
        return False
    try:
        datetime.datetime.fromisoformat(
            str(ev["collected_at"]).replace("Z", "+00:00"))
    except ValueError:
        print(f"제외: {item.get('title', '제목없음')} — collected_at 형식 오류")
        return False
    return True


def fetch_announcements() -> list[dict]:
    """실제 공고를 받아온다.

    아직 구현하지 않았다. 예시 데이터로 채우지 않는다.
    붙일 때 지켜야 할 것:
      - https://www.gosi.kr/robots.txt 를 먼저 읽고 허용 경로만 요청한다
      - raw_snippet 은 받아온 HTML 에서 잘라낸 실제 글자여야 한다
      - collected_at 은 요청을 보낸 시각이어야 한다
    """
    return []


def collect_gosi() -> list[dict]:
    items = fetch_announcements()
    valid = [x for x in items if validate_evidence(x)]

    payload = {
        "items": valid,
        "updated_at": now(),
        "source": "https://www.gosi.kr",
        "수집기": "gosi_collector.py",
        "대상": "공무원 시험 공고. 화장품 고시가 아니다.",
    }

    if not valid:
        payload["note"] = (
            "수집기가 아직 없다. 지어낸 예시 데이터를 넣지 않으려고 비워 둔다. "
            "예전 버전은 합격자 인원과 공고 번호를 소스에 박아 두고 "
            "data/gosi.json 을 덮어썼다. 2026-09-12 에 제거했다."
        )

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"{DATA_PATH.relative_to(ROOT)} 저장: {len(valid)}건")
    if not valid:
        print("  (수집기 미구현. 빈 상태로 둔다.)")
    return valid


if __name__ == "__main__":
    collect_gosi()
