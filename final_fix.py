#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image

path = r'C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png'

# 이미지 열기
img = Image.open(path)

# 이미지를 RGBA로 변환 (투명도 채널 추가)
img = img.convert('RGBA')

# 픽셀 데이터를 리스트로 변환
pixdata = img.getdata()

# 새로운 픽셀 데이터 리스트
newdata = []

# 각 픽셀 처리
for item in pixdata:
    # RGB 값 확인
    if len(item) == 4:
        r, g, b, a = item
    else:
        r, g, b = item[:3]
        a = 255

    # 흰색(R,G,B > 240) 감지 및 투명화
    if r > 240 and g > 240 and b > 240:
        newdata.append((r, g, b, 0))
    else:
        newdata.append((r, g, b, a))

# 새 이미지에 픽셀 데이터 설정
img.putdata(newdata)

# PNG로 저장 (투명도 유지)
img.save(path, 'PNG')

print("완료!")
