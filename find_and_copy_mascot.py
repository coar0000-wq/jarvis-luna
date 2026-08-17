#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import zipfile
import os
import shutil
from pathlib import Path

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
zip_path = os.path.join(base_dir, "stuffed-dog-digital-clone.zip")
images_dir = os.path.join(base_dir, "images")
mascot_path = os.path.join(images_dir, "mascot-main.png")

print("🐕 Stuffed Dog Digital에서 개 캐릭터 이미지 찾기...")

# 이미지 폴더 생성
os.makedirs(images_dir, exist_ok=True)

# ZIP 파일에서 이미지 추출
with zipfile.ZipFile(zip_path, 'r') as z:
    all_files = z.namelist()

    # 개 캐릭터 이미지 찾기 (이름에 dog, character, mascot, render 포함)
    dog_keywords = ['dog', 'character', 'mascot', 'render', 'hero']
    png_files = [f for f in all_files if f.lower().endswith('.png')]

    print(f"\n총 PNG 파일: {len(png_files)}개")

    # 후보 이미지 찾기
    candidates = []
    for f in png_files:
        filename_lower = f.lower()
        if any(keyword in filename_lower for keyword in dog_keywords):
            candidates.append(f)

    if candidates:
        print(f"✅ 개 캐릭터 후보: {len(candidates)}개")

        # 가장 가능성 높은 이미지 선택 (파일 크기 순)
        best_candidate = None
        max_size = 0

        for candidate in candidates:
            file_info = z.getinfo(candidate)
            if file_info.file_size > max_size and file_info.file_size < 10000000:  # 10MB 이하
                max_size = file_info.file_size
                best_candidate = candidate

        if best_candidate:
            print(f"\n🎯 선택된 이미지: {best_candidate}")
            print(f"   크기: {max_size / 1024:.1f} KB")

            # 이미지 추출
            with z.open(best_candidate) as source:
                with open(mascot_path, 'wb') as target:
                    shutil.copyfileobj(source, target)

            print(f"\n✨ 완료! 저장 위치: {mascot_path}")
            print(f"📊 파일 크기: {os.path.getsize(mascot_path) / 1024:.1f} KB")
        else:
            print("❌ 적합한 개 캐릭터 이미지를 찾을 수 없습니다")
    else:
        print("⚠️  개 캐릭터 후보를 찾을 수 없습니다")
        print("\n💡 대신 처음 5개 PNG를 보여드립니다:")
        for i, f in enumerate(png_files[:5], 1):
            print(f"   {i}. {f}")
