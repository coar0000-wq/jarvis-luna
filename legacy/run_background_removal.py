from PIL import Image
img = Image.open(r'C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png')
img_rgba = img.convert('RGBA')
pixels = img_rgba.getdata()
new_data = [(r,g,b,0) if r>240 and g>240 and b>240 else (r,g,b,a if len(p)==4 else 255) for p in pixels for r,g,b,*a in [p]]
img_rgba.putdata(new_data)
img_rgba.save(r'C:\Users\Desktop\Claude\Projects\kms\images\mascot-main.png', 'PNG')
print('완료!')
