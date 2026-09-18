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
    path = DATA_DIR / "product_master.json"
    if not path.exists():
        print("product_master.json 없음 - build_product_master.py 먼저 실행")
        return
    
    data = json.loads(path.read_text(encoding="utf-8"))
    
    for p in data:
        # 이미 있으면 스킵, 없으면 계산 (예시 점수)
        m = p.get("match_score", 0.8)
        d = p.get("demand_score", 0.8)
        r = p.get("review_score", 0.8)
        
        # 증거 기반 demand_score 보정
        ev = p.get("evidence", {})
        if "tiktok" in ev.get("raw_snippet","").lower():
            d = min(1.0, d + 0.05)
        
        final = p.get("final_score") or calc_final(m, d, r)
        grade = grade_from_score(final)
        
        p["match_score"] = round(m,4)
        p["demand_score"] = round(d,4)
        p["review_score"] = round(r,4)
        p["final_score"] = final
        p["grade"] = grade
        p["grade_reason"] = f"match={m} demand={d} review={r} => final={final} >= {GRADE_RULE[grade]}"
    
    # S 우선 정렬
    data.sort(key=lambda x: x["final_score"], reverse=True)
    
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    s_count = len([x for x in data if x["grade"]=="S"])
    print(f"✅ Grade 계산 완료: S {s_count}개 / 전체 {len(data)}개")
    for p in data[:10]:
        print(f"  {p['canonical_id']} {p['name']} - {p['grade']} {p['final_score']} ({p['grade_reason']})")
    
    return data

if __name__ == "__main__":
    enrich_product_master()
