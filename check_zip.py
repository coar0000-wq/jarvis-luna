#!/usr/bin/env python3
import zipfile
import os

files = [
    r"C:\Users\Desktop\Claude\Projects\kms\stuffed-dog-digital-clone.zip",
    r"C:\Users\Desktop\Claude\Projects\kms\stuffed-dog-digital-1to1-style-v2.zip"
]

for filepath in files:
    if os.path.exists(filepath):
        print(f"\n{'='*60}")
        print(f"📦 파일: {os.path.basename(filepath)}")
        print(f"{'='*60}")

        try:
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                print(f"총 파일 개수: {len(file_list)}")
                print(f"\n📋 파일 목록 (처음 30개):")
                for i, name in enumerate(file_list[:30], 1):
                    size = zip_ref.getinfo(name).file_size
                    print(f"  {i:2}. {name} ({size:,} bytes)")

                if len(file_list) > 30:
                    print(f"\n  ... 그 외 {len(file_list)-30}개 파일")

        except Exception as e:
            print(f"❌ 에러: {e}")
    else:
        print(f"⚠️  파일을 찾을 수 없음: {filepath}")
