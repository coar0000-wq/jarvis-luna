#!/usr/bin/env python3
import zipfile
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
zip_files = [
    "stuffed-dog-digital-clone.zip",
    "stuffed-dog-digital-1to1-style-v2.zip"
]

for zip_name in zip_files:
    zip_path = os.path.join(base_dir, zip_name)

    if os.path.exists(zip_path):
        print(f"\n{'='*70}")
        print(f"📦 {zip_name}")
        print(f"{'='*70}")

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            files = zip_ref.namelist()

            # 파일 타입별 분류
            html_files = [f for f in files if f.endswith('.html')]
            css_files = [f for f in files if f.endswith('.css')]
            js_files = [f for f in files if f.endswith('.js')]
            img_files = [f for f in files if f.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'))]
            other_files = [f for f in files if f.endswith(('.md', '.json', '.txt', '.yml', '.yaml'))]

            print(f"\n📊 파일 요약:")
            print(f"  총 파일: {len(files)}")
            print(f"  HTML: {len(html_files)}")
            print(f"  CSS: {len(css_files)}")
            print(f"  JavaScript: {len(js_files)}")
            print(f"  이미지: {len(img_files)}")
            print(f"  기타: {len(other_files)}")

            if html_files:
                print(f"\n🌐 HTML 파일:")
                for f in html_files[:5]:
                    print(f"  - {f}")

            if css_files:
                print(f"\n🎨 CSS 파일:")
                for f in css_files[:5]:
                    print(f"  - {f}")

            if js_files:
                print(f"\n⚙️ JavaScript 파일:")
                for f in js_files[:5]:
                    print(f"  - {f}")

            if img_files:
                print(f"\n🖼️ 이미지 파일 (처음 10개):")
                for f in img_files[:10]:
                    print(f"  - {f}")

            print(f"\n📄 전체 파일 목록:")
            for f in sorted(files)[:30]:
                print(f"  - {f}")

            if len(files) > 30:
                print(f"  ... 외 {len(files)-30}개 파일")
