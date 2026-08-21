#!/usr/bin/env python3
import zipfile
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"

# 첫 번째 프로젝트 분석
zip_path = os.path.join(base_dir, "stuffed-dog-digital-clone.zip")

print("=" * 80)
print("📦 stuffed-dog-digital-clone.zip 분석")
print("=" * 80)

with zipfile.ZipFile(zip_path, 'r') as z:
    all_files = sorted(z.namelist())

    # HTML 파일 찾기
    html_files = [f for f in all_files if f.endswith('.html')]
    css_files = [f for f in all_files if f.endswith('.css')]

    print(f"\n🌐 HTML 파일 ({len(html_files)}):")
    for f in html_files:
        print(f"  - {f}")

    print(f"\n🎨 CSS 파일 ({len(css_files)}):")
    for f in css_files:
        print(f"  - {f}")

    # index.html 읽기
    if html_files:
        main_html = html_files[0]
        print(f"\n📄 {main_html} 크기: {z.getinfo(main_html).file_size} bytes")

        try:
            content = z.read(main_html).decode('utf-8')
            print(f"\n📋 HTML 내용 (처음 500자):")
            print(content[:500])
        except:
            print("❌ HTML 읽기 실패")

print("\n" + "=" * 80)
print("📦 stuffed-dog-digital-1to1-style-v2.zip 분석")
print("=" * 80)

zip_path2 = os.path.join(base_dir, "stuffed-dog-digital-1to1-style-v2.zip")

with zipfile.ZipFile(zip_path2, 'r') as z:
    all_files = sorted(z.namelist())

    html_files = [f for f in all_files if f.endswith('.html')]
    css_files = [f for f in all_files if f.endswith('.css')]

    print(f"\n🌐 HTML 파일 ({len(html_files)}):")
    for f in html_files[:5]:
        print(f"  - {f}")

    print(f"\n🎨 CSS 파일 ({len(css_files)}):")
    for f in css_files[:5]:
        print(f"  - {f}")

print("\n✨ 분석 완료!")
