#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import cv2
import numpy as np
from PIL import Image
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 공격적인 배경 제거 - 도그만 남기고 나머지 전부 흰색\n")

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        print(f"🔄 {i}.png 처리 중... ", end="")

        # OpenCV로 로드 (BGR)
        img = cv2.imread(image_path)
        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 1. 파란색 배경 범위 (INSIDE 텍스트가 있는 파란색)
        blue_lower = np.array([90, 50, 50])
        blue_upper = np.array([130, 255, 255])
        blue_mask = cv2.inRange(img_hsv, blue_lower, blue_upper)

        # 2. 밝은 색상 범위 (화이트/연한 색)
        # HSV에서 명도가 높은 것들
        light_lower = np.array([0, 0, 200])
        light_upper = np.array([180, 50, 255])
        light_mask = cv2.inRange(img_hsv, light_lower, light_upper)

        # 3. 회색 범위
        gray_lower = np.array([0, 0, 50])
        gray_upper = np.array([180, 30, 200])
        gray_mask = cv2.inRange(img_hsv, gray_lower, gray_upper)

        # 배경 마스크 합치기 (파란색 + 밝은색 + 회색 = 배경)
        bg_mask = cv2.bitwise_or(blue_mask, light_mask)
        bg_mask = cv2.bitwise_or(bg_mask, gray_mask)

        # 모폴로지 연산 - 노이즈 제거
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_CLOSE, kernel)
        bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_OPEN, kernel)

        # 도그 마스크 (배경의 반대)
        dog_mask = cv2.bitwise_not(bg_mask)

        # 도그 마스크 다이레이션 (작은 구멍 메우기)
        kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        dog_mask = cv2.dilate(dog_mask, kernel2, iterations=2)
        dog_mask = cv2.erode(dog_mask, kernel2, iterations=1)

        # 흰색 배경 생성
        white_bg = np.full_like(img, 255)

        # 3채널로 마스크 확장
        dog_mask_3ch = cv2.cvtColor(dog_mask, cv2.COLOR_GRAY2BGR)

        # 이미지 합성 (도그는 원본, 배경은 흰색)
        result = np.where(dog_mask_3ch, img, white_bg)

        # PNG로 저장
        cv2.imwrite(image_path, result)

        print("✅")

    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 60)
print("✨ 공격적인 배경 제거 완료!")
print("=" * 60)
print("\nlocalhost:8000 새로고침하세요! (Ctrl+Shift+Delete 후)")
