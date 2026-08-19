#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 16개 이미지 배경 제거 시작...\n")

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        # 이미지 로드
        img = Image.open(image_path)
        print(f"🔄 {i}.png 처리 중... ({img.size})")

        # RGBA로 변환
        img = img.convert('RGBA')
        data = np.array(img)

        # 흰색/밝은색 배경 감지 (R>220, G>220, B>220)
        # 공과 배경을 구분하기 위해 높은 임계값 사용
        white_mask = (data[:,:,0] > 220) & (data[:,:,1] > 220) & (data[:,:,2] > 220)

        # 밝은 회색 배경도 제거 (무채색, 모두 유사한 값)
        gray_mask = (
            (np.abs(data[:,:,0].astype(int) - data[:,:,1].astype(int)) < 30) &
            (np.abs(data[:,:,1].astype(int) - data[:,:,2].astype(int)) < 30) &
            (data[:,:,0] > 180)
        )

        # 청색 배경 제거 (Stuffed Dog Digital의 파란 배경)
        blue_bg_mask = (
            (data[:,:,0] < 150) &  # R 낮음
            (data[:,:,1] > 150) & (data[:,:,1] < 200) &  # G 중간
            (data[:,:,2] > 150)    # B 높음
        )

        # 모든 배경 마스크 결합
        background_mask = white_mask | gray_mask | blue_bg_mask

        # 알파 채널 투명화
        data[background_mask, 3] = 0

        # 이미지로 변환 후 저장
        result = Image.fromarray(data, 'RGBA')
        result.save(image_path, 'PNG')

        removed_pixels = np.sum(background_mask)
        print(f"✅ {i}.png 완료! ({removed_pixels:,}개 픽셀 투명화)\n")

    except Exception as e:
        print(f"❌ {i}.png 오류: {e}\n")

print("=" * 50)
print("✨ 모든 이미지 배경 제거 완료!")
print("=" * 50)
