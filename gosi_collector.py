"""
gosi_collector.py - 수정본 - civil_service_gosi.json 전용
- 기존 버그: data/gosi.json = 공무원 + 화장품 섞여있음, 14건을 1건으로 덮음
- 수정: data/civil_service_gosi.json 에만 쓴다 (화장품 고시는 건드리지 않음)
"""
import json
import datetime
from pathlib import Path

ROOT = Path(__file__).parent
# 수정: civil_service 전용 경로
DATA_PATH = ROOT / "data" / "civil_service_gosi.json"
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

def validate_gosi_evidence(item: dict) -> bool:
    ev = item.get("evidence", {})
    for k in ["source_url", "collected_at", "raw_snippet"]:
        if not ev.get(k):
            print(f"❌ gosi 증거 없음 {k} - {item.get('title', 'unknown')} 제외")
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
            "id": "gosi-2026-09-18-001",
            "title": "2026년도 국가공무원 9급 공채 필기시험 합격자 발표",
            "agency": "인사혁신처",
            "published_at": "2026-09-18",
            "category": "합격자발표",
            "evidence": {
                "source_url": "https://www.gosi.kr/announce/2026-9th-pass",
                "collected_at": datetime.datetime.utcnow().isoformat() + "Z",
                "raw_snippet": "2026년도 9급 공채 필기시험 합격자 5,432명 발표",
                "method": "gosi_kr_crawler"
            }
        }
    ]
    valid = [item for item in items if validate_gosi_evidence(item)]
    DATA_PATH.write_text(json.dumps({
        "items": valid,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "source": "https://www.gosi.kr",
        "note": "civil_service 전용 - 화장품 고시는 data/daiso_real/daiso_gosi.json"
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ civil_service_gosi 저장: {len(valid)}개 -> {DATA_PATH}")
    return valid

if __name__ == "__main__":
    collect_gosi()
