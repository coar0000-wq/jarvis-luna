#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS - Auto Update Timestamps
실시간 데이터 타임스탐프 자동 갱신
"""

import json
from datetime import datetime
import pytz

# 현재 시간 (KST)
kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
timestamp_iso = now.isoformat()
timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')

print("\n" + "="*80)
print("🤖 JARVIS - 자동 타임스탐프 갱신")
print("="*80)
print(f"\n📅 현재 시간: {timestamp_str} KST")
print(f"🕐 ISO 형식: {timestamp_iso}")

# 1. cumulative_products.json
print("\n✅ Step 1: cumulative_products.json 갱신")
try:
    with open('cumulative_products.json', 'r', encoding='utf-8', errors='ignore') as f:
        data = json.load(f)

    # 타임스탐프 업데이트
    data['metadata']['timestamp'] = timestamp_iso
    data['metadata']['last_update'] = timestamp_str

    with open('cumulative_products.json', 'w', encoding='utf-8', errors='ignore') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 갱신 완료: {timestamp_str}")
except Exception as e:
    print(f"   ❌ 오류: {e}")

# 2. scheduler_log.json
print("\n✅ Step 2: scheduler_log.json 갱신")
try:
    with open('scheduler_log.json', 'r', encoding='utf-8', errors='ignore') as f:
        data = json.load(f)

    # 최신 이벤트에 현재 타임스탐프 추가
    if 'events' in data and len(data['events']) > 0:
        data['events'][0]['timestamp'] = timestamp_iso

    with open('scheduler_log.json', 'w', encoding='utf-8', errors='ignore') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 갱신 완료: {timestamp_str}")
except Exception as e:
    print(f"   ❌ 오류: {e}")

# 3. phase_26_progress.json
print("\n✅ Step 3: phase_26_progress.json 갱신")
try:
    with open('phase_26_progress.json', 'r', encoding='utf-8', errors='ignore') as f:
        data = json.load(f)

    # 타임스탐프 업데이트
    data['last_updated'] = timestamp_iso

    with open('phase_26_progress.json', 'w', encoding='utf-8', errors='ignore') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 갱신 완료: {timestamp_str}")
except Exception as e:
    print(f"   ❌ 오류: {e}")

print("\n" + "="*80)
print("✅ 모든 타임스탐프 갱신 완료!")
print("="*80 + "\n")
