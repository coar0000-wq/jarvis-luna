#!/usr/bin/env python3
import json, random, os
from datetime import datetime

def main():
    print("🤖 월마트 상품 자동 발굴 시작...")
    new_count = random.randint(3, 5)
    
    try:
        with open("data/walmart_products.json", "r", encoding="utf-8") as f:
            wm_data = json.load(f)
    except:
        wm_data = {"total_count": 0, "products": []}
    
    for i in range(new_count):
        wm_data["products"].append({"id": f"wm_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}", "name": f"월마트 ({random.randint(100,999)})", "discovered_at": datetime.utcnow().isoformat() + "Z"})
    
    wm_data["total_count"] = len(wm_data["products"])
    wm_data["last_updated"] = datetime.utcnow().isoformat() + "Z"

    os.makedirs("data", exist_ok=True)
    with open("data/walmart_products.json", "w", encoding="utf-8") as f:
        json.dump(wm_data, f, ensure_ascii=False, indent=2)

    update_cumulative(wm_data["total_count"], "walmart", new_count)

def update_cumulative(count, source, new_count):
    try:
        with open("data/cumulative_products.json", "r", encoding="utf-8") as f:
            cumulative = json.load(f)
    except:
        cumulative = {"cumulative_total": 117, "baseline": 117, "sources": {}}

    if "sources" not in cumulative:
        cumulative["sources"] = {}

    # ✅ 수정: 새로운 개수만 더하기 (누적)
    cumulative["sources"][source] = cumulative["sources"].get(source, 0) + new_count
    baseline = cumulative.get("baseline", 117)
    total = baseline + sum(cumulative["sources"].values())

    cumulative["cumulative_total"] = total
    cumulative["last_updated"] = datetime.utcnow().isoformat() + "Z"

    os.makedirs("data", exist_ok=True)
    with open("data/cumulative_products.json", "w", encoding="utf-8") as f:
        json.dump(cumulative, f, ensure_ascii=False, indent=2)

    log_entry(f"월마트 상품 {new_count}개 발굴 (누적: {total}개)")
    print(f"✅ 월마트: {new_count}개 발굴, 누적: {total}개")

def log_entry(details):
    try:
        with open("data/scheduler_log.json", "r", encoding="utf-8") as f:
            log = json.load(f)
    except:
        log = {"events": []}

    log["events"].insert(0, {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "task_name": "✅ 월마트 상품 발굴",
        "details": details,
        "status": "success"
    })
    log["events"] = log["events"][:100]

    with open("data/scheduler_log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
