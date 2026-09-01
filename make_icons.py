from PIL import Image

img = Image.open("static/avatar.png")
for size in (192, 512):
    small = img.resize((size, size))
    small.save("static/icon-" + str(size) + ".png")
    print("icon-" + str(size) + ".png 生成完毕")
