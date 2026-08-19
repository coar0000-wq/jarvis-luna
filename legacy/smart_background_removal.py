#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import cv2
import numpy as np
from PIL import Image
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🤖 자비스 - 스마트 배경 제거 시작...\n")

success_count = 0
failed_count = 0

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        failed_count += 1
        continue

    try:
        print(f"🔄 {i}.png 처리 중... ", end="")

        # 이미지 로드
        img_bgr = cv2.imread(image_path)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        # HSV로 변환 (색상 범위 감지에 유리)
        img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

        # 배경 색상 범위 정의 (파란색, 회색, 흰색 배경)
        # 1. 파란색 배경 감지 (Stuffed Dog Digital)
        lower_blue = np.array([90, 50, 50])
        upper_blue = np.array([130, 255, 255])
        mask_blue = cv2.inRange(img_hsv, lower_blue, upper_blue)

        # 2. 회색 배경 감지 (낮은 채도)
        lower_gray = np.array([0, 0, 100])
        upper_gray = np.array([180, 50, 255])
        mask_gray = cv2.inRange(img_hsv, lower_gray, upper_gray)

        # 3. 흰색 배경 감지 (높은 명도)
        lower_white = np.array([0, 0, 200])
        upper_white = np.array([180, 30, 255])
        mask_white = cv2.inRange(img_hsv, lower_white, upper_white)

        # 모든 배경 마스크 결합
        background_mask = cv2.bitwise_or(mask_blue, mask_gray)
        background_mask = cv2.bitwise_or(background_mask, mask_white)

        # 모폴로지 연산으로 노이즈 제거
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        background_mask = cv2.morphologyEx(background_mask, cv2.MORPH_CLOSE, kernel)
        background_mask = cv2.morphologyEx(background_mask, cv2.MORPH_OPEN, kernel)

        # 역마스크 (도그 부분만)
        foreground_mask = cv2.bitwise_not(background_mask)

        # RGBA 이미지로 변환
        img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)

        # 알파 채널에 마스크 적용
        b, g, r = cv2.split(img_bgr)
        img_rgba = cv2.merge([b, g, r, foreground_mask])

        # PIL로 변환 후 저장
        img_pil = Image.fromarray(cv2.cvtColor(img_rgba, cv2.COLOR_BGRA2RGBA))
        img_pil.save(image_path, 'PNG')

        print("✅")
        success_count += 1

    except Exception as e:
        print(f"❌ {str(e)[:40]}")
        failed_count += 1

print("\n" + "=" * 60)
print(f"✨ 배경 제거 완료!")
print(f"✅ 성공: {success_count}/16개")
print(f"❌ 실패: {failed_count}/16개")
print("=" * 60)
print("\n💡 이제 localhost:8000을 새로고침(Ctrl+F5)하면")
print("   도그만 깔끔하게 보일 것입니다! 🐕")
