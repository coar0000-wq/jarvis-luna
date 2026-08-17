#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

# rembg 설치 확인
try:
    from rembg import remove
    from PIL import Image
    import io
except ImportError:
    print("🔧 필요한 라이브러리 설치 중...")
    os.system("pip install rembg pillow -q")
    from rembg import remove
    from PIL import Image
    import io

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 AI 기반 배경 제거 시작...\n")

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        print(f"🔄 {i}.png 처리 중...")

        # 이미지 로드
        input_img = Image.open(image_path)

        # rembg로 배경 제거
        output_img = remove(input_img)

        # RGBA로 변환 후 저장
        if output_img.mode != 'RGBA':
            output_img = output_img.convert('RGBA')

        output_img.save(image_path, 'PNG')
        print(f"✅ {i}.png 완료!\n")

    except Exception as e:
        print(f"❌ {i}.png 오류: {e}\n")

print("=" * 50)
print("✨ 모든 이미지 배경 제거 완료!")
print("=" * 50)
