#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import cv2
import numpy as np
from PIL import Image
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 강력한 배경 제거 - OpenCV 기반\n")

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        print(f"🔄 {i}.png 처리 중... ", end="", flush=True)

        # OpenCV로 로드 (BGR)
        img = cv2.imread(image_path)
        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 파란색 배경 감지 (파란색 범위)
        lower_blue = np.array([85, 50, 50])
        upper_blue = np.array([135, 255, 255])
        blue_mask = cv2.inRange(img_hsv, lower_blue, upper_blue)

        # 밝은 색상 감지 (하얀색/밝은 배경)
        lower_light = np.array([0, 0, 200])
        upper_light = np.array([180, 50, 255])
        light_mask = cv2.inRange(img_hsv, lower_light, upper_light)

        # 두 마스크 합치기
        bg_mask = cv2.bitwise_or(blue_mask, light_mask)

        # 모폴로지 연산 (노이즈 제거)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_CLOSE, kernel)
        bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_OPEN, kernel)

        # 도그 마스크 생성
        fg_mask = cv2.bitwise_not(bg_mask)
        fg_mask = cv2.dilate(fg_mask, kernel, iterations=2)
        fg_mask = cv2.erode(fg_mask, kernel, iterations=1)

        # 알파 채널 생성
        alpha = fg_mask

        # BGR → BGRA
        b_channel, g_channel, r_channel = cv2.split(img)
        img_bgra = cv2.merge([b_channel, g_channel, r_channel, alpha])

        # PNG로 저장
        cv2.imwrite(image_path, img_bgra)

        print("✅")

    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 60)
print("✨ 강력한 배경 제거 완료!")
print("=" * 60)
print("\nlocalhost:5000 새로고침! (Ctrl+Shift+Delete 후 F5)")
