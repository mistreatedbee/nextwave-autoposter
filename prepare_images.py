"""Create Instagram-ready JPEGs (feed 1080x1350, story 1080x1920) from flyers/*.png."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

import content

FEED_SIZE = (1080, 1350)
STORY_SIZE = (1080, 1920)
STORY_MARGIN = 220
QUALITY = 92
MIN_SOURCE_WIDTH = 1000


def flatten(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white and return RGB."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def blurred_background(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cover-crop a copy of the image to `size` and blur it softly."""
    w, h = size
    scale = max(w / img.width, h / img.height)
    big = img.resize((round(img.width * scale) + 1, round(img.height * scale) + 1), Image.LANCZOS)
    left, top = (big.width - w) // 2, (big.height - h) // 2
    bg = big.crop((left, top, left + w, top + h))
    return bg.filter(ImageFilter.GaussianBlur(40))


def compose(img: Image.Image, size: tuple[int, int], margin_y: int = 0) -> Image.Image:
    """Place the flyer, scaled to fit inside the safe area, on its blurred copy."""
    w, h = size
    canvas = blurred_background(img, size)
    avail_w, avail_h = w, h - 2 * margin_y
    scale = min(avail_w / img.width, avail_h / img.height)
    fw, fh = round(img.width * scale), round(img.height * scale)
    fit = img.resize((fw, fh), Image.LANCZOS)
    canvas.paste(fit, ((w - fw) // 2, (h - fh) // 2))
    return canvas


def prepare(flyer: content.Flyer) -> list[Path]:
    src = flatten(Image.open(flyer.png))
    if src.width < MIN_SOURCE_WIDTH:
        print(f"WARNING: {flyer.png.name} is only {src.width}px wide (< {MIN_SOURCE_WIDTH}); it may look soft.")
    outputs = []
    for path, size, margin in ((flyer.feed_jpg(), FEED_SIZE, 0), (flyer.story_jpg(), STORY_SIZE, STORY_MARGIN)):
        path.parent.mkdir(parents=True, exist_ok=True)
        compose(src, size, margin).save(path, "JPEG", quality=QUALITY, optimize=True)
        outputs.append(path)
    return outputs


def main() -> int:
    c = content.Content()
    missing = [f for f in c.flyers if not f.png.exists()]
    for f in missing:
        print(f"ERROR: missing {f.png}")
    for f in c.flyers:
        if f in missing:
            continue
        for p in prepare(f):
            print(f"wrote {p.relative_to(content.ROOT)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
