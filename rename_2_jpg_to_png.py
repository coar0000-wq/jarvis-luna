#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import shutil

images_dir = r"C:\Users\Desktop\Claude\Projects\kms\images"
source = os.path.join(images_dir, "2.jpg")
target = os.path.join(images_dir, "2.png")

if os.path.exists(source):
    shutil.move(source, target)
    print(f"✅ 완료: 2.jpg → 2.png로 변경되었습니다!")
else:
    print(f"❌ 오류: 2.jpg 파일을 찾을 수 없습니다")
