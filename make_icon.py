"""Genere assets/icon.ico et assets/icon.png (eclair sur fond degrade cyan -> violet)."""
import os
from PIL import Image, ImageDraw, ImageFilter

S = 1024
os.makedirs("assets", exist_ok=True)
grad = Image.new("RGB", (S, S))
px = grad.load()
c1, c2 = (34, 211, 238), (139, 92, 246)
for y in range(S):
    for x in range(S):
        f = (x + y) / (2 * S)
        px[x, y] = tuple(int(c1[i] * (1 - f) + c2[i] * f) for i in range(3))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=230, fill=255)
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icon.paste(grad, (0, 0), mask)

bolt = [(0.60, 0.10), (0.24, 0.55), (0.47, 0.55), (0.38, 0.91), (0.77, 0.43), (0.53, 0.43), (0.66, 0.10)]
pts = [(x * S, y * S) for x, y in bolt]
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).polygon([(x + 10, y + 22) for x, y in pts], fill=(10, 15, 40, 120))
shadow = shadow.filter(ImageFilter.GaussianBlur(18))
icon = Image.alpha_composite(icon, shadow)
ImageDraw.Draw(icon).polygon(pts, fill=(255, 255, 255, 255))

icon.resize((512, 512), Image.LANCZOS).save("assets/icon.png")
icon.save("assets/icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icone creee")