#!/usr/bin/env python3
"""
Stuffed Dog Digital 디자인 자동 통합
"""
import zipfile
import os
import shutil
import re

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"

# Step 1: ZIP 파일 추출
print("=" * 80)
print("🔄 Step 1: ZIP 파일 압축 해제")
print("=" * 80)

for zip_name in ["stuffed-dog-digital-clone.zip", "stuffed-dog-digital-1to1-style-v2.zip"]:
    zip_path = os.path.join(base_dir, zip_name)
    extract_dir = os.path.join(base_dir, zip_name.replace('.zip', ''))

    if os.path.exists(zip_path):
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)

        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(extract_dir)
        print(f"✅ {zip_name}")

# Step 2: 주요 파일 찾기
print("\n" + "=" * 80)
print("🔍 Step 2: 주요 파일 분석")
print("=" * 80)

def find_html_css(directory):
    """HTML과 CSS 파일 찾기"""
    html_files = []
    css_files = []

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.html'):
                html_files.append(os.path.join(root, file))
            elif file.endswith('.css'):
                css_files.append(os.path.join(root, file))

    return html_files, css_files

designs = {}

for project in ["stuffed-dog-digital-clone", "stuffed-dog-digital-1to1-style-v2"]:
    project_path = os.path.join(base_dir, project)

    if os.path.exists(project_path):
        html_files, css_files = find_html_css(project_path)
        designs[project] = {
            'html': html_files,
            'css': css_files,
            'path': project_path
        }
        print(f"\n📁 {project}:")
        print(f"  HTML: {len(html_files)} 파일")
        print(f"  CSS: {len(css_files)} 파일")

# Step 3: 색상 팔레트 추출
print("\n" + "=" * 80)
print("🎨 Step 3: 색상 팔레트 분석")
print("=" * 80)

def extract_colors(css_content):
    """CSS에서 색상 추출"""
    color_pattern = r'#[0-9a-fA-F]{6}|rgb\([^)]+\)|rgba\([^)]+\)'
    colors = set(re.findall(color_pattern, css_content))
    return colors

all_colors = {}

for project_name, project_data in designs.items():
    project_colors = set()

    for css_file in project_data['css']:
        try:
            with open(css_file, 'r', encoding='utf-8') as f:
                content = f.read()
                colors = extract_colors(content)
                project_colors.update(colors)
        except:
            pass

    all_colors[project_name] = list(project_colors)[:10]  # 상위 10개
    print(f"\n{project_name}:")
    for color in all_colors[project_name]:
        print(f"  • {color}")

# Step 4: 현재 JARVIS 색상
print("\n" + "=" * 80)
print("🎯 Step 4: JARVIS LUNA 현재 설정")
print("=" * 80)

jarvis_colors = {
    'bg-dark': '#0a0e27',
    'bg-darker': '#050810',
    'color-primary': '#64e5ff',
    'color-accent': '#ff6b35',
    'text': '#ffffff',
    'text-muted': '#888888'
}

print("\n현재 색상:")
for key, color in jarvis_colors.items():
    print(f"  {key}: {color}")

print("\n✨ 분석 완료!")
print("\n💡 다음: index.html 업데이트 준비...")
