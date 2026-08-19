#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import base64
import re
from pathlib import Path

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 MHTML 파일에서 이미지 추출 중\n")

# 1.mhtml ~ 16.mhtml 처리
for i in range(1, 17):
    mhtml_path = os.path.join(images_dir, f"{i}.mhtml")

    if not os.path.exists(mhtml_path):
        print(f"⚠️  {i}.mhtml 없음")
        continue

    try:
        print(f"🔄 {i}.mhtml 분석 중... ", end="")

        # MHTML 파일 읽기
        with open(mhtml_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # base64 이미지 찾기 (PNG)
        # data:image/png;base64, 패턴 찾기
        pattern = r'data:image/(png|jpeg|jpg);base64,([A-Za-z0-9+/=]+)'
        matches = re.findall(pattern, content)

        if matches:
            # 가장 큰 이미지 선택 (도그 이미지일 가능성 높음)
            largest_match = max(matches, key=lambda x: len(x[1]))
            mime_type, base64_data = largest_match

            # Base64 디코딩
            try:
                image_data = base64.b64decode(base64_data)

                # 이미지 저장
                ext = 'png' if mime_type == 'png' else 'jpg'
                output_path = os.path.join(images_dir, f"{i}.png")

                with open(output_path, 'wb') as img_file:
                    img_file.write(image_data)

                print(f"✅ {len(image_data)} bytes 저장")

            except Exception as e:
                print(f"❌ 디코딩 실패: {e}")
        else:
            print(f"⚠️  이미지 없음")

    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 60)
print("✨ 이미지 추출 완료!")
print("=" * 60)
print("\nlocalhost:8000 새로고침하세요! (Ctrl+Shift+Delete 후)")
