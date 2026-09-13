"""브라우저에서 직접 읽은 고시를 gosi.json 에 넣는다. (2026-09-13)

왜 손으로 넣나
  collect_gosi_alt.py 는 만들어 두고 한 번도 안 돌렸다. 그래서 두 건이 비어 있었다.
  사용자가 화면 스크린샷으로 "고시 다 있다" 고 세 번 말했고 전부 맞았다.
  그래서 먼저 눈으로 확인한 값을 넣어 게이트를 풀고, 수집기는 뒤에 고친다.

어디서 읽었나 — 실측 경로
  상품 페이지 -> "상품설명 더보기" 버튼 클릭 -> 아래로 스크롤
  -> div.editor-content 안의 img 하나. 그 img 의 alt 가 고시 전문이다.

  1041749  alt 1,077자   전성분·용량·제조업자·제조국 다 있음
  1045421  alt   725자   전성분 없음. SPF50+/PA+++ 자외선 차단 기능성화장품

  아래 값은 그 alt 를 그대로 옮긴 것이다. 오탈자도 원문 그대로 뒀다.
  (예: "소듐폴리아크릴로알다이메틸타우레이트" 는 다이소 표기 그대로다.
   INCI 는 국제 표준이라 내가 고쳐 적으면 미국 라벨 위반이 된다.
   표준명 대응은 inci_dictionary.json 이 할 일이지 여기서 손댈 일이 아니다.)

  1045421 은 전성분이 아예 없다. 넣어도 gosi_ok 가 안 된다.
  그리고 자외선 차단 기능성이라 미국에선 OTC 의약품이다. 팔 물건이 아니다.
  그래도 기록은 남긴다. 왜 뺐는지 근거가 있어야 하기 때문이다.

쓰는 법
  python scripts/daiso/add_gosi_measured.py          보여만 준다
  python scripts/daiso/add_gosi_measured.py --apply  실제로 넣는다
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOSI = ROOT / "data" / "gosi.json"

SOURCE = "browser:editor-content img[alt] (상품설명 더보기 펼친 뒤)"

MEASURED: dict[str, dict] = {
    "1041749": {
        "name": "식물원 병풀 클리어 앰플 30ml",
        "volume": "30 ml",
        "origin": "대한민국",
        "maker": "코스맥스(주) / (주)네이처리퍼블릭",
        "ingredients": (
            "정제수, 부틸렌글라이콜, 글리세린, 1,2-헥산다이올, 프로판다이올, "
            "흰버드나무껍질추출물, 병풀추출물(100.1 ppm), 병풀잎추출물(100ppm), "
            "병풀뿌리추출물(100 ppm), 티트리잎오일, C12-14알케스-12, "
            "소듐폴리아크릴로알다이메틸타우레이트, 소듐시트레이트, 에틸헥실글리세린, "
            "시트릭애씨드, 토코페롤, 에피갈로카테킨갈레이트, 살리실릭애씨드, "
            "글라이콜릭애씨드, 카프릴릭/카프릭트라이글리세라이드, 매스틱검, "
            "하이드로제네이티드레시틴, 잔탄검, 페네틸알코올"
        ),
        "expiry": "별도표기",
        "functional": "해당없음",
        "usage": "토너 사용 후, 적당량을 덜어 얼굴 전면에 부드럽게 펴 바르고 흡수시켜줍니다.",
        "warnings": (
            "1. 화장품 사용 시 또는 사용 후 직사광선에 의하여 사용부위가 붉은 반점, "
            "부어오름 또는 가려움증 등의 이상증상에 내부작용이 있는 경우에는 전문의 등과 "
            "상담할 것\n"
            "2. 상처가 있는 부위 등에는 사용을 자재할 것\n"
            "3. 보관 및 취급 시의 주의사항\n"
            " - 어린이의 손이 닿지 않는 곳에 보관할 것\n"
            " - 직사광선을 피해서 보관할 것"
        ),
        "quality": "공정거래위원회고시 '소비자분쟁 해결기준'에 의거 보상",
        "tel": "080-890-6000",
    },
    "1045421": {
        "name": "태그듀 스킨쿠션 2호 누드라이트",
        "volume": "",
        "origin": "",
        "maker": "(주)코스메카코리아 / (주)투쿨포스쿨",
        "ingredients": "",
        "expiry": "개봉 전 30개월 / 개봉 후 12개월",
        "functional": "SPF50+ / PA+++ (미백, 주름개선, 자외선 차단 기능성화장품)",
        "usage": "",
        "warnings": (
            "상처가 있는 부위 등에는 사용을 자제할 것\n"
            "어린이 손이 닿지 않는 곳에 보관할 것"
        ),
        "quality": "",
        "tel": "1566-3128",
        "_미국_판매_불가": (
            "SPF 표시 자외선 차단 제품이다. 미국에서는 화장품이 아니라 OTC 의약품이라 "
            "sunscreen monograph 를 따라야 한다. 드롭시핑으로 팔 수 있는 물건이 아니다. "
            "근거 https://www.fda.gov/cosmetics/cosmetics-laws-regulations/"
            "it-cosmetic-drug-or-both-or-it-soap"
        ),
        "_전성분_없음": "상세 alt 725자에 전성분 항목 자체가 없다. 지어내지 않는다.",
    },
}

ALT_LEN = {"1041749": 1077, "1045421": 725}


def main() -> int:
    apply = "--apply" in sys.argv
    doc = json.loads(GOSI.read_text(encoding="utf-8-sig"))
    items = doc.setdefault("items", {})
    if not isinstance(items, dict):
        print("gosi.json 의 items 가 dict 가 아니다. 멈춘다.")
        return 1

    before = len(items)
    stamp = datetime.now(timezone.utc).isoformat()

    for pd, rec in MEASURED.items():
        row = dict(rec)
        row["captured_at"] = stamp
        row["source"] = SOURCE
        row["alt_length"] = ALT_LEN.get(pd)
        filled = [k for k in ("ingredients", "volume", "maker", "origin")
                  if str(row.get(k) or "").strip()]
        mark = "덮어씀" if pd in items else "새로"
        print(f"  {mark} {pd} {row['name'][:28]:<30} "
              f"필수 {len(filled)}/4 {filled}")
        if apply:
            items[pd] = row

    if not apply:
        print(f"\n지금은 보여주기만 했다. 넣으려면 --apply 를 붙인다. "
              f"(현재 {before}건)")
        return 0

    GOSI.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print(f"\n고시 {before} -> {len(items)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
