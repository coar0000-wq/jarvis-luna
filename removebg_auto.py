#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import os
from PIL import Image
import io

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 Remove.bg 온라인 배경 제거 시작...\n")
print("⚠️  각 이미지마다 처리 중입니다...")
print("=" * 50)

success_count = 0
failed_count = 0

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        failed_count += 1
        continue

    try:
        print(f"\n🔄 {i}.png 처리 중...", end=" ")

        # Remove.bg 무료 API 사용
        with open(image_path, 'rb') as img_file:
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                files={'image_file': img_file},
                data={'size': 'auto', 'type': 'auto'},
                headers={'X-API-Key': 'freeKey'}  # 무료 키
            )

        if response.status_code == 200:
            # 이미지 저장
            output_img = Image.open(io.BytesIO(response.content))
            output_img.save(image_path, 'PNG')
            print("✅ 완료!")
            success_count += 1
        else:
            print(f"❌ API 오류 ({response.status_code})")
            failed_count += 1

    except Exception as e:
        print(f"❌ 오류: {str(e)[:50]}")
        failed_count += 1

print("\n" + "=" * 50)
print(f"✨ 처리 완료!")
print(f"✅ 성공: {success_count}개")
print(f"❌ 실패: {failed_count}개")
print("=" * 50)
