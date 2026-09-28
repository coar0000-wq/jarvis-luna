#!/usr/bin/env python3
"""고시 alt 라벨 파서 회귀 테스트. 외부 호출 없음."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "daiso" / "collect_gosi_alt.py"
spec = importlib.util.spec_from_file_location("collect_gosi_alt", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

sample = """화장품법에 따라 기재·표시하여야 하는 모든 성분(전성분):
정제수, 글리세린, 세라마이드엔피

심사 필 유무(기능성화장품): 해당사항 없음
용량 또는 중량: 23 ml / 0.78 fl. oz.
제조업자 및 책임(제조) 판매업자: (주)메가코스 / 유니레버코리아(주)
제조국: 대한민국
"""
parsed = module.parse_alt(sample)
assert parsed["ingredients"] == "정제수, 글리세린, 세라마이드엔피", parsed
assert parsed["volume"] == "23 ml / 0.78 fl. oz.", parsed
assert parsed["maker"] == "(주)메가코스 / 유니레버코리아(주)", parsed
assert parsed["origin"] == "대한민국", parsed
print("GOSI_ALT_PARSER_OK")
