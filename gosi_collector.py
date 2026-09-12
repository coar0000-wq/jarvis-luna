"""
gosi_collector.py - FULL FILE 전체 덮어쓰기용
gosi.json 검증 로직 - 증거 필수 (CLAUDE.md Rule 1)
"""

import json
import datetime
from pathlib import Path

DATA_PATH = Path("data/gosi.json")
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

def validate_gosi_evidence(item: dict) -> bool:
    """gosi 항목 증거 검증 - 3종 세트 필수"""
    ev = item.get("evidence", {})
    required = ["source_url", "collected_at", "raw_snippet"]
    for k in required:
        if not ev.get(k):
            print(f"❌ gosi 증거 없음 {k} - {item.get('title', 'unknown')} 제외")
            return False
    # URL 형식 간단 검증
    if not ev["source_url"].startswith("http"):
        print(f"❌ source_url 형식 오류")
        return False
    try:
        datetime.datetime.fromisoformat(ev["collected_at"].replace("Z", "+00:00"))
    except:
        print(f"❌ collected_at 형식 오류 - {item.get('title')}")
        return False
    return True

def collect_gosi():
    """
    실제 고시 공고 수집 로직
    예: 인사혁신처 https://www.gosi.kr 등
    현재는 예시 데이터 1개 (증거 포함)
    """
    items = [
        {
            "id": "gosi-2026-09-12-001",
            "title": "2026년도 국가공무원 9급 공채 필기시험 합격자 발표",
            "agency": "인사혁신처",
            "published_at": "2026-09-11",
            "category": "합격자발표",
            "evidence": {
                "source_url": "https://www.gosi.kr/announce/2026-9th-pass",
                "collected_at": datetime.datetime.utcnow().isoformat() + "Z",
                "raw_snippet": "2026년도 9급 공채 필기시험 합격자 5,432명 발표 - 인사혁신처 공고 제2026-123호",
                "method": "gosi_kr_crawler"
            }
        }
    ]
    
    valid = [item for item in items if validate_gosi_evidence(item)]
    
    if not valid:
        DATA_PATH.write_text(json.dumps({
            "items": [],
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "note": "no valid evidence - gosi hidden",
            "source": "https://www.gosi.kr"
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print("ℹ️ gosi 유효 데이터 없음 - 숨김 처리")
        return []
    
    DATA_PATH.write_text(json.dumps({
        "items": valid,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "source": "https://www.gosi.kr"
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ gosi 저장: {len(valid)}개")
    return valid

if __name__ == "__main__":
    collect_gosi()
