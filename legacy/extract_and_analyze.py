#!/usr/bin/env python3
import zipfile
import os
import json

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
zip_files = [
    "stuffed-dog-digital-clone.zip",
    "stuffed-dog-digital-1to1-style-v2.zip"
]

for zip_name in zip_files:
    zip_path = os.path.join(base_dir, zip_name)
    extract_dir = os.path.join(base_dir, zip_name.replace('.zip', ''))

    if os.path.exists(zip_path):
        print(f"\n{'='*70}")
        print(f"📦 압축 해제 중: {zip_name}")
        print(f"{'='*70}")

        try:
            # 압축 해제
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            print(f"✅ 압축 해제 완료: {extract_dir}")

            # 폴더 구조 출력
            print(f"\n📋 폴더 구조:")
            for root, dirs, files in os.walk(extract_dir):
                level = root.replace(extract_dir, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f'{indent}{os.path.basename(root)}/')
                subindent = ' ' * 2 * (level + 1)
                for file in files[:10]:  # 처음 10개만
                    print(f'{subindent}{file}')
                if len(files) > 10:
                    print(f'{subindent}... 외 {len(files)-10}개 파일')

        except Exception as e:
            print(f"❌ 에러: {e}")
    else:
        print(f"⚠️ 파일을 찾을 수 없음: {zip_path}")
