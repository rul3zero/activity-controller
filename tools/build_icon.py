"""Rebuild Paper's document-and-pencil app icon (requires Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new("RGBA", (1024, 1024))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((48, 48, 976, 976), radius=210, fill="#657c50")
draw.rounded_rectangle((256, 186, 742, 838), radius=38, fill="#fffff5")
for y, end in [(330, 628), (430, 628), (530, 560), (630, 500)]:
    draw.rounded_rectangle((342, y, end, y + 20), radius=10, fill="#c8cebd")
draw.polygon([(518, 737), (555, 602), (784, 373), (882, 471), (653, 700)], fill="#394732")
draw.polygon([(549, 704), (573, 622), (632, 681)], fill="#ddc6a3")
draw.polygon([(582, 602), (784, 400), (855, 471), (653, 673)], fill="#b6c791")
target = Path(__file__).resolve().parents[1] / "assets" / "Paper.icns"
target.parent.mkdir(exist_ok=True)
image.save(target, format="ICNS")
print(target)
