#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 배경 투명화 처리 최종 버전
from PIL import Image
import numpy as np

mascot_path = r"C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png"

# 이미지 로드
img = Image.open(mascot_path)
img_rgba = img.convert('RGBA')
data = np.array(img_rgba)

# 흰색 배경 감지 및 투명화
white_pixels = (data[:,:,0] > 200) & (data[:,:,1] > 200) & (data[:,:,2] > 200)
data[white_pixels, 3] = 0

# 저장
result = Image.fromarray(data, 'RGBA')
result.save(mascot_path, 'PNG')

print("배경 투명화 완료!")
