#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image

mascot_path = r'C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png'

img = Image.open(mascot_path)
img = img.convert('RGBA')

pixels = img.load()
width, height = img.size
transparent_count = 0

for y in range(height):
    for x in range(width):
        r, g, b, a = pixels[x, y]
        if r > 200 and g > 200 and b > 200:
            pixels[x, y] = (r, g, b, 0)
            transparent_count += 1

img.save(mascot_path, 'PNG')
print(f"처리 완료! {transparent_count} 픽셀 투명화됨")
