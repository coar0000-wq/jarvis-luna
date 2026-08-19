#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os
from pathlib import Path

# 이미지 디렉토리
images_dir = r"C:\Users\Desktop\Claude\Projects\kms\images"
background_color = (255, 255, 255, 0)  # 투명 배경

# 1번부터 16번까지만 처리
target_nums = list(range(1, 17))

# 1번 이미지 크기 확인
img_1_path = os.path.join(images_dir, "1.png")
if not os.path.exists(img_1_path):
    print(f"❌ 1.png를 찾을 수 없습니다: {img_1_path}")
    exit(1)

img_1 = Image.open(img_1_path)
print(f"✅ 1번 이미지 원본 크기: {img_1.width}×{img_1.height}")

# 1번 이미지를 기준으로 모든 이미지 리사이징
target_size = (img_1.width, img_1.height)
print(f"📌 목표 크기: {target_size[0]}×{target_size[1]}")
print()

count = 0
for num in target_nums:
    file_path = os.path.join(images_dir, f"{num}.png")

    if not os.path.exists(file_path):
        print(f"⚠️  {num:2d}번: 파일 없음")
        continue

    try:
        # 원본 이미지 열기
        img = Image.open(file_path)
        original_size = (img.width, img.height)

        # RGBA로 변환
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        # 원본 비율 유지하면서 리사이징
        img.thumbnail(target_size, Image.Resampling.LANCZOS)

        # 새로운 정사각형 이미지 생성 (투명한 배경)
        square_img = Image.new('RGBA', target_size, background_color)

        # 중앙에 배치
        offset_x = (target_size[0] - img.width) // 2
        offset_y = (target_size[1] - img.height) // 2
        square_img.paste(img, (offset_x, offset_y), img)

        # PNG로 저장
        square_img.save(file_path, 'PNG')

        print(f"✅ {num:2d}번 | 원본: {original_size[0]:4}×{original_size[1]:<4} → 목표: {target_size[0]}×{target_size[1]}")
        count += 1

    except Exception as e:
        print(f"❌ {num:2d}번: {e}")

print(f"\n🎉 총 {count}개 이미지 처리 완료!")
print(f"   모든 이미지가 {target_size[0]}×{target_size[1]} 크기로 통일되었습니다.")
