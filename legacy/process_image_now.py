#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
import os
import sys

# 이미지 경로
mascot_path = r"C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png"

print("🐕 배경 제거 처리 중...")

try:
    # 이미지 로드
    img = Image.open(mascot_path)
    print(f"✅ 로드 - 모드: {img.mode}, 크기: {img.size}")

    # RGBA로 변환
    img = img.convert('RGBA')

    # NumPy 배열로 변환
    data = np.array(img)

    # 흰색 배경 감지 (R>200, G>200, B>200) - 밝은 색 모두 포함
    white_mask = (data[:,:,0] > 200) & (data[:,:,1] > 200) & (data[:,:,2] > 200)

    # 알파 채널 투명화
    data[white_mask, 3] = 0

    # 이미지로 변환 후 저장
    result = Image.fromarray(data, 'RGBA')
    result.save(mascot_path, 'PNG')

    print(f"✨ 완료!")
    print(f"📊 {np.sum(white_mask):,}개 픽셀 투명화됨")
    print(f"📁 저장됨: {mascot_path}")

except Exception as e:
    print(f"❌ 오류: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
