from PIL import Image
import os

os.chdir('C:\\Users\\Desktop\\Claude\\Projects\\kms\\images')

base_size = (800, 800)

# 2-12.png 리사이징
for i in range(2, 13):
    img_path = f'{i}.png'
    if os.path.exists(img_path):
        img = Image.open(img_path)
        
        # 비율 유지하면서 리사이징
        img.thumbnail(base_size, Image.Resampling.LANCZOS)
        
        # 800x800 캔버스에 중앙 배치
        new_img = Image.new('RGBA', base_size, (255, 255, 255, 0))
        offset = ((base_size[0] - img.size[0]) // 2, 
                  (base_size[1] - img.size[1]) // 2)
        new_img.paste(img, offset, img if img.mode == 'RGBA' else None)
        new_img.save(img_path, 'PNG')
        
        print(f'{i}.png -> 800x800 완료')

print("모든 이미지가 800x800으로 통일되었습니다!")
