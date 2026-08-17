#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🤖 자비스 - 이미지 파일 검증\n")
print("=" * 60)

# 1.png ~ 16.png 검증
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        img = Image.open(image_path)

        # 이미지 정보
        mode = img.mode
        size = img.size

        # 알파 채널 확인
        has_alpha = 'A' in mode

        # 투명 픽셀 개수 확인
        if has_alpha:
            pixdata = img.getdata()
            transparent_count = sum(1 for pixel in pixdata if pixel[3] < 128)
            percentage = (transparent_count / len(list(pixdata))) * 100
            print(f"✅ {i}.png | 모드: {mode} | 투명: {percentage:.1f}%")
        else:
            print(f"⚠️  {i}.png | 모드: {mode} (알파 채널 없음!)")

    except Exception as e:
        print(f"❌ {i}.png | 오류: {e}")

print("=" * 60)
print("\n✅ 검증 완료!")
