#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os

mascot_path = r'C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png'

print(f"처리 시작: {mascot_path}")

# 이미지 로드
img = Image.open(mascot_path)
print(f"원본 이미지 모드: {img.mode}, 크기: {img.size}")

# RGBA로 변환
img = img.convert('RGBA')

# 픽셀 데이터 접근
data = img.getdata()
new_data = []

# 흰색 기준값 설정 (RGB 모두 200 이상)
white_threshold = 200

for item in data:
    # RGBA 튜플
    if len(item) == 4:
        r, g, b, a = item
        if r > white_threshold and g > white_threshold and b > white_threshold:
            # 흰색 -> 투명 처리
            new_data.append((r, g, b, 0))
        else:
            new_data.append(item)
    elif len(item) == 3:
        # RGB 이미지인 경우
        r, g, b = item
        if r > white_threshold and g > white_threshold and b > white_threshold:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, 255))

# 새 이미지 생성
img.putdata(new_data)

# 저장
img.save(mascot_path, 'PNG')
print(f"처리 완료! {mascot_path}")
