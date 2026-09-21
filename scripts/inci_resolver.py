#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고시 원문의 표기 흔들림을 정본 사전의 표준명으로 되돌린다.

왜 필요한가 (2026-09-21)

  영문 라벨 5건이 ingredients_inci 하나 때문에 막혀 있었다. 사전은
  대한화장품협회 표준화명칭목록 24,678개를 그대로 담고 있는데도
  아래 열 개를 못 찾았다.

    에틸헥실메톡시신나메이트      사전은 에칠헥실메톡시신나메이트
    소듐폴리스티렌설포네이트      사전은 소듐폴리스타이렌설포네이트
    합성플루오르플로그파이트      사전은 합성플루오르플로고파이트
    다이스타다이모늄헥토라이트    사전은 다이스테아다이모늄헥토라이트
    대왕송나무잎추출물            사전은 대왕소나무잎추출물
    다이메틸실릴레이트실리카      사전은 실리카다이메틸실릴레이트
    하이드롤라이즈드하이알루로네이트   염 이름이 빠져 무엇인지 모른다
    피이지-20글리세릴-12          뒷부분이 잘려 무엇인지 모른다
    테트라데칸에이트              앞부분이 잘려 무엇인지 모른다
    경북                          주소 조각이 성분 자리에 섞였다

  앞의 여섯은 같은 성분을 다르게 적은 것이다. 뒤의 넷은 원문이
  깨져서 무엇인지 알 수 없다. 이 둘을 갈라야 한다. 앞은 기계가
  되돌릴 수 있고, 뒤는 사람이 포장 실물을 봐야 한다.

지어내지 않기 위한 규칙

  1. 정본에 있는 값만 돌려준다. 새 INCI 표기를 만들지 않는다.
  2. 후보가 여럿이고 영문 표기가 서로 다르면 포기한다.
     하이드롤라이즈드하이알루로네이트가 그렇다. 아연·소듐·칼슘 염이
     모두 가까워 하나를 고를 근거가 없다.
  3. 고친 자리는 전부 기록한다. 어느 표기를 어떤 표준명으로,
     어떤 방법으로 이었는지 남긴다. 사람이 뒤집을 수 있어야 한다.
  4. 짧은 말은 건드리지 않는다. 글자 수가 적을수록 우연히 닮는다.

되돌리는 방법 네 가지

  exact      그대로 있다
  nospace    공백만 다르다
  spelling   표기 규칙만 다르다 (에칠/에틸, 디/다이, 이소/아이소)
  distance   한두 글자가 다르고 가까운 후보의 영문 표기가 하나다
  reorder    앞뒤가 바뀌었고 글자 구성이 같은 표준명이 하나다

  사람이 봐야 하는 것은 아래로 분류해 남긴다

  not_ingredient   행정구역명 등 성분이 아닌 조각
  ambiguous        가까운 후보의 영문 표기가 갈린다
  unknown          가까운 후보 자체가 없다
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# 표기 규칙만 다른 것을 한 모양으로 접는다.
# 접은 모양은 비교에만 쓰고 라벨에는 쓰지 않는다.
# 순서가 중요하다. 긴 것을 먼저 접어야 짧은 규칙이 가로채지 않는다.
_FOLD: tuple[tuple[str, str], ...] = (
    ("스타이렌", "스티렌"),
    ("아이소", "이소"),
    ("트라이", "트리"),
    ("다이", "디"),
    ("틸", "칠"),
    ("티", "치"),
)

_STRIP_RE = re.compile(r"[\s\-·,()\[\]/]+")

# 성분 자리에 섞여 들어오는 주소 조각. 성분명이 아니다.
_ADMIN_WORDS = frozenset(
    """
    서울 부산 대구 인천 광주 대전 울산 세종 경기 강원 충북 충남
    전북 전남 경북 경남 제주 충청 전라 경상 강원도 제주도
    """.split()
)


def strip(value: str) -> str:
    return _STRIP_RE.sub("", str(value or ""))


def fold(value: str) -> str:
    """표기 규칙 차이를 지운 비교용 모양."""
    out = strip(value)
    for old, new in _FOLD:
        out = out.replace(old, new)
    return out


