#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")
mascot_path = os.path.join(images_dir, "mascot-main.png")

print("🐕 개 캐릭터 배경 제거 시작...")

if not os.path.exists(mascot_path):
    print(f"❌ 파일 없음: {mascot_path}")
    exit(1)

# 이미지 로드
img = Image.open(mascot_path)
print(f"✅ 로드 - 모드: {img.mode}, 크기: {img.size}")

# RGBA로 변환
img = img.convert('RGBA')

# NumPy 배열로 변환
data = np.array(img)

# 흰색 배경 감지 및 투명화
# 흰색 범위: R>200, G>200, B>200
white_mask = (data[:,:,0] > 200) & (data[:,:,1] > 200) & (data[:,:,2] > 200)

# 알파 채널 수정
data[white_mask, 3] = 0

# 이미지로 변환 후 저장
result = Image.fromarray(data, 'RGBA')
result.save(mascot_path, 'PNG')

print(f"✨ 완료! 흰색 {np.sum(white_mask):,}개 픽셀 투명화됨")
print(f"📁 저장: {mascot_path}")
