#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
import os

# 첫 번째 이미지(1.png) 분석
image_path = r"C:\Users\Desktop\Claude\Projects\kms\images\1.png"

if os.path.exists(image_path):
    img = Image.open(image_path)
    print(f"이미지 크기: {img.size}")
    print(f"이미지 모드: {img.mode}")

    # RGB/RGBA로 변환
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    data = np.array(img)
    print(f"배열 크기: {data.shape}")

    # 이미지의 모서리 색상 분석 (배경으로 추정)
    print("\n=== 모서리 색상 분석 (배경) ===")
    corners = [
        ("좌상단", data[10, 10, :3]),
        ("우상단", data[10, -10, :3]),
        ("좌하단", data[-10, 10, :3]),
        ("우하단", data[-10, -10, :3]),
    ]

    for name, color in corners:
        print(f"{name}: RGB({color[0]}, {color[1]}, {color[2]})")

    # 가장 흔한 색상 찾기 (배경)
    print("\n=== 가장 흔한 색상 ===")
    pixels = data[:, :, :3].reshape(-1, 3)
    unique, counts = np.unique(pixels, axis=0, return_counts=True)

    # 상위 5개 색상
    top_indices = np.argsort(counts)[-5:][::-1]
    for idx in top_indices:
        color = unique[idx]
        count = counts[idx]
        percentage = (count / len(pixels)) * 100
        print(f"RGB({color[0]}, {color[1]}, {color[2]}): {count}개 ({percentage:.1f}%)")
else:
    print(f"❌ 파일 없음: {image_path}")
