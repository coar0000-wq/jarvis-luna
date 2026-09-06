#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""스토어를 열기 전에 필요한 것들을 미리 만들어 둔다.

왜
  디자인팀 카드가 "스토어 2/12단계" 에서 멈춰 있었다. 다음 단계가
  "Shopify 스토어 개설" 인데 그건 사람이 계정을 만들어야 한다. 그렇다고
  나머지를 손 놓고 기다릴 이유는 없다. 계정이 생기는 순간 바로 붙일 수
  있게 준비물을 먼저 만들어 둔다.

무엇을 만드나
  브랜드 컬러   실제로 팔 상품에서 뽑는다. 상상해서 고르지 않는다.
               Open Color 팔레트에서 고르므로 명도 대비가 보장된다.
  글꼴         Google Fonts 실수집분에서 고른다. 한글 지원 여부를 본다.
  썸네일 규격   Shopify 공개 문서 기준 수치.
  정책 페이지   미국 판매에 필요한 5종의 뼈대와 무엇을 채워야 하는지.

무엇을 안 만드나
  로고. 상표는 사람이 정할 일이고, 내가 그린 것을 쓰면 상표 분쟁을
  자초한다. 대신 로고에 쓸 색과 글꼴 후보까지만 정해 둔다.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "brand_kit.json"
DESIGN = DATA / "design_sources.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"
GATE = DATA / "listing_gate.json"
COPY = DATA / "shopify_listing_copy.json"

# Shopify 공개 문서 기준. 2026-09-06 확인.
IMAGE_SPEC = {
    "상품 이미지": {"권장": "2048 x 2048 정사각", "최대": "4472 x 4472 (20MP)",
                "용량": "20MB 이하", "형식": "JPEG 권장, PNG 는 투명 필요할 때만",
                "메모": "정사각이 아니면 격자에서 잘려 보인다"},
    "컬렉션 대표": {"권장": "1200 x 1200", "메모": "상품 이미지와 같은 여백 규칙을 쓴다"},
    "히어로 배너": {"권장": "1920 x 1080", "메모": "모바일에서 가운데가 잘리므로 "
                                          "글자를 가장자리에 두지 않는다"},
    "로고": {"권장": "높이 100~200px, 가로는 비율대로", "형식": "PNG 투명 배경",
           "메모": "어두운 배경용 흰색 버전도 함께 만든다"},
    "파비콘": {"권장": "48 x 48", "형식": "PNG"},
}

# 미국 판매에 필요한 정책 페이지. Shopify 가 템플릿을 주지만 내용은 채워야 한다.
POLICIES = {
    "환불 정책": ["반품 가능 기간(며칠)", "반품 배송비 부담자", "환불 처리 기간",
              "개봉한 화장품 반품 가능 여부 — 위생용품이라 별도로 정해야 한다"],
    "배송 정책": ["한국 발송이라는 사실 명시", "예상 소요일(우체국 기준)",
              "관세·부가세 부담자(DDU 면 구매자)", "추적 제공 여부"],
    "개인정보 처리방침": ["수집 항목", "쿠키 사용", "제3자 제공(결제·배송)",
                   "캘리포니아 CCPA 고지", "문의처"],
    "이용약관": ["판매자 정보", "주문 취소 조건", "분쟁 해결", "준거법"],
    "연락처": ["회사명", "주소", "이메일", "응답 시간"],
}


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def pick_palette(buckets: Counter, palette: dict) -> dict:
    """팔 상품의 성격에서 색을 고른다.

    스킨케어·토너가 많으면 차분한 청록·남색, 마스크팩이 많으면 분홍 계열이
    흔하다. 근거 없이 고르지 않으려고 상품 구성을 근거로 삼는다.
    """
    top = buckets.most_common(1)[0][0] if buckets else "스킨케어"
    MAP = {
        "스킨케어": ("teal", "진정·수분 계열이 많아 차분한 청록을 주색으로 둔다"),
        "마스크팩": ("pink", "마스크팩 비중이 높아 부드러운 분홍을 주색으로 둔다"),
        "클렌징": ("cyan", "세정 계열이라 맑은 청록을 주색으로 둔다"),
        "메이크업": ("grape", "색조 비중이 높아 채도 있는 자주를 주색으로 둔다"),
        "헤어케어": ("indigo", "두발 계열이라 깊은 남색을 주색으로 둔다"),
        "바디케어": ("lime", "바디 계열이라 산뜻한 연두를 주색으로 둔다"),
    }
    hue, why = MAP.get(top, ("teal", "기본값"))
    scale = palette.get(hue) or []
    gray = palette.get("gray") or []
    if not scale or not gray:
        return {"status": "no_palette", "reason": "design_sources.json 에 팔레트가 없다"}
    return {
        "status": "ok",
        "기준": f"가장 많은 상품군 '{top}' — {why}",
        "primary": {"hue": hue, "hex": scale[6], "용도": "버튼·강조"},
        "primary_dark": {"hex": scale[8], "용도": "버튼 눌림·링크 방문"},
        "primary_light": {"hex": scale[1], "용도": "배경 강조 블록"},
        "text": {"hex": gray[9], "용도": "본문"},
        "text_muted": {"hex": gray[6], "용도": "보조 설명"},
        "border": {"hex": gray[3], "용도": "구분선·입력창 테두리"},
        "bg": {"hex": "#ffffff", "용도": "기본 배경"},
        "출처": "Open Color (MIT). 명도 단계를 맞춰 만든 팔레트라 대비가 확보된다.",
    }


