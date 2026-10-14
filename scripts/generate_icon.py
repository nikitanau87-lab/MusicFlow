"""Create the offline, vector-like MusicFlow app icon at build time."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
folder = root / "assets"
folder.mkdir(exist_ok=True)
size = 1024
image = Image.new("RGBA", (size, size))
mask = Image.new("L", (size, size))
ImageDraw.Draw(mask).rounded_rectangle((44, 44, 980, 980), radius=208, fill=255)
gradient = Image.new("RGBA", (size, size))
pixels = gradient.load()
for y in range(size):
    for x in range(size):
        t = (x + y) / (2 * size)
        pixels[x, y] = (int(181 - 60 * t), int(145 - 55 * t), int(248 - 30 * t), 255)
image.paste(gradient, (0, 0), mask)
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((53, 53, 971, 971), radius=201, outline=(227, 207, 255, 110), width=5)
for x, height in zip((250, 360, 470, 580, 690), (178, 322, 460, 290, 142)):
    draw.rounded_rectangle((x, 512 - height // 2, x + 70, 512 + height // 2), radius=35, fill=(247, 240, 255, 255))
image.save(folder / "MusicFlow.png")
image.save(folder / "MusicFlow.icns")
