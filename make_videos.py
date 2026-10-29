#!/usr/bin/env python3
"""Render a ~12s vertical promo video (videos/<id>.mp4) for each flyer.

Local tool (macOS fonts). Needs: pip install -r requirements-video.txt
Usage: python3 make_videos.py [flyer-id ...] [--preview]   (--preview also saves PNG frames)
Only facts from captions.json's brief are used; edit VIDEOS below to change wording.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import content

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM = 230, 330
DARK, LIME, CREAM, WHITE, MUTED = (26, 35, 20), (198, 217, 42), (243, 241, 232), (255, 255, 255), (190, 200, 175)
SCENES = (3.2, 5.6, 3.2)       # flyer, features, end card (seconds)
FADE = 0.45
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"

VIDEOS = {
    "web-design-packages": dict(
        head=["Get your", "business", "online."], accent=2,
        badge=("ALL ONCE-OFF", "Free .co.za domain included"),
        bullets=["Starter  R3500 - up to 5 pages", "Professional  R5000 - up to 10 pages",
                 "Premium  R7000 - unlimited pages", "Mobile responsive"]),
    "ecommerce-store": dict(
        head=["Start selling", "online."], accent=1,
        badge=("R5500", "ONCE-OFF"),
        bullets=["Unlimited products", "Payment gateways setup", "Training included",
                 "Mobile friendly", "1 year hosting & domain included"]),
    "ai-automation": dict(
        head=["Let automation", "do the", "busywork."], accent=2,
        badge=("R9000", "ONCE-OFF SETUP"),
        bullets=["AI chatbot & live chat", "Appointment scheduling", "Lead capture & follow-up",
                 "Email marketing", "Training & support"]),
    "landing-page": dict(
        head=["One page.", "Everything", "your business needs."], accent=2,
        badge=("R3000", "ONCE-OFF - NO MONTHLY FEES"),
        bullets=["Modern design", "Customer booking", "Gallery / portfolio",
                 "Fast loading & SEO optimised", "Easy to edit"]),
    "mobile-app": dict(
        head=["Your idea,", "as a", "mobile app."], accent=2,
        badge=("ANDROID & iOS-READY", "Custom app design & development"),
        bullets=["Secure login & user management", "Real-time notifications",
                 "Booking, payments & chat", "UI/UX design"]),
}


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def text_w(draw, text, f) -> int:
    return int(draw.textlength(text, font=f))


def fit_font(draw, text, path, size, max_w):
    while size > 24 and text_w(draw, text, font(path, size)) > max_w:
        size -= 2
    return font(path, size)


def blurred_cover(img: Image.Image) -> Image.Image:
    s = max(W / img.width, H / img.height)
    big = img.resize((round(img.width * s) + 1, round(img.height * s) + 1), Image.BILINEAR)
    l, t = (big.width - W) // 2, (big.height - H) // 2
    return big.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(45))


def gradient_bg() -> Image.Image:
    top, bot = DARK, (40, 56, 28)
    col = Image.new("RGB", (1, H))
    col.putdata([tuple(round(top[i] + (bot[i] - top[i]) * y / H) for i in range(3)) for y in range(H)])
    return col.resize((W, H))


class Renderer:
    def __init__(self, flyer_id: str, spec: dict, flyer_img: Image.Image):
        self.spec = spec
        avail_h = H - SAFE_TOP - SAFE_BOTTOM + 120
        s = min((W - 20) / flyer_img.width, avail_h / flyer_img.height)
        self.flyer_base = flyer_img.resize((round(flyer_img.width * s * 1.2), round(flyer_img.height * s * 1.2)), Image.LANCZOS)
        self.fit = (round(flyer_img.width * s), round(flyer_img.height * s))
        self.bg_flyer = blurred_cover(flyer_img)
        self.bg_dark = gradient_bg()
        self.d = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # --- scene 1: the flyer itself, slow zoom, sliding in -------------------
    def scene_flyer(self, t: float) -> Image.Image:
        im = self.bg_flyer.copy()
        z = 1.0 + 0.06 * (t / SCENES[0])
        w, h = round(self.fit[0] * z), round(self.fit[1] * z)
        fl = self.flyer_base.resize((w, h), Image.BILINEAR)
        p = ease(t / 0.6)
        y = (H - h) // 2 + int(220 * (1 - p))
        im.paste(fl, ((W - w) // 2, y))
        return im

    # --- scene 2: headline, price badge, staggered bullets ------------------
    def scene_features(self, t: float) -> Image.Image:
        sp = self.spec
        im = self.bg_dark.copy()
        d = ImageDraw.Draw(im)
        # brand pill
        pill_f = font(FONT_BOLD, 30)
        label = "NEXTWAVE DIGITAL SOLUTIONS"
        pw = text_w(d, label, pill_f) + 60
        p = ease(t / 0.4)
        d.rounded_rectangle(((W - pw) // 2, SAFE_TOP + int(30 * (1 - p)), (W + pw) // 2,
                             SAFE_TOP + 70 + int(30 * (1 - p))), 35, fill=LIME)
        d.text(((W - pw) // 2 + 30, SAFE_TOP + 17 + int(30 * (1 - p))), label, font=pill_f, fill=DARK)
        # headline lines
        y = SAFE_TOP + 130
        hf = font(FONT_BOLD, 92)
        for i, line in enumerate(sp["head"]):
            lp = ease((t - 0.25 - 0.18 * i) / 0.45)
            f = fit_font(d, line, FONT_BOLD, 92, W - 120)
            layer = Image.new("RGBA", (W, 130), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            lw = text_w(ld, line, f)
            ld.text(((W - lw) / 2, 0), line, font=f, fill=LIME if i == sp["accent"] else WHITE)
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * lp)))
            im.paste(layer, (0, y + int(40 * (1 - lp))), layer)
            y += 108
        y += 30
        # badge
        big, small = sp["badge"]
        bt = ease((t - 1.0) / 0.5)
        is_price = big.startswith("R")
        bh = 250 if is_price else 190
        if bt > 0:
            off = int(50 * (1 - bt))
            layer = Image.new("RGBA", (W, bh + 10), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.rounded_rectangle((90, 0, W - 90, bh), 36, fill=LIME)
            bf = fit_font(ld, big, FONT_BOLD, 150 if is_price else 62, W - 260)
            sf = fit_font(ld, small, FONT_BOLD if is_price else FONT_REG, 34 if is_price else 36, W - 240)
            bw = text_w(ld, big, bf)
            ld.text(((W - bw) / 2, 28 if is_price else 38), big, font=bf, fill=DARK)
            sw = text_w(ld, small, sf)
            ld.text(((W - sw) / 2, bh - 66 if is_price else bh - 70), small, font=sf, fill=DARK)
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * bt)))
            im.paste(layer, (0, y + off), layer)
        y += bh + 60
        # bullets
        bf = font(FONT_BOLD, 50)
        for i, text in enumerate(sp["bullets"]):
            bp = ease((t - 1.7 - 0.5 * i) / 0.45)
            if bp <= 0:
                continue
            layer = Image.new("RGBA", (W, 100), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.ellipse((90, 14, 150, 74), fill=LIME)
            ld.line([(105, 45), (116, 58), (136, 32)], fill=DARK, width=7, joint="curve")
            f = fit_font(ld, text, FONT_BOLD, 50, W - 270)
            ld.text((180, 44 - f.size // 2 - 2), text, font=f, fill=WHITE)
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * bp)))
            im.paste(layer, (int(-60 * (1 - bp)), y), layer)
            y += 112
        assert y - 112 + 100 <= H - SAFE_BOTTOM + 20, "content runs into the bottom safe area"
        return im

    # --- scene 3: end card ---------------------------------------------------
    def scene_end(self, t: float) -> Image.Image:
        im = self.bg_dark.copy()
        d = ImageDraw.Draw(im)
        items = [
            ("Build. Grow.", font(FONT_BOLD, 104), LIME, 0.0),
            ("Succeed online.", font(FONT_BOLD, 104), WHITE, 0.2),
            ("073 153 1188", font(FONT_BOLD, 76), WHITE, 0.6),
            ("www.nextwavedigitalsolutions.co.za", None, LIME, 0.8),
            ("info@nextwavedigitalsolutions.co.za", None, MUTED, 1.0),
            ("Made for South African businesses", font(FONT_REG, 36), MUTED, 1.3),
        ]
        ys = [SAFE_TOP + 330, SAFE_TOP + 450, SAFE_TOP + 650, SAFE_TOP + 770, SAFE_TOP + 850, SAFE_TOP + 980]
        for (text, f, color, delay), y in zip(items, ys):
            f = f or fit_font(d, text, FONT_BOLD, 46, W - 100)
            p = ease((t - delay) / 0.5)
            layer = Image.new("RGBA", (W, 140), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.text(((W - text_w(ld, text, f)) / 2, 0), text, font=f, fill=color)
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * p)))
            im.paste(layer, (0, y + int(40 * (1 - p))), layer)
        return im

    # --- timeline ------------------------------------------------------------
    @property
    def duration(self) -> float:
        return sum(SCENES)

    def frame(self, t: float) -> Image.Image:
        s1, s2 = SCENES[0], SCENES[0] + SCENES[1]
        funcs = [(0.0, SCENES[0], self.scene_flyer), (s1, SCENES[1], self.scene_features),
                 (s2, SCENES[2], self.scene_end)]
        for i, (start, dur, fn) in enumerate(funcs):
            if t < start + dur or i == len(funcs) - 1:
                im = fn(min(t - start, dur))
                # crossfade into the next scene
                if i < len(funcs) - 1 and t > start + dur - FADE:
                    nxt = funcs[i + 1]
                    im = Image.blend(im, nxt[2](max(0.0, t - nxt[0])),
                                     (t - (start + dur - FADE)) / FADE)
                return im
        raise AssertionError


def render(flyer: content.Flyer, preview: bool) -> Path:
    import imageio_ffmpeg
    spec = VIDEOS[flyer.id]
    src = Image.open(flyer.png)
    src = content_flatten(src)
    r = Renderer(flyer.id, spec, src)
    out = content.ROOT / "videos" / f"{flyer.id}.mp4"
    out.parent.mkdir(exist_ok=True)
    n = round(r.duration * FPS)
    if preview:
        pdir = content.ROOT / "videos" / "_preview"
        pdir.mkdir(exist_ok=True)
        for label, t in (("a-flyer", 1.5), ("b-features-early", 4.4), ("c-features-full", 8.3), ("d-end", 11.5)):
            r.frame(t).save(pdir / f"{flyer.id}-{label}.png")
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        proc.stdin.write(r.frame(i / FPS).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out


def content_flatten(img: Image.Image) -> Image.Image:
    import prepare_images
    return prepare_images.flatten(img)


def main(argv: list[str]) -> int:
    preview = "--preview" in argv
    ids = [a for a in argv if not a.startswith("--")]
    c = content.Content()
    flyers = [f for f in c.flyers if not ids or f.id in ids]
    for f in flyers:
        out = render(f, preview)
        print(f"wrote {out.relative_to(content.ROOT)}  ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
