#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os
from pathlib import Path

# 이미지 디렉토리
images_dir = r"C:\Users\Desktop\Claude\Projects\kms\images"
target_size = (800, 800)
background_color = (255, 255, 255)  # 흰색 배경

# 이미지 확장자
image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}

count = 0
for file in Path(images_dir).iterdir():
    if file.suffix.lower() in image_extensions and file.is_file():
        # 폴더 제외
        if 'files' in str(file):
            continue

        try:
            # 원본 이미지 열기
            img = Image.open(file)

            # RGBA가 아니면 변환
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            # 새로운 정사각형 이미지 생성 (투명한 배경)
            square_img = Image.new('RGBA', target_size, (255, 255, 255, 0))

            # 원본 이미지의 비율 유지하면서 리사이징
            img.thumbnail(target_size, Image.Resampling.LANCZOS)

            # 중앙에 배치
            offset_x = (target_size[0] - img.width) // 2
            offset_y = (target_size[1] - img.height) // 2
            square_img.paste(img, (offset_x, offset_y), img)

            # PNG로 저장 (투명도 유지)
            output_path = file.with_suffix('.png')
            square_img.save(output_path, 'PNG')

            print(f"✅ {file.name} → {output_path.name} (800×800)")
            count += 1

        except Exception as e:
            print(f"❌ {file.name}: {e}")

print(f"\n🎉 총 {count}개 이미지 처리 완료!")
