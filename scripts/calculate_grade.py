"""
calculate_grade.py - P0-2 S등급 정량화
match_score + demand_score + review_score -> final_score
Grade 기준 코드 고정

S >=0.85
A >=0.75
B >=0.60
C <0.60
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

GRADE_RULE = {
    "S": 0.85,
    "A": 0.75,
    "B": 0.60,
    "C": 0.00
}

def calc_final(match: float, demand: float, review: float, w_match=0.3, w_demand=0.4, w_review=0.3):
    return round(match*w_match + demand*w_demand + review*w_review, 4)

def grade_from_score(final: float) -> str:
    if final >= GRADE_RULE["S"]:
        return "S"
    elif final >= GRADE_RULE["A"]:
        return "A"
    elif final >= GRADE_RULE["B"]:
        return "B"
    else:
        return "C"

def enrich_product_master():
    """호환 진입점.

    M/D/Q는 병행 관찰 지표다. 근거가 없을 때 0.8을 넣거나 기존 S등급을
    덮어쓰지 않는다. 운영 점수와 CP는 build_product_master가 한 번에 갱신한다.
    """
    from build_product_master import build_master

    doc = build_master(inject_scores=True)
    rows = doc.get("products") or []
    observed = [p for p in rows if p.get("component_scores")]
    print(f"병행 M/D/Q 지표 {len(observed)}/{len(rows)}건 · 기존 100점제 등급 유지")
    return doc

if __name__ == "__main__":
    enrich_product_master()
