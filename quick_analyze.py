#!/usr/bin/env python3
"""
두 개의 ZIP 파일에서 주요 HTML/CSS/이미지 파일을 빠르게 분석
"""
import zipfile
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
zips = {
    "clone": "stuffed-dog-digital-clone.zip",
    "v2": "stuffed-dog-digital-1to1-style-v2.zip"
}

results = {}

for name, zip_file in zips.items():
    zip_path = os.path.join(base_dir, zip_file)

    if not os.path.exists(zip_path):
        continue

    with zipfile.ZipFile(zip_path, 'r') as z:
        all_files = z.namelist()

        # 주요 파일 필터링
        html_files = [f for f in all_files if f.endswith('.html')]
        css_files = [f for f in all_files if f.endswith('.css')]
        js_files = [f for f in all_files if f.endswith('.js')]
        imgs = [f for f in all_files if f.endswith(('.png', '.jpg', '.jpeg', '.svg', '.webp'))]

        results[name] = {
            'total': len(all_files),
            'html': html_files,
            'css': css_files,
            'js': js_files,
            'images': len(imgs),
            'all_files': sorted(all_files)
        }

# 출력
import json
print(json.dumps(results, indent=2, ensure_ascii=False))
