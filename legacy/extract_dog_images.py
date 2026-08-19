#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import cv2
import numpy as np
from PIL import Image
import os

base_dir = r"C:\Users\Desktop\Claude\Projects\kms"
images_dir = os.path.join(base_dir, "images")

print("🐕 자비스 - 도그 이미지 정밀 추출 시작...\n")

success_count = 0

# 1.png ~ 16.png 처리
for i in range(1, 17):
    image_path = os.path.join(images_dir, f"{i}.png")

    if not os.path.exists(image_path):
        print(f"❌ {i}.png 없음")
        continue

    try:
        print(f"🔄 {i}.png 추출 중... ", end="")

        # 이미지 로드
        img_bgr = cv2.imread(image_path)
        img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

        # 도그의 색상 범위 감지 (갈색/주황색)
        # 도그의 갈색 모피 색상
        lower_brown1 = np.array([5, 50, 50])
        upper_brown1 = np.array([25, 255, 255])
        mask1 = cv2.inRange(img_hsv, lower_brown1, upper_brown1)

        # 도그의 어두운 갈색
        lower_brown2 = np.array([10, 100, 30])
        upper_brown2 = np.array([20, 255, 180])
        mask2 = cv2.inRange(img_hsv, lower_brown2, upper_brown2)

        # 도그의 검은색 부분 (눈, 코)
        lower_black = np.array([0, 0, 0])
        upper_black = np.array([180, 50, 50])
        mask3 = cv2.inRange(img_hsv, lower_black, upper_black)

        # 도그의 빨간색/분홍색 부분 (입, 신발)
        lower_red = np.array([0, 50, 50])
        upper_red = np.array([10, 255, 255])
        mask4 = cv2.inRange(img_hsv, lower_red, upper_red)

        # 모든 도그 색상 범위 결합
        dog_mask = cv2.bitwise_or(mask1, mask2)
        dog_mask = cv2.bitwise_or(dog_mask, mask3)
        dog_mask = cv2.bitwise_or(dog_mask, mask4)

        # 모폴로지 연산으로 도그 영역 확대 및 노이즈 제거
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        dog_mask = cv2.morphologyEx(dog_mask, cv2.MORPH_CLOSE, kernel)
        dog_mask = cv2.morphologyEx(dog_mask, cv2.MORPH_DILATE, kernel, iterations=2)

        # 가장 큰 윤곽선 찾기 (도그)
        contours, _ = cv2.findContours(dog_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            # 가장 큰 윤곽선
            largest_contour = max(contours, key=cv2.contourArea)

            # 최소 바운딩 박스
            x, y, w, h = cv2.boundingRect(largest_contour)

            # 여백 추가 (도그를 완전히 포함하도록)
            padding = 20
            x = max(0, x - padding)
            y = max(0, y - padding)
            w = min(img_bgr.shape[1] - x, w + 2 * padding)
            h = min(img_bgr.shape[0] - y, h + 2 * padding)

            # 도그 부분만 crop
            dog_region = img_bgr[y:y+h, x:x+w].copy()

            # 정밀한 마스크 생성
            dog_hsv = cv2.cvtColor(dog_region, cv2.COLOR_BGR2HSV)

            # 배경 제거 (배경은 파랑/회색/흰색)
            lower_bg_blue = np.array([90, 40, 40])
            upper_bg_blue = np.array([140, 255, 255])
            mask_bg_blue = cv2.inRange(dog_hsv, lower_bg_blue, upper_bg_blue)

            lower_bg_gray = np.array([0, 0, 80])
            upper_bg_gray = np.array([180, 60, 255])
            mask_bg_gray = cv2.inRange(dog_hsv, lower_bg_gray, upper_bg_gray)

            # 배경 마스크 결합
            bg_mask = cv2.bitwise_or(mask_bg_blue, mask_bg_gray)

            # 도그 마스크 (배경의 역)
            final_mask = cv2.bitwise_not(bg_mask)

            # 모폴로지 연산
            kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_CLOSE, kernel2)
            final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_OPEN, kernel2)

            # RGBA로 변환
            b, g, r = cv2.split(dog_region)
            dog_rgba = cv2.merge([b, g, r, final_mask])

            # 원본 이미지 크기로 복원
            result_img = np.zeros((img_bgr.shape[0], img_bgr.shape[1], 4), dtype=np.uint8)
            result_img[y:y+h, x:x+w] = dog_rgba

            # PIL로 변환 후 저장
            img_pil = Image.fromarray(cv2.cvtColor(result_img, cv2.COLOR_BGRA2RGBA))
            img_pil.save(image_path, 'PNG')

            print("✅")
            success_count += 1
        else:
            print("⚠️ 도그 감지 실패")

    except Exception as e:
        print(f"❌ {str(e)[:40]}")

print("\n" + "=" * 60)
print(f"✨ 도그 이미지 추출 완료!")
print(f"✅ 성공: {success_count}/16개")
print("=" * 60)
print("\n💡 localhost:8000을 새로고침(Ctrl+F5)하세요!")
