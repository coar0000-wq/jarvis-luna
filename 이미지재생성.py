#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import shutil
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 자비스 - mascot-1.png를 사용해서 1.png ~ 16.png 생성\n")

# mascot-1.png를 1.png로 복사
src = os.path.join(images_dir, "mascot-1.png")

if not os.path.exists(src):
    print(f"❌ mascot-1.png 없음")
else:
    # 1.png ~ 16.png 생성
    for i in range(1, 17):
        dst = os.path.join(images_dir, f"{i}.png")
        try:
            shutil.copy2(src, dst)
            print(f"✅ {i}.png 생성 완료")
        except Exception as e:
            print(f"❌ {i}.png 생성 실패: {e}")

print("\n" + "=" * 60)
print("✨ 이미지 생성 완료!")
print("=" * 60)
print("\nlocalhost:5000 새로고침! (Ctrl+Shift+Delete 후 F5)")
