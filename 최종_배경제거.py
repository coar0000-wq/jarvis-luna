#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 최종 배경 제거 - 지능형 색상 범위 감지\n")

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
        img_array = np.array(img.convert('RGB'))

        # 이미지의 모서리 색상 샘플링 (배경이 모서리에 있을 확률 높음)
        edges = []
        edges.extend(img_array[0, :])  # 상단
        edges.extend(img_array[-1, :])  # 하단
        edges.extend(img_array[:, 0])  # 좌측
        edges.extend(img_array[:, -1])  # 우측

        edges = np.array(edges)

        # 가장 흔한 색상 찾기 (배경 색상)
        from scipy.stats import mode
        bg_color = mode(edges.reshape(-1, 3), axis=0).mode[0]

        print(f"\n   배경색: RGB{tuple(bg_color)}", end="")

        # 배경색 ±30 범위의 픽셀을 투명하게
        r, g, b = bg_color
        diff = 40

        mask = (
            (np.abs(img_array[:, :, 0].astype(int) - int(r)) < diff) &
            (np.abs(img_array[:, :, 1].astype(int) - int(g)) < diff) &
            (np.abs(img_array[:, :, 2].astype(int) - int(b)) < diff)
        )

        # RGBA로 변환
        img_rgba = img.convert('RGBA')
        data = np.array(img_rgba)

        # 배경 투명화
        data[mask, 3] = 0

        # 저장
        result_img = Image.fromarray(data, 'RGBA')
        result_img.save(image_path)

        print(" ✅")

    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 60)
print("✨ 배경 제거 완료! (투명 PNG)")
print("=" * 60)
print("\nlocalhost:8000 새로고침하세요! (Ctrl+Shift+Delete 후)")
