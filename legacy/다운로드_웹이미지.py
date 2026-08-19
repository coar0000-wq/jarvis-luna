#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
from urllib.parse import urljoin
import os

# Stuffed Dog Digital 웹사이트
base_url = "https://stuffeddogdigital.com"

# 이미지 저장 경로
images_dir = r"C:\Users\Desktop\Claude\Projects\kms\images"

print("🐕 Stuffed Dog Digital에서 이미지 다운로드 중...\n")

# 가능한 이미지 경로들 (일반적인 WordPress 패턴)
image_urls = [
    # 가능한 CDN/서버 경로
    f"{base_url}/wp-content/uploads/2024/01/dog-pose-",
    f"{base_url}/wp-content/uploads/images/pose-",
    f"{base_url}/images/pose-",
    f"{base_url}/assets/images/dog-",
]

# 또는 메인 페이지에서 이미지 추출
try:
    print("🔍 웹사이트 분석 중...")
    response = requests.get(base_url, timeout=10)
    response.encoding = 'utf-8'

    # img 태그 찾기
    import re
    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
    matches = re.findall(img_pattern, response.text)

    print(f"✅ {len(matches)}개 이미지 태그 발견\n")

    # 도그 관련 이미지 필터링
    dog_images = [img for img in matches if 'dog' in img.lower() or 'mascot' in img.lower() or 'pose' in img.lower()]

    print(f"🐕 도그 이미지: {len(dog_images)}개\n")

    for idx, img_url in enumerate(dog_images[:16], 1):
        # 절대 URL로 변환
        if img_url.startswith('/'):
            full_url = urljoin(base_url, img_url)
        elif not img_url.startswith('http'):
            full_url = urljoin(base_url, img_url)
        else:
            full_url = img_url

        try:
            print(f"📥 다운로드 {idx}: {full_url[:80]}...")
            img_response = requests.get(full_url, timeout=10)

            # 파일 저장
            file_path = os.path.join(images_dir, f"{idx}.png")
            with open(file_path, 'wb') as f:
                f.write(img_response.content)

            print(f"   ✅ {idx}.png 저장 완료")
        except Exception as e:
            print(f"   ❌ 실패: {e}")

except Exception as e:
    print(f"❌ 웹사이트 접근 실패: {e}")
    print("\n다른 방법 시도: 직접 URL 사용...")

    # 백업: 일반적인 이미지 URL 패턴 시도
    for i in range(1, 17):
        urls_to_try = [
            f"{base_url}/wp-content/uploads/2024/01/mascot-pose-{i}.png",
            f"{base_url}/wp-content/uploads/2024/01/dog-pose-{i}.png",
            f"{base_url}/images/poses/pose-{i}.png",
        ]

        for url in urls_to_try:
            try:
                print(f"📥 시도 {i}: {url[:80]}...")
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    file_path = os.path.join(images_dir, f"{i}.png")
                    with open(file_path, 'wb') as f:
                        f.write(response.content)
                    print(f"   ✅ {i}.png 저장 완료")
                    break
            except:
                pass

print("\n" + "=" * 60)
print("✨ 다운로드 완료!")
print("=" * 60)
