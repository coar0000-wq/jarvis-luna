#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import shutil
import os

# 경로 설정
uploads_dir = r"C:\Users\Desktop\AppData\Roaming\Claude\local-agent-mode-sessions\ab2eb384-63dc-4ae8-905a-71460e9ab5d4\f0933c22-8c2d-42bf-80b4-5a7cd933feaf\local_062e88da-5cc1-4a51-a825-03661f67e32c\uploads"
images_dir = r"C:\Users\Desktop\Claude\Projects\kms\images"

print("🐕 업로드된 이미지 복사 시작\n")

# 1.png ~ 16.png 복사
for i in range(1, 17):
    src = os.path.join(uploads_dir, f"{i}.png")
    dst = os.path.join(images_dir, f"{i}.png")

    if os.path.exists(src):
        try:
            shutil.copy2(src, dst)
            print(f"✅ {i}.png 복사 완료")
        except Exception as e:
            print(f"❌ {i}.png 복사 실패: {e}")
    else:
        print(f"⚠️  {i}.png 없음 (uploads)")

print("\n" + "=" * 60)
print("✨ 모든 이미지 복사 완료!")
print("=" * 60)
print("\nlocalhost:8000 새로고침하세요! (Ctrl+Shift+Delete 후)")
