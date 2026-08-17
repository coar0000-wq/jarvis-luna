#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os
from pathlib import Path

# 이미지 디렉토리
images_dir = r"C:\Users\Desktop\Claude\Projects\kms\images"
background_color = (255, 255, 255, 0)  # 투명 배경

# 1번 이미지 크기 확인
img_1 = Image.open(os.path.join(images_dir, "1.png"))
size_1 = (img_1.width, img_1.height)
print(f"1번 이미지 크기: {size_1[0]}×{size_1[1]}")

# 2번부터는 1번의 3배 크기로 확대
size_2plus = (size_1[0] * 3, size_1[1] * 3)
print(f"2번부터 크기: {size_2plus[0]}×{size_2plus[1]} (1번의 3배)")
print()

# 이미지 확장자
image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}

count = 0
for file in sorted(Path(images_dir).iterdir()):
    if file.suffix.lower() in image_extensions and file.is_file():
        # 폴더 제외
        if 'files' in str(file):
            continue

        try:
            # 원본 이미지 열기
            img = Image.open(file)
            original_size = (img.width, img.height)

            # RGBA로 변환
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            # 1번인지 2번 이상인지 확인
            if file.stem == '1':
                # 1번: 원본 크기 유지
                target_size = size_1
                print(f"✅ {file.name:10} | 원본: {original_size[0]:4}×{original_size[1]:<4} → {target_size[0]}×{target_size[1]} (1번)")
            else:
                # 2번부터: 2배 크기로 확대
                target_size = size_2plus
                # 원본 비율 유지하면서 리사이징
                img.thumbnail(target_size, Image.Resampling.LANCZOS)

                # 새로운 이미지 생성 (투명한 배경)
                square_img = Image.new('RGBA', target_size, background_color)

                # 중앙에 배치
                offset_x = (target_size[0] - img.width) // 2
                offset_y = (target_size[1] - img.height) // 2
                square_img.paste(img, (offset_x, offset_y), img)

                # PNG로 저장
                output_path = file.with_suffix('.png')
                square_img.save(output_path, 'PNG')

                print(f"✅ {file.name:10} | 원본: {original_size[0]:4}×{original_size[1]:<4} → {target_size[0]}×{target_size[1]} (2배 확대)")
                count += 1
                continue

            # 1번 이미지 처리
            img.thumbnail(target_size, Image.Resampling.LANCZOS)
            square_img = Image.new('RGBA', target_size, background_color)
            offset_x = (target_size[0] - img.width) // 2
            offset_y = (target_size[1] - img.height) // 2
            square_img.paste(img, (offset_x, offset_y), img)
            output_path = file.with_suffix('.png')
            square_img.save(output_path, 'PNG')
            count += 1

        except Exception as e:
            print(f"❌ {file.name}: {e}")

print(f"\n🎉 총 {count}개 이미지 처리 완료!")
print(f"   • 1번: {size_1[0]}×{size_1[1]}")
print(f"   • 2번~16번: {size_2plus[0]}×{size_2plus[1]} (1번의 2배 크기)")
