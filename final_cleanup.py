#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 최종 배경 제거 - 흰색만 투명화\n")

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        print(f"🔄 {i}.png 처리 중... ", end="")

        # 이미지 열기
        img = Image.open(image_path)

        # RGBA로 변환
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        # 픽셀 데이터 가져오기
        pixdata = img.getdata()

        # 새 픽셀 리스트
        new_pixdata = []

        # 흰색(255,255,255)과 밝은 회색, 파란색 배경만 투명화
        for pixel in pixdata:
            r, g, b = pixel[0], pixel[1], pixel[2]

            # 흰색 배경 (R>240, G>240, B>240)
            if r > 240 and g > 240 and b > 240:
                new_pixdata.append((r, g, b, 0))  # 투명
            # 밝은 회색 배경
            elif r > 200 and g > 200 and b > 200 and abs(r-g) < 20 and abs(g-b) < 20:
                new_pixdata.append((r, g, b, 0))  # 투명
            # 파란 배경
            elif b > r + 30 and b > g + 30 and r < 180:
                new_pixdata.append((r, g, b, 0))  # 투명
            else:
                new_pixdata.append(pixel)  # 그대로

        # 이미지에 적용
        img.putdata(new_pixdata)

        # 저장
        img.save(image_path, 'PNG')
        print("✅")

    except Exception as e:
        print(f"❌ {e}")

print("\n✨ 완료! localhost:8000 새로고침하세요 (Ctrl+Shift+Delete 캐시 삭제 후)")
