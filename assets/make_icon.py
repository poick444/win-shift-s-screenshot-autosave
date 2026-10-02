"""Generate Kadr's simple crop-frame icon."""

from pathlib import Path

from PIL import Image, ImageDraw


SIZE = 256
image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((12, 12, 244, 244), radius=52, fill="#25313b")

color = "#f5f5f0"
width = 20
for points in (
    [(64, 106), (64, 64), (106, 64)],
    [(150, 64), (192, 64), (192, 106)],
    [(64, 150), (64, 192), (106, 192)],
    [(150, 192), (192, 192), (192, 150)],
):
    draw.line(points, fill=color, width=width, joint="curve")

draw.rounded_rectangle((112, 112, 144, 144), radius=6, fill="#76a7b8")
image.save(Path(__file__).with_name("kadr.ico"), format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