def _distance(a: str, b: str, limit: int) -> int:
    """글자 편집 거리. limit 을 넘으면 limit + 1 로 끊는다."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            value = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(value)
            best = min(best, value)
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


@dataclass
class Resolution:
    """한 성분명을 어떻게 읽었는지."""

    term: str
    value: str = ""
    method: str = ""
    matched: str = ""
    distance: int = 0
    reason: str = ""
    candidates: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.value)

    def as_record(self) -> dict:
        record = {
            "원문": self.term,
            "방법": self.method,
        }
        if self.ok:
            record["표준명"] = self.matched
            record["영문"] = self.value
            if self.distance:
                record["다른_글자수"] = self.distance
        else:
            record["사유"] = self.reason
            if self.candidates:
                record["후보"] = self.candidates[:6]
        return record


def load_manual_overrides(root) -> dict[str, str]:
    """사람이 포장 실물로 확인해 적어 둔 표기를 읽는다.

    기계가 못 읽는 것은 정본에 없는 것이 아니라 원문이 깨진 것일 때가
    많다. 그때는 사람이 한 줄 적어 풀어 준다. 파일이 없으면 없는 대로 둔다.

    형식
      {"상품에 적힐 한국어 성분명": "Official INCI Name"}
      {"...": {"inci": "...", "근거": "포장 실물 2026-09-21"}}
    """
    import json
    from pathlib import Path

    path = Path(root) / "data" / "manual" / "inci_overrides.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}

    if not isinstance(doc, dict):
        return {}

    out: dict[str, str] = {}
    for key, value in doc.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            value = value.get("inci") or value.get("INCI") or ""
        value = str(value or "").strip()
        if value:
            out[str(key).strip()] = value
    return out


class InciResolver:
    """정본 사전 하나를 여러 번 조회하기 위한 색인 묶음."""

    # 짧은 이름은 우연히 닮는다. 되돌리기는 이 길이부터 시도한다.
    MIN_FUZZY_LEN = 7
    MAX_DISTANCE = 2
    MAX_RATIO = 0.2

    def __init__(self, table: dict[str, str],
                 overrides: dict[str, str] | None = None):
        self.table = table or {}
        self.overrides = {k: v for k, v in (overrides or {}).items() if k and v}
        self.by_nospace: dict[str, str] = {}
        self.by_fold: dict[str, set[str]] = {}
        self.by_shape: dict[tuple[str, ...], set[str]] = {}
        self.folded_keys: list[tuple[str, str]] = []

        for key, value in self.table.items():
            value = str(value or "").strip()
            if not value:
                continue
            self.by_nospace.setdefault(strip(key), value)
            folded = fold(key)
            self.by_fold.setdefault(folded, set()).add(value)
            self.by_shape.setdefault(tuple(sorted(folded)), set()).add(value)
            self.folded_keys.append((folded, key))

    # ------------------------------------------------------------------
    # 내부 도우미
    # ------------------------------------------------------------------
    def _standard_name(self, folded: str) -> str:
        for candidate_folded, key in self.folded_keys:
            if candidate_folded == folded:
                return key
        return ""

    def _shape_name(self, shape: tuple[str, ...]) -> str:
        for candidate_folded, key in self.folded_keys:
            if tuple(sorted(candidate_folded)) == shape:
                return key
        return ""

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------
    def resolve(self, term: str) -> Resolution:
        term = str(term or "").strip()
        if not term:
            return Resolution(term=term, method="skip", reason="빈 값")

        manual = self.overrides.get(term) or self.overrides.get(strip(term))
        if manual:
            return Resolution(term=term, value=manual,
                              method="manual_override", matched=term)

        direct = self.table.get(term)
        if direct:
            return Resolution(term=term, value=direct, method="exact", matched=term)

        bare = strip(term)
        hit = self.by_nospace.get(bare)
        if hit:
            return Resolution(term=term, value=hit, method="nospace", matched=term)

        if term in _ADMIN_WORDS or bare in _ADMIN_WORDS:
            return Resolution(
                term=term,
                method="not_ingredient",
                reason="행정구역명이다. 성분표가 아니라 주소가 섞였다.",
            )

        folded = fold(term)
        values = self.by_fold.get(folded)
        if values and len(values) == 1:
            value = next(iter(values))
            return Resolution(
                term=term,
                value=value,
                method="spelling",
                matched=self._standard_name(folded),
            )
        if values:
            return Resolution(
                term=term,
                method="ambiguous",
                reason="표기를 접으면 여러 성분에 닿는다",
                candidates=sorted(values),
            )

        if len(folded) < self.MIN_FUZZY_LEN:
            return Resolution(
                term=term,
                method="unknown",
                reason="정본에 없고, 짧아서 되돌리지 않는다",
            )

        limit = min(self.MAX_DISTANCE, max(1, int(len(folded) * self.MAX_RATIO)))
        best: dict[int, set[str]] = {}
        best_key: dict[int, str] = {}
        for candidate_folded, key in self.folded_keys:
            d = _distance(folded, candidate_folded, limit)
            if d > limit:
                continue
            value = self.table.get(key, "").strip()
            if not value:
                continue
            best.setdefault(d, set()).add(value)
            best_key.setdefault(d, key)

        if best:
            near = min(best)
            values = best[near]
            if len(values) == 1:
                return Resolution(
                    term=term,
                    value=next(iter(values)),
                    method="distance",
                    matched=best_key[near],
                    distance=near,
                )
            return Resolution(
                term=term,
                method="ambiguous",
                reason=f"{near}글자 차이 후보의 영문 표기가 갈린다",
                candidates=sorted(values),
            )

        shape = tuple(sorted(folded))
        shaped = self.by_shape.get(shape)
        if shaped and len(shaped) == 1:
            return Resolution(
                term=term,
                value=next(iter(shaped)),
                method="reorder",
                matched=self._shape_name(shape),
            )
        if shaped:
            return Resolution(
                term=term,
                method="ambiguous",
                reason="앞뒤를 바꾼 후보의 영문 표기가 갈린다",
                candidates=sorted(shaped),
            )

        return Resolution(
            term=term,
            method="unknown",
            reason="정본에서 가까운 표준명을 찾지 못했다",
        )

    def resolve_all(self, terms: Iterable[str]) -> list[Resolution]:
        return [self.resolve(term) for term in terms]


def main() -> int:
    """사전을 읽어 전달한 성분명을 어떻게 읽는지 보여 준다."""
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    doc = json.loads(
        (root / "data" / "inci_dictionary.json").read_text(encoding="utf-8-sig")
    )
    resolver = InciResolver(doc.get("kr_to_inci") or {},
                            load_manual_overrides(root))

    terms = sys.argv[1:]
    if not terms:
        print("사용법: python scripts/inci_resolver.py <성분명> [...]")
        return 2

    for resolution in resolver.resolve_all(terms):
        print(json.dumps(resolution.as_record(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
