#!/usr/bin/env python3
"""
Stuffed Dog Digital + JARVIS LUNA 디자인 병합
"""
import zipfile
import os
import re

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"

# Step 1: clone 프로젝트에서 HTML/CSS 추출
print("🔍 Stuffed Dog Digital 디자인 추출 중...")

zip_path = os.path.join(base_dir, "stuffed-dog-digital-clone.zip")
html_content = None
css_content = None

with zipfile.ZipFile(zip_path, 'r') as z:
    all_files = z.namelist()

    # index.html 찾기
    html_candidates = [f for f in all_files if 'index.html' in f.lower()]
    if not html_candidates:
        html_candidates = [f for f in all_files if f.endswith('.html')]

    # CSS 찾기
    css_files = [f for f in all_files if f.endswith('.css')]

    if html_candidates:
        try:
            html_content = z.read(html_candidates[0]).decode('utf-8')
            print(f"✅ HTML 추출: {html_candidates[0]}")
        except Exception as e:
            print(f"⚠️ HTML 읽기 실패: {e}")

    if css_files:
        try:
            css_content = z.read(css_files[0]).decode('utf-8')
            print(f"✅ CSS 추출: {css_files[0]}")
        except Exception as e:
            print(f"⚠️ CSS 읽기 실패: {e}")

# Step 2: 색상 추출
print("\n🎨 디자인 요소 분석...")

colors_found = {}
if html_content:
    # 색상 코드 찾기
    color_matches = re.findall(r'#[0-9a-fA-F]{6}|rgb\([^)]+\)', html_content)
    if color_matches:
        colors_found['html'] = list(set(color_matches))[:5]
        print(f"  HTML 색상: {colors_found['html']}")

if css_content:
    color_matches = re.findall(r'#[0-9a-fA-F]{6}|rgb\([^)]+\)', css_content)
    if color_matches:
        colors_found['css'] = list(set(color_matches))[:5]
        print(f"  CSS 색상: {colors_found['css']}")

# Step 3: 현재 JARVIS index.html 읽기
jarvis_path = os.path.join(base_dir, "index.html")
with open(jarvis_path, 'r', encoding='utf-8') as f:
    jarvis_html = f.read()

print(f"\n📖 현재 JARVIS LUNA: {len(jarvis_html)} bytes")

# Step 4: 스타일 강화 버전 생성
print("\n✨ JARVIS LUNA 디자인 강화 중...")

# 새로운 색상 변수 추가
new_style = """
        /* Stuffed Dog Digital 통합 디자인 */
        :root {
            --bg-dark: #0a0e27;
            --bg-darker: #050810;
            --bg-card: #0f1535;
            --color-primary: #64e5ff;
            --color-accent: #ff6b35;
            --color-text: #ffffff;
            --color-text-muted: #888888;
            --border-color: rgba(100, 229, 255, 0.1);
            /* 새로운 강화 색상 */
            --color-secondary: #00d4ff;
            --color-tertiary: #ff8c42;
            --shadow-glow: 0 0 20px rgba(100, 229, 255, 0.3);
        }
"""

# 기존 :root 찾아서 교체
if ':root' in jarvis_html:
    old_root = re.search(r':root\s*\{[^}]+\}', jarvis_html, re.DOTALL)
    if old_root:
        jarvis_html = jarvis_html.replace(old_root.group(0), new_style)
        print("✅ CSS 변수 업데이트")

# 카드 hover 효과 강화
hover_effect = """
        .feature-card:hover {
            background: linear-gradient(135deg, rgba(100, 229, 255, 0.1) 0%, rgba(255, 107, 53, 0.1) 100%);
            border-color: rgba(100, 229, 255, 0.5);
            transform: translateY(-15px);
            box-shadow: var(--shadow-glow);
        }
"""

if '.feature-card:hover' in jarvis_html:
    old_hover = re.search(r'\.feature-card:hover\s*\{[^}]+\}', jarvis_html, re.DOTALL)
    if old_hover:
        jarvis_html = jarvis_html.replace(old_hover.group(0), hover_effect)
        print("✅ Hover 효과 강화")

# 메트릭 카드 애니메이션 추가
animation = """
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.8; transform: scale(1.02); }
        }

        .metric-card {
            animation: pulse 3s ease-in-out infinite;
        }
"""

if '@keyframes bounce' in jarvis_html:
    # bounce 애니메이션 뒤에 추가
    jarvis_html = jarvis_html.replace('@keyframes bounce', animation + '\n        @keyframes bounce')
    print("✅ 펄스 애니메이션 추가")

# 저장
output_path = os.path.join(base_dir, "index_enhanced.html")
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(jarvis_html)

print(f"\n✨ 완료!")
print(f"📁 출력: {output_path}")
print(f"📊 크기: {len(jarvis_html)} bytes")
