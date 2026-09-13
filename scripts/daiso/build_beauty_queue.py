#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 뷰티관 상품 목록을 공식 목록 API 로 받아 큐로 만든다.

2026-09-13 에 방식을 통째로 바꿨다. 전에는 Gemini 에게 페이지를 읽어
달라고 맡겼는데 두 가지가 겹쳐서 계속 0건이 나왔다.

  1. Gemini 가 HTTP 500 을 돌려줬다
     "gemini-flash-latest is currently experiencing high demand"
  2. 500 이 아닐 때도 못 읽었다
     뷰티관 허브는 클라이언트 렌더링이라 제목이 "다이소몰" 로만 온다.
     진단 칸에 남은 답이 이랬다.
       Title: "다이소몰", 29 product cards,
       first 40 characters: "다이소몰 다이소몰 - 다이소 검색 페이지 랜딩 키티..."

  그래서 큐가 비었고, 수집기는 사이트맵 19,739건을 앞에서부터 훑었다.
  110건 중 105건이 뷰티가 아니었고 Crawl-delay 30 때문에 52분이 버려졌다.

브라우저가 그 페이지를 그릴 때 무엇을 부르는지 직접 봤다 (2026-09-13).
개발자도구 네트워크를 열고 /ds/diy2/C245 를 다시 불러서 잡은 것이다.

  fapi.daisomall.co.kr/ds/pdListApi/beauty/selGoodRevwPdList   POST {}
  fapi.daisomall.co.kr/ds/pdListApi/beauty/selRevwUp1000PdList POST {}
  fapi.daisomall.co.kr/ds/pdListApi/beauty/selRevwRankPickPdList POST {}
  fapi.daisomall.co.kr/ds/pdListApi/beauty/selDepletingStockPdList POST {}
  fapi.daisomall.co.kr/ds/pdListApi/selSnsHotPdList            POST {}

빈 본문 {} 하나로 부른다. 첫 번째가 한 번에 4,050건을 돌려줬다.
전부 뷰티관 상품이다. 페이지를 렌더할 필요도, LLM 도 필요 없다.

robots.txt (2026-09-13 확인)
  www.daisomall.co.kr 의 User-agent: * 는 /ds/ 와 /pd/pdr/ 을 허용하고
  Disallow 목록에 /or/ /ms/ /mb/ /py/ 등이 있다. Disallow: / 는 없다.
  Crawl-delay 30.

  fapi.daisomall.co.kr 은 /robots.txt 가 404 다. 규칙 파일이 없다.
  없으면 제한이 없다는 뜻이지만, 그렇다고 마구 부르지는 않는다.
  하루 다섯 번 부르는 것이 전부이고 호출 사이에 쉬는 시간을 둔다.
  우리 UA 로 신분을 밝힌다.

숫자를 어떻게 다루나
  이 API 가 주는 값은 다이소가 직접 내려주는 실측값이다.
  전 방식처럼 LLM 이 옮겨 적은 숫자가 아니다. 그래서 리뷰수·주문수·
  분류·품절여부는 그대로 기록해도 된다.

  다만 가격과 고시는 여기서 쓰지 않는다. 상세 페이지가 정본이고
  collect_daiso.py 가 원래대로 직접 받는다. 목록 API 의 pdPrc 는
  참고용으로만 남기고 이름 끝에 _list 를 붙여 출처를 구분한다.

품절·판매중지는 큐에 넣지 않는다
  soldOutYn 이 Y 이거나 판매상태가 판매중이 아니면 뺀다.
  어차피 상세를 받아도 "구매 불가" 로 실패한다. 30초씩 버릴 이유가 없다.

환경변수
  DAISO_QUEUE_DELAY   호출 사이 대기 초. 기본 5
  DAISO_QUEUE_MAX     큐에 담을 최대 개수. 기본 제한 없음
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "daiso_real" / "beauty_queue.json"
CATMAP = Path(__file__).with_name("category_map.json")

