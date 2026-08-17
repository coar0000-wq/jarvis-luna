#!/usr/bin/env python3
# -*- coding: utf-8 -*-

if __name__ == "__main__":
    from PIL import Image
    import numpy as np

    mascot_path = r"C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png"

    print("=" * 60)
    print("개 캐릭터 이미지 배경 투명화 처리")
    print("=" * 60)

    # 이미지 로드
    img = Image.open(mascot_path)
    print(f"\n원본 이미지:")
    print(f"  - 크기: {img.size}")
    print(f"  - 모드: {img.mode}")

    # RGBA로 변환
    img = img.convert('RGBA')
    data = np.array(img)

    # 흰색 배경 감지 (R>200, G>200, B>200)
    white_mask = (data[:,:,0] > 200) & (data[:,:,1] > 200) & (data[:,:,2] > 200)

    # 알파 채널 투명화
    data[white_mask, 3] = 0

    # 이미지 저장
    result = Image.fromarray(data, 'RGBA')
    result.save(mascot_path, 'PNG')

    print(f"\n처리 완료:")
    print(f"  - 투명화된 픽셀: {np.sum(white_mask):,}개")
    print(f"  - 저장 위치: {mascot_path}")

    # 검증
    img_check = Image.open(mascot_path)
    data_check = np.array(img_check)
    transparent_count = np.sum(data_check[:,:,3] == 0)
    total = data_check.shape[0] * data_check.shape[1]

    print(f"\n검증:")
    print(f"  - 투명한 픽셀: {transparent_count:,}개 ({transparent_count/total*100:.1f}%)")
    print(f"  - 불투명한 픽셀: {total - transparent_count:,}개 ({(total-transparent_count)/total*100:.1f}%)")
    print(f"\n✨ 배경 투명화 완료! localhost:8000 새로고침")
