#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 배경을 전부 흰색으로 변경\n")

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        print(f"🔄 {i}.png 처리 중... ", end="")

        # 이미지 로드
        img = Image.open(image_path)
        img_rgb = img.convert('RGB')

        # NumPy 배열로 변환
        img_array = np.array(img_rgb)

        # 흰색 배경 생성
        white_bg = np.full_like(img_array, 255)

        # 도그 색상 범위 감지 (갈색, 검은색, 빨간색)
        r, g, b = img_array[:,:,0], img_array[:,:,1], img_array[:,:,2]

        # 도그인 부분 감지
        is_dog = (
            # 갈색/황색 (도그 모피)
            ((r > 100) & (g > 80) & (b < 100)) |
            # 검은색 (눈, 코)
            ((r < 100) & (g < 100) & (b < 100)) |
            # 빨간색/분홍색 (입, 신발)
            ((r > 150) & (g < 150) & (b < 150)) |
            # 주황색 (도구)
            ((r > 180) & (g > 100) & (b < 100)) |
            # 파란색 (옷)
            ((b > r + 20) & (b > g + 20))
        )

        # 마스크 생성 (도그는 1, 배경은 0)
        mask = np.expand_dims(is_dog, axis=2)

        # 이미지 합성 (도그는 원본, 배경은 흰색)
        result = np.where(mask, img_array, white_bg)

        # PIL로 변환 후 저장
        result_img = Image.fromarray(result.astype('uint8'), 'RGB')
        result_img.save(image_path, 'PNG')

        print("✅")

    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 60)
print("✨ 모든 이미지 배경을 흰색으로 변경 완료!")
print("=" * 60)
print("\nlocalhost:8000 새로고침하세요! (Ctrl+Shift+Delete 후)")
