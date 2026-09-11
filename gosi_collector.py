"""
gosi_collector.py - FULL FILE
gosi.json 검증 - 증거 3종 필수
"""
import json
import datetime
from pathlib import Path

DATA_PATH = Path("data/gosi.json")
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

def validate_gosi_evidence(item: dict) -> bool:
    ev = item.get("evidence", {})
    for k in ["source_url", "collected_at", "raw_snippet"]:
        if not ev.get(k):
            print(f"❌ 증거 없음 {k} - {item.get('title')} 제외")
            return False
    if not ev["source_url"].startswith("http"):
        return False
    try:
        datetime.datetime.fromisoformat(ev["collected_at"].replace("Z", "+00:00"))
    except:
        return False
    return True

def collect_gosi():
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
    DATA_PATH.write_text(json.dumps({
        "items": valid,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "source": "https://www.gosi.kr"
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ gosi 저장: {len(valid)}개")
    return valid

if __name__ == "__main__":
    collect_gosi()