API = "https://fapi.daisomall.co.kr"
HUB = "https://www.daisomall.co.kr/ds/diy2/C245"
PRODUCT = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"

UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

DELAY = float(os.environ.get("DAISO_QUEUE_DELAY", "5"))
MAX_ITEMS = int(os.environ.get("DAISO_QUEUE_MAX", "0"))
TIMEOUT = 60

# 브라우저에서 실제로 잡은 순서 그대로 둔다.
# 앞쪽이 넓고 뒤쪽이 좁다. 좁은 것이 신호가 강하다.
SOURCES = [
    ("선호리뷰", "/ds/pdListApi/beauty/selGoodRevwPdList"),
    ("리뷰1000이상", "/ds/pdListApi/beauty/selRevwUp1000PdList"),
    ("리뷰랭킹픽", "/ds/pdListApi/beauty/selRevwRankPickPdList"),
    ("재고소진임박", "/ds/pdListApi/beauty/selDepletingStockPdList"),
    ("SNS인기", "/ds/pdListApi/selSnsHotPdList"),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def post(path: str) -> tuple[int, dict | None, str]:
    req = urllib.request.Request(
        API + path,
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
            "Origin": "https://www.daisomall.co.kr",
            "Referer": HUB,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body), ""
            except json.JSONDecodeError as e:
                return r.status, None, f"JSON 아님: {e}"
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def rows_of(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and x.get("pdNo")]
    return []


def on_sale(row: dict) -> tuple[bool, str]:
    """확인한 것만 보고 거른다.

    처음에 sleStsCd 가 "10" 이나 "SS001" 이면 판매중이라고 짐작하고
    나머지를 막았다. 그랬더니 4,518건이 전부 걸려 큐가 0건이 됐다.

    실제로 값을 세어 보니 이랬다 (2026-09-13, 선호리뷰 4,050건).
      sleStsCd   "03" 4,050건. 다른 값이 없다.
      sleStsNm   전부 null
      delYn      전부 null
      soldOutYn  N 3,574 / Y 476

    즉 03 이 판매중이고, 그 목록에는 그것밖에 안 들어온다.
    모르는 코드를 막는 규칙이 멀쩡한 상품을 다 잘라냈다.

    그래서 짐작으로 막지 않는다. 확실히 아는 것만 막는다.
    품절 표시가 Y 인 것과 삭제 표시가 Y 인 것 둘뿐이다.
    관측된 상태 코드 분포는 큐 파일에 같이 적어 둔다.
    나중에 새 코드가 나오면 세어 보고 판단한다.
    """
    if str(row.get("soldOutYn") or "").upper() == "Y":
        return False, "품절"
    if str(row.get("delYn") or "").upper() == "Y":
        return False, "삭제됨"
    return True, ""


def to_int(v) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


# ============================================================
# 받기 전에 거른다
#
# 2026-09-12 실행에서 110건을 받아 105건을 버렸다. Crawl-delay 30 이라
# 52분이다. 받아 보고 버리는 것이 문제다. 받기 전에 걸러야 한다.
#
# 목록 API 가 상품 이름을 준다. 그 이름으로 category_map.json 의
# 규칙을 그대로 돌린다. collect_daiso.py 의 classify_bucket 과 같은
# 사전을 쓰므로 두 곳의 판단이 갈리지 않는다.
#
# 선케어와 네일은 아예 뺀다. 사유는 category_map 에 적혀 있다.
#   선케어  미국에서 선크림은 OTC 의약품이다. Drug Facts 라벨이 따로 필요하다.
#   네일    매니큐어는 인화성 액체라 항공 배송에 제약이 있다.
# 받아서 버릴 것을 미리 뺀다. 30초씩 아낀다.
#
# 주의: 이름만 보는 것이라 놓치는 것이 있다. 상세 페이지를 받은 뒤
# collect_daiso 가 다시 판정한다. 여기는 그물의 첫 칸일 뿐이고
# 최종 판정이 아니다. 그래서 '예상' 이라고 적는다.
# ============================================================


def load_catmap() -> dict:
    try:
        return json.loads(CATMAP.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"category_map.json 을 못 읽었다: {e}")
        print("이름 기준 사전 거르기를 건너뛴다. 상세에서 걸러진다.")
        return {}


def excluded_by_name(name: str, catmap: dict) -> str:
    low = name.lower()
    for label, spec in (catmap.get("exclude") or {}).items():
        # category_map 의 exclude 에는 "_note" 처럼 밑줄로 시작하는 설명 칸이
        # 섞여 있고 그 값은 dict 가 아니라 문자열이다. 그대로 .get 을 부르면
        # AttributeError 로 죽는다. 실제로 죽어서 큐 생성이 멈췄다.
        if label.startswith("_") or not isinstance(spec, dict):
            continue
        for kw in spec.get("keywords") or []:
            if kw.lower() in low:
                return label
    return ""


def bucket_by_name(name: str, catmap: dict) -> str:
    low = name.lower()
    # category_map 의 순서를 지킨다. 스킨케어가 크림·로션을 다 갖고 있어
    # 앞에 두면 바디로션까지 삼킨다. 그래서 사전에 적힌 순서대로 본다.
    for bucket, words in (catmap.get("buckets") or {}).items():
        if bucket.startswith("_") or not isinstance(words, list):
            continue
        for w in words:
            if w.lower() in low:
                return bucket
    return ""


def main() -> int:
    catmap = load_catmap()
    picked: dict[str, dict] = {}
    per_source = []
    errors = []
    skipped: dict[str, int] = {}
    # 상태 코드를 짐작으로 막았다가 큐를 0건으로 만든 적이 있다.
    # 그래서 막는 대신 세어서 남긴다. 새 값이 나오면 여기서 보인다.
    status_seen: dict[str, int] = {}

    for i, (label, path) in enumerate(SOURCES):
        if i:
            time.sleep(DELAY)

        status, payload, err = post(path)
        rows = rows_of(payload)

        print(f"{label:12} {path}")
        print(f"             HTTP {status} · 항목 {len(rows)}건"
              + (f" · {err}" if err else ""))

        if err or not rows:
            errors.append({
                "출처": label,
                "endpoint": path,
                "http_status": status,
                "error": err or "항목 0건",
            })

        added = 0
        for row in rows:
            pd_no = str(row.get("pdNo") or "").strip()
            if not pd_no:
                continue

            code = f"sleStsCd={row.get('sleStsCd')!r}"
            status_seen[code] = status_seen.get(code, 0) + 1

            ok, why = on_sale(row)
            if not ok:
                skipped[why] = skipped.get(why, 0) + 1
                continue

            name = str(row.get("pdNm") or "").strip()

            drop = excluded_by_name(name, catmap)
            if drop:
                skipped[f"제외 대상 {drop}"] = (
                    skipped.get(f"제외 대상 {drop}", 0) + 1)
                continue

            if pd_no in picked:
                if label not in picked[pd_no]["출처"]:
                    picked[pd_no]["출처"].append(label)
                continue

            picked[pd_no] = {
                "pdNo": pd_no,
                "url": PRODUCT.format(pd_no),
                "출처": [label],
                # 이름으로 미리 본 버킷. 최종 판정은 상세를 받은 뒤
                # collect_daiso 의 classify_bucket 이 한다.
                "예상버킷": bucket_by_name(name, catmap),
                "이름_list": name,
                "가격_list": to_int(row.get("pdPrc")),
                "리뷰수": to_int(row.get("revwCnt")),
                "평점": row.get("avgStscVal"),
                "누적주문수": to_int(row.get("totOrQy")),
                "브랜드": str(row.get("brndNm") or "").strip(),
                # 이 목록에서 분류는 코드만 온다. 이름 칸은 전부 null 이다.
                # 4,050건을 세어서 확인했다 (2026-09-13).
                #   onlLclNm / onlMclNm / onlSclNm   0/4050 채워짐
                #   exhLCtgrNm / exhMCtgrNm / ...    0/4050 채워짐
                #   onlSclCd                         4050/4050  예 CAQ001
                # 그래서 빈 칸을 만들지 않고 코드만 남긴다.
                # 사람이 읽는 분류는 collect_daiso.py 의 classify_bucket 이
                # 상세 페이지를 보고 정한다. 그쪽이 정본이다.
                "분류코드_list": str(row.get("onlSclCd") or "").strip(),
            }
            added += 1

        per_source.append({
            "출처": label,
            "endpoint": path,
            "http_status": status,
            "받은 항목": len(rows),
            "새로 담은 것": added,
        })

    # 신호가 강한 순서로 둔다. 수집기가 앞에서부터 가져간다.
    items = sorted(
        picked.values(),
        key=lambda x: (-x["누적주문수"], -x["리뷰수"]),
    )

    if MAX_ITEMS > 0:
        items = items[:MAX_ITEMS]

    bucket_dist: dict[str, int] = {}
    for x in items:
        key = x["예상버킷"] or "(이름으로 못 가림)"
        bucket_dist[key] = bucket_dist.get(key, 0) + 1

    payload = {
        "generated_at": now(),
        "generator": "scripts/daiso/build_beauty_queue.py",
        "방식": "다이소 공식 목록 API. Gemini 를 쓰지 않는다.",
        "왜": (
            "사이트맵을 앞에서 훑으면 뷰티관 밖 상품을 받아본 뒤 버린다. "
            "2026-09-12 실행은 110건 중 105건이 그랬고 Crawl-delay 30 이라 "
            "52분이 버려졌다. 이 큐는 전부 뷰티관 상품이라 그 낭비가 없다."
        ),
        "신뢰": (
            "여기 숫자는 다이소가 직접 내려주는 실측값이다. LLM 이 옮긴 값이 "
            "아니다. 다만 가격과 고시는 상세 페이지가 정본이고 "
            "collect_daiso.py 가 직접 받는다. 목록 API 값은 _list 를 붙여 "
            "출처를 구분해 둔다."
        ),
        "robots": (
            "www.daisomall.co.kr 은 /ds/ 와 /pd/pdr/ 허용, Crawl-delay 30, "
            "Disallow: / 없음. fapi.daisomall.co.kr 은 robots.txt 가 404 라 "
            "규칙이 없다. 그래도 하루 5회만 부르고 호출 사이에 쉰다."
        ),
        "호출_간격_초": DELAY,
        "출처별": per_source,
        "제외": skipped,
        "예상버킷_분포": bucket_dist,
        "관측된_판매상태": status_seen,
        "판매상태_주의": (
            "모르는 코드를 막지 않는다. 전에 sleStsCd 를 10 이나 SS001 로 "
            "짐작하고 나머지를 막았다가 4,518건이 전부 걸려 큐가 0건이 됐다. "
            "실제로는 03 하나뿐이었다. 위 분포에 새 값이 보이면 그때 세어 본다."
        ),
        "errors": errors,
        "total": len(items),
        "new_this_run": len(items),
        "items": items,
        # collect_daiso.py 가 읽는 칸. 이름을 바꾸지 않는다.
        "urls": [x["url"] for x in items],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print(f"큐 저장: {OUT.relative_to(ROOT)}")
    print(f"담긴 상품 {len(items)}건")
    if skipped:
        print(f"제외 {sum(skipped.values())}건 · {skipped}")
    if errors:
        print(f"실패한 출처 {len(errors)}개")
        for e in errors:
            print(f"  - {e['출처']}: {e['error']}")
    print("=" * 60)

    if not items:
        print("큐가 비었다. 수집기는 사이트맵으로 돌아간다.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
