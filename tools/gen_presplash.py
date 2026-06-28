"""Stamp the app version onto the Android presplash.

Idempotent: always starts from presplash_base.png (the pristine logo+name splash)
and writes presplash.png, so re-running after a version bump just restamps cleanly.
Run after changing APP_VERSION:  PYTHONPATH=. python tools/gen_presplash.py
"""
import os

import kivy
from PIL import Image, ImageDraw, ImageFont

from app.config import APP_VERSION

ICONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "assets", "icons"
)
BASE = os.path.join(ICONS, "presplash_base.png")
OUT = os.path.join(ICONS, "presplash.png")
FONT = os.path.join(os.path.dirname(kivy.__file__), "data", "fonts", "Roboto-Regular.ttf")


def main() -> None:
    img = Image.open(BASE).convert("RGBA")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 34)
    text = f"v{APP_VERSION}"
    w, _ = img.size
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (w - (bbox[2] - bbox[0])) / 2
    draw.text((x, 915), text, font=font, fill=(130, 140, 160, 255))  # below the "Trainer" subtitle
    img.save(OUT)
    print(f"presplash.png updated with {text}")


if __name__ == "__main__":
    main()
