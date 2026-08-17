from PIL import Image
import os

os.chdir('C:\\Users\\Desktop\\Claude\\Projects\\kms\\images')

base_size = (800, 800)

# 2-12.png 자동 조정
for i in range(2, 13):
    img_path = f'{i}.png'
    if os.path.exists(img_path):
        img = Image.open(img_path)
        
        # 원본 이미지 정보
        w, h = img.size
        print(f'{i}.png: 원본 {w}x{h}')
        
        # 1단계: 이미지를 400x400으로 크롭 (중앙 기준)
        left = (w - 400) // 2
        top = (h - 400) // 2
        right = left + 400
        bottom = top + 400
        
        # 범위 초과 방지
        left = max(0, left)
        top = max(0, top)
        right = min(w, right)
        bottom = min(h, bottom)
        
        img_cropped = img.crop((left, top, right, bottom))
        
        # 2단계: 800x800으로 확대
        img_resized = img_cropped.resize(base_size, Image.Resampling.LANCZOS)
        
        # 3단계: 저장
        img_resized.save(img_path, 'PNG')
        print(f'  완료: {i}.png -> 800x800')

print("모든 이미지 조정 완료!")
