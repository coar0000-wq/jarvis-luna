#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stuffed Dog Digital ZIP에서 개 캐릭터 이미지 추출 및 복사
"""

import zipfile
import os
from pathlib import Path
import shutil

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
zip_path = os.path.join(base_dir, "stuffed-dog-digital-clone.zip")
extract_dir = os.path.join(base_dir, "stuffed-extracted")
images_dir = os.path.join(base_dir, "images")

# 이미지 폴더 생성
os.makedirs(images_dir, exist_ok=True)

print("=" * 80)
print("🐕 Stuffed Dog Digital 이미지 추출 시작!")
print("=" * 80)

# ZIP 파일 압축 해제
if os.path.exists(zip_path):
    print(f"\n📦 ZIP 파일 추출 중: {zip_path}")

    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_dir)
    print(f"✅ 추출 완료: {extract_dir}")

    # 이미지 파일 찾기
    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')
    image_files = []

    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith(image_extensions):
                full_path = os.path.join(root, file)
                image_files.append(full_path)

    print(f"\n🖼️  찾은 이미지 파일: {len(image_files)}개")

    if image_files:
        # 이미지 미리보기
        print("\n📋 이미지 목록:")
        for i, img in enumerate(image_files[:20], 1):
            print(f"  {i:2d}. {img}")

        if len(image_files) > 20:
            print(f"  ... 외 {len(image_files) - 20}개")

        # 개 캐릭터 이미지 찾기 (파일명에 dog, mascot, character 포함)
        mascot_keywords = ['dog', 'mascot', 'character', 'hero', 'avatar', 'render']
        mascot_images = [
            img for img in image_files
            if any(keyword in img.lower() for keyword in mascot_keywords)
        ]

        if mascot_images:
            print(f"\n🎯 개 캐릭터 이미지 후보: {len(mascot_images)}개")
            for i, img in enumerate(mascot_images, 1):
                print(f"  {i}. {os.path.basename(img)}")
                # 복사
                dest = os.path.join(images_dir, f"mascot-{i}.png")
                if img.lower().endswith('.png') or i == 1:
                    try:
                        shutil.copy2(img, dest)
                        print(f"     ✅ 복사됨: {dest}")
                    except Exception as e:
                        print(f"     ⚠️  복사 실패: {e}")
        else:
            # 키워드 없으면 처음 4개 이미지 사용
            print(f"\n🐕 처음 4개 이미지를 마스코트로 설정...")
            selected_images = image_files[:4]

            for i, img in enumerate(selected_images, 1):
                dest = os.path.join(images_dir, f"mascot-{i}.png")
                try:
                    shutil.copy2(img, dest)
                    print(f"  ✅ mascot-{i}.png: {os.path.basename(img)}")
                except Exception as e:
                    print(f"  ❌ 복사 실패: {e}")

        print(f"\n✨ 완료!")
        print(f"📁 이미지 폴더: {images_dir}")

        # 복사된 파일 확인
        copied_files = os.listdir(images_dir)
        print(f"📊 복사된 파일: {len(copied_files)}개")
        for f in sorted(copied_files):
            if f.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                print(f"   ✅ {f}")

    else:
        print("⚠️  이미지 파일을 찾을 수 없습니다.")

else:
    print(f"❌ ZIP 파일을 찾을 수 없습니다: {zip_path}")

print("\n" + "=" * 80)
