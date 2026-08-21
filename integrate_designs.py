#!/usr/bin/env python3
"""
Stuffed Dog Digital 디자인을 JARVIS LUNA에 통합
"""
import zipfile
import os
import shutil

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"

# 1. ZIP 파일 추출
print("=" * 70)
print("📦 ZIP 파일 추출 중...")
print("=" * 70)

for zip_name in ["stuffed-dog-digital-clone.zip", "stuffed-dog-digital-1to1-style-v2.zip"]:
    zip_path = os.path.join(base_dir, zip_name)
    extract_dir = os.path.join(base_dir, zip_name.replace('.zip', ''))

    if os.path.exists(zip_path):
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)

        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_dir)
            print(f"✅ {zip_name}")
        except Exception as e:
            print(f"❌ {zip_name}: {e}")

# 2. 폴더 구조 분석
print("\n" + "=" * 70)
print("📋 폴더 구조 분석")
print("=" * 70)

for folder_name in ["stuffed-dog-digital-clone", "stuffed-dog-digital-1to1-style-v2"]:
    folder_path = os.path.join(base_dir, folder_name)

    if os.path.exists(folder_path):
        print(f"\n📂 {folder_name}/")

        for root, dirs, files in os.walk(folder_path):
            level = root.replace(folder_path, '').count(os.sep)
            indent = "  " * (level + 1)

            # 폴더 출력
            for dir_name in sorted(dirs):
                print(f"{indent}📁 {dir_name}/")

            # 파일 출력
            for file_name in sorted(files):
                file_path = os.path.join(root, file_name)
                file_size = os.path.getsize(file_path)

                if file_name.endswith(('.html', '.css', '.js', '.json', '.md')):
                    icon = "🌐" if file_name.endswith('.html') else "🎨" if file_name.endswith('.css') else "⚙️"
                    print(f"{indent}{icon} {file_name} ({file_size:,}B)")

print("\n✨ 분석 완료!")
print(f"\n💡 다음 단계: 각 프로젝트의 index.html과 스타일을 검토하세요.")