def pick_fonts(fonts: dict) -> dict:
    ko = fonts.get("korean_fonts") or []
    pop = fonts.get("top_popular") or []
    sans = [f for f in pop if f.get("category") == "Sans Serif"]
    serif = [f for f in pop if f.get("category") == "Serif"]
    return {
        "status": "ok" if pop else "no_fonts",
        "본문": {"후보": [f["family"] for f in sans[:3]],
               "이유": "인기 순위 상위 산세리프. 화면에서 읽기 좋고 웨이트가 많다"},
        "제목": {"후보": [f["family"] for f in (serif[:2] or sans[:2])],
               "이유": "본문과 대비를 주려면 세리프가 낫다. 없으면 산세리프 볼드"},
        "한글": {"후보": [f["family"] for f in ko[:3]],
               "이유": ("브랜드명이나 후기에 한글이 섞이면 fallback 이 깨진다. "
                      "미리 지정해 둔다")},
        "출처": "fonts.google.com/metadata/fonts 실수집분",
    }


def main() -> int:
    ds = load(DESIGN) or {}
    score = load(SCORE) or {}
    gate = load(GATE) or {}
    copy = load(COPY) or {}

    ready = [r for r in (gate.get("items") or []) if r.get("listing_ready")]
    ready_ids = {str(r["pd_no"]) for r in ready}
    by_no = {str(r.get("pd_no")): r for r in (score.get("all_scored") or [])}
    buckets = Counter(by_no[i]["bucket"] for i in ready_ids
                      if i in by_no and by_no[i].get("bucket"))

    palette = ((ds.get("colors") or {}).get("palette")) or {}
    kit_colors = pick_palette(buckets, palette)
    kit_fonts = pick_fonts(ds.get("fonts") or {})

    # 썸네일이 실제로 있는지. 없으면 만들 수도 없다.
    imgs = [(str(i.get("pd_no")), i.get("image_url"))
            for i in (copy.get("items") or []) if str(i.get("pd_no")) in ready_ids]
    have_img = [p for p, u in imgs if u]

    types = sorted({(i.get("copy") or {}).get("product_type")
                    for i in (copy.get("items") or [])
                    if str(i.get("pd_no")) in ready_ids and (i.get("copy") or {}).get("product_type")})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/prepare_brand_kit.py",
        "왜": ("스토어 개설은 사람이 해야 하지만 준비물까지 기다릴 이유는 없다. "
              "계정이 생기면 바로 붙일 수 있게 먼저 만들어 둔다."),
        "만들지_않는_것": ("로고. 상표는 사람이 정할 일이고 내가 그린 걸 쓰면 "
                     "상표 분쟁을 자초한다. 색과 글꼴 후보까지만 정해 둔다."),
        "상품_구성": dict(buckets),
        "등록_대상": len(ready),
        "colors": kit_colors,
        "fonts": kit_fonts,
        "image_spec": IMAGE_SPEC,
        "thumbnails": {"등록대상": len(ready), "이미지 있음": len(have_img),
                       "메모": ("다이소 이미지를 그대로 쓰면 배경이 제각각이라 "
                              "격자에서 어수선하다. 흰 배경 정사각으로 맞춰야 한다.")},
        "product_types": types,
        "policies": {k: {"채워야 할 것": v, "상태": "뼈대만 있음"}
                     for k, v in POLICIES.items()},
        "사람이_해야_하는_것": [
            "Shopify 스토어 개설 (계정·도메인)",
            "브랜드명과 로고 확정",
            "정책 페이지의 회사명·주소·연락처 기입",
            "MoCRA 책임자 지정 (법률팀 라벨의 마지막 빈칸과 같은 값)",
        ],
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

    c = kit_colors
    print(f"등록 대상 {len(ready)}건 · 구성 {dict(buckets)}")
    if c.get("status") == "ok":
        print(f"주색 {c['primary']['hex']} ({c['primary']['hue']}) — {c['기준']}")
    print(f"글꼴 본문 {kit_fonts.get('본문', {}).get('후보')} · "
          f"한글 {kit_fonts.get('한글', {}).get('후보')}")
    print(f"썸네일 {len(have_img)}/{len(ready)}건 이미지 확보 · 정책 {len(POLICIES)}종 뼈대")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
