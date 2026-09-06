#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""영상 제목을 보고 어느 팀 자료인지 나눈다.

왜 따로 뺐나
  낱말표가 두 군데 있었다. ingest_youtube_links.py 와
  ingest_youtube_channels.py 가 각각 자기 것을 들고 있었다.

  한국어 영상이 안 걸리길래 링크 쪽에만 한글을 넣었다. 그러고 나서
  땡스큐레이터 채널을 받아보니 영상 20건이 전부 knowledge 로 떨어졌다.
  채널 쪽 표는 그대로 영어만 보고 있었던 것이다.

  표가 둘이면 또 벌어진다. 한 곳에 두고 둘 다 여기서 가져다 쓴다.

낱말을 고를 때 지킨 것
  넓게 잡으면 아무거나 걸린다. 실제로 겪은 것 두 가지를 적어둔다.

    '감각' 을 디자인에 넣었더니 '감각 있다 소리 듣는 법' 이라는
    선물 추천 영상이 디자인팀으로 갔다. 일상어는 어디에나 붙는다.

    '지원사업' 을 법률에 넣었더니 정부지원사업 영상이 법률팀으로 갔다.
    그건 규제가 아니라 자금 이야기다. 검토할 것이 없다.

  그래서 값을 다루는 말도 견적·마진·원가·수익률처럼 일하는 자리에서
  쓰는 것만 남겼다. '가격' 을 넣으면 '가격대별 안경 추천' 이 걸린다.

  '인증' 도 좁혔다. AI 허브 데이터를 받는 영상이 법률팀으로 갔는데
  API 인증 실패 이야기였다. 제품 인증과 로그인 인증은 다른 말이다.
  kc인증·안전인증·수입인증·인증기관으로 나눴다.

  '패키지' 도 '패키지디자인' 으로 좁혔다. 강의를 파는 채널의
  '동행패키지' 가 디자인팀으로 걸려 들어왔다.

  영어 낱말은 단어 경계를 본다. 'ui' 를 그냥 넣었더니 Liquid Death 를
  다루는 영상이 디자인팀으로 갔다. liq'ui'd 안에 들어 있었던 것이다.
  build, guide, quick 도 전부 걸린다. 한글은 조사가 붙어 다녀서
  경계를 못 쓴다. '브랜딩을' 을 놓치면 안 되니 그대로 포함으로 본다.

  반대로 브이로그와 호캉스는 아무 팀도 아니다. 제목에 '브랜드' 가
  섞여 있어도 팀으로 보내면 안 된다. 따로 걸러낸다.
"""
from __future__ import annotations

import re

# 팀별 낱말. 영어와 한글을 함께 둔다.
TEAM_TERMS: dict[str, list[str]] = {
    "design": [
        "theme", "design", "layout", "branding", "logo", "template",
        "typography", "figma", "wireframe", "ui", "ux",
        "디자인", "브랜딩", "로고", "패키지디자인", "레이아웃", "테마",
        "폰트", "무드보드", "톤앤매너",
    ],
    "listing": [
        "shopify", "product page", "listing", "description", "seo",
        "conversion", "checkout", "cart",
        "쇼피파이", "상세페이지", "상품페이지", "전환율", "결제", "장바구니",
    ],
    "market": [
        "k-beauty", "kbeauty", "korean skincare", "trend", "viral",
        "tiktok", "haul", "review", "instagram",
        "브랜드", "시장조사", "리서치", "트렌드", "소비", "고객", "수요",
        "큐레이션", "하울", "입점", "인스타", "웰니스", "영업",
    ],
    "pricing": [
        "pricing", "margin", "profit", "shipping cost", "dropship",
        "견적", "마진", "원가", "역마진", "수익률", "손익", "객단가",
        "단가", "정산", "수수료",
    ],
    "legal": [
        "fda", "compliance", "label", "regulation", "customs", "import",
        "수출", "통관", "관세", "규제", "라벨", "성분표시",
        "kc인증", "안전인증", "수입인증", "인증기관",
    ],
    "sourcing": [
        "daiso", "sourcing", "supplier", "wholesale",
        "다이소", "화장품", "뷰티", "스킨케어", "소싱", "도매", "사입",
        "공급처",
    ],
}

# 팀 일이 아닌 것. 제목에 이 말이 있으면 팀 배정을 하지 않는다.
# 브랜드 이름이 스쳐 지나가는 일상 영상까지 팀으로 보내면
# 나중에 팀 자료를 열었을 때 쓸 게 없다.
NOISE_TERMS = ("브이로그", "vlog", "호캉스", "먹방")

KNOWN_TEAMS = set(TEAM_TERMS) | {"knowledge"}


def _matcher(term: str):
    """낱말 하나를 어떻게 찾을지 정한다.

    영어는 단어 경계를 붙인다. 안 그러면 두세 글자짜리가 남의 단어
    속에 박힌다. 한글은 조사와 붙어 다녀서 경계를 쓰면 다 놓친다.
    """
    if term.isascii():
        pat = re.compile(r"\b" + re.escape(term) + r"\b")
        return lambda low: bool(pat.search(low))
    return lambda low: term in low


_TEAM_MATCHERS = {t: [_matcher(k) for k in terms]
                  for t, terms in TEAM_TERMS.items()}
_NOISE_MATCHERS = [_matcher(n) for n in NOISE_TERMS]


def route(text: str, forced: list[str] | str | None = None) -> list[str]:
    """제목(과 설명)을 보고 팀을 고른다.

    사람이 지정했으면 그걸 쓴다. 자동 분류는 어디까지나 추측이고
    아는 사람이 정해주면 그게 맞다.
    """
    if forced:
        return [forced] if isinstance(forced, str) else list(forced)
    low = (text or "").lower()
    if any(m(low) for m in _NOISE_MATCHERS):
        return ["knowledge"]
    hit = [t for t, ms in _TEAM_MATCHERS.items() if any(m(low) for m in ms)]
    return hit or ["knowledge"]
