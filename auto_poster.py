"""Daily Instagram promo for The Drowned Concordat, Book One.

Each run:
  1. `build`  - picks the next line from lines.txt and the next background from
                backgrounds/, draws a 1080x1350 JPEG card into generated/, and
                writes the caption + image path to post.json.
  2. (the workflow commits and pushes the card so it has a public URL)
  3. `post`   - waits until the card is publicly reachable, then sends the caption
                and image URL to the Make webhook, which publishes to Instagram.

Every day at 17:00 UTC: a quote card. Extra posts at 10:00 UTC: a website card on
Wednesdays and an Amazon card on Saturdays.

Rules: promote only published books (currently Book One). Never Business Time.
No spoilers: lines.txt holds setting and premise level text only.
"""

import json
import os
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINES_FILE = ROOT / "lines.txt"
BACKGROUNDS = ROOT / "backgrounds"
FONTS = ROOT / "fonts"
GENERATED = ROOT / "generated"
POST_FILE = ROOT / "post.json"
KEEP_CARDS = 30  # older generated cards are deleted to keep the repo small
KEEP_VIDEOS = 14

RAW_BASE = (
    "https://raw.githubusercontent.com/somhairlemaccormick-collab/"
    "The-Drowned-Concordat-Promo/main/"
)

HASHTAGS = (
    "#TheDrownedConcordat #HamishCRannoch #scifi #dystopian #climatefiction "
    "#bookstagram #scifibooks #kindlebooks"
)

# Rotating calls to action under each line. Instagram captions don't make links
# clickable, so links are written out plainly.
CALLS_TO_ACTION = [
    "📖 The Rise of the Covenant — Book One of The Drowned Concordat, out now on Kindle.\n"
    "🔗 https://www.amazon.com/dp/B0HJLRN48X",
    "🌊 Step behind the Bulwark. The Drowned Concordat, Book One: The Rise of the Covenant.\n"
    "🔗 https://thedrownedconcordat.com/",
    "📚 Start the series with Book One, The Rise of the Covenant. Available now on Kindle.\n"
    "🔗 https://www.amazon.com/dp/B0HJLRN48X",
]

W, H = 1080, 1350
ORANGE = (236, 128, 52)
CREAM = (240, 236, 228)
GREY = (170, 180, 185)
INK = (5, 10, 14)


def load_lines():
    lines = []
    for raw in LINES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def load_backgrounds():
    return sorted(p for p in BACKGROUNDS.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def pick(n):
    """Choose line and background for post number n (0-based).

    Lines go in order; backgrounds rotate independently, so with 40 lines and
    7 backgrounds the same line+background pairing only comes round once every
    280 posts.
    """
    lines, bgs = load_lines(), load_backgrounds()
    return lines[n % len(lines)], bgs[n % len(bgs)], CALLS_TO_ACTION[n % len(CALLS_TO_ACTION)]


# ---------------------------------------------------------------- drawing ---

def _background(path):
    from PIL import Image, ImageFilter

    src = Image.open(path).convert("RGB")
    # Blurred, darkened fill for the whole canvas
    r = max(W / src.width, H / src.height)
    fill = src.resize((round(src.width * r), round(src.height * r)), Image.LANCZOS)
    left, top = (fill.width - W) // 2, (fill.height - H) // 2
    fill = fill.crop((left, top, left + W, top + H))

    if src.width / src.height >= 1:
        # Landscape: keep it sharp across the top (barely enlarged), fade its lower
        # edge into a blurred fill so the text sits on a dark, calm area
        canvas = fill.filter(ImageFilter.GaussianBlur(30))
        band = 800
        r = max(W / src.width, band / src.height)
        sharp = src.resize((round(src.width * r), round(src.height * r)), Image.LANCZOS)
        left = (sharp.width - W) // 2
        sharp = sharp.crop((left, 0, left + W, band))
        mask = Image.new("L", sharp.size, 255)
        fade = int(band * 0.4)
        for y in range(band - fade, band):
            mask.paste(int(255 * (band - y) / fade), (0, y, W, y + 1))
        canvas.paste(sharp, (0, 0), mask)
        return canvas
    return fill  # portrait: fill the frame


def _darken(im):
    from PIL import Image

    g = Image.new("L", (1, H))
    for y in range(H):
        f = y / H
        a = 0.05 if f < 0.32 else min(0.94, 0.05 + 0.89 * ((f - 0.32) / 0.40) ** 1.1)
        g.putpixel((0, y), int(255 * a))
    return Image.composite(Image.new("RGB", (W, H), INK), im, g.resize((W, H)))


def _fit_text(draw, text, font_path, max_width, max_lines=7):
    """Largest font size (64 down to 40) at which the text wraps within the limits."""
    from PIL import ImageFont

    for size in range(64, 39, -2):
        font = ImageFont.truetype(str(font_path), size)
        avg = font.getlength("abcdefghijklmnopqrstuvwxyz") / 26
        width_chars = max(12, int(max_width / avg))
        lines = textwrap.wrap(text, width_chars)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_width for l in lines):
            # balance: narrow the wrap while the line count stays the same,
            # so the last line isn't a single dangling word
            k = len(lines)
            while width_chars > 12:
                tighter = textwrap.wrap(text, width_chars - 1)
                if len(tighter) != k:
                    break
                width_chars -= 1
                lines = tighter
            return font, lines, size
    return font, textwrap.wrap(text, width_chars), size


def _series_mark(draw, x, y, r=26):
    """The series' orange slashed circle."""
    draw.ellipse((x, y, x + 2 * r, y + 2 * r), outline=ORANGE, width=5)
    draw.line((x + 2 * r - 6, y + 4, x + 6, y + 2 * r - 4), fill=ORANGE, width=5)


def draw_card(text, bg_path, out_path):
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    serif = FONTS / "FreeSerifItalic.ttf"
    sans_bold = FONTS / "DejaVuSansCondensed-Bold.ttf"
    sans = FONTS / "DejaVuSansCondensed.ttf"

    im = _darken(_background(bg_path))
    d = ImageDraw.Draw(im)
    margin = 90
    font, lines, size = _fit_text(d, text, serif, W - 2 * margin)
    lh = int(size * 1.22)

    bottom_of_text = H - 230
    y = bottom_of_text - lh * len(lines)

    # soft shadow behind the line for legibility
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i, l in enumerate(lines):
        sd.text((margin + 2, y + i * lh + 3), l, font=font, fill=(0, 0, 0, 210))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    im.paste(shadow, (0, 0), shadow)
    d = ImageDraw.Draw(im)

    _series_mark(d, margin, y - 90)
    for i, l in enumerate(lines):
        d.text((margin, y + i * lh), l, font=font, fill=CREAM)

    rule_y = y + lh * len(lines) + 28
    d.line((margin, rule_y, margin + 80, rule_y), fill=ORANGE, width=4)
    d.text((margin, rule_y + 22), "THE RISE OF THE COVENANT · OUT NOW",
           font=ImageFont.truetype(str(sans_bold), 30), fill=CREAM)

    d.text((margin, H - 95), "THE DROWNED CONCORDAT · BOOK ONE",
           font=ImageFont.truetype(str(sans), 26), fill=GREY)
    d.text((W - margin, H - 95), "HAMISH C. RANNOCH",
           font=ImageFont.truetype(str(sans_bold), 26), fill=ORANGE, anchor="ra")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, "JPEG", quality=90, optimize=True)


# ---------------------------------------------------- weekly link posts ---
# Extra posts on top of the daily quote card: Wednesday points to the website,
# Saturday to Amazon. Each has a few headline/caption variants that rotate weekly.

WEBSITE_URL = "https://thedrownedconcordat.com/"
AMAZON_URL = "https://www.amazon.com/dp/B0HJLRN48X"

COVERS = [ROOT / "images" / "book1-rise-of-the-covenant-ebook.jpg",
          ROOT / "images" / "book1-rise-of-the-covenant-painted.jpg"]

WEBSITE_POSTS = [
    ("Step inside the Delta.",
     "Step inside the world of The Drowned Concordat: the Delta, the Bulwark and the books. 🌊"),
    ("New to the Delta? Start here.",
     "New to The Drowned Concordat? The series, the world and the author, all in one place."),
    ("The world behind the wall.",
     "Find out more about the drowned world of Hamish C. Rannoch's Drowned Concordat series."),
]

AMAZON_POSTS = [
    ("Out now on Kindle",
     "📖 The Rise of the Covenant, Book One of The Drowned Concordat, is out now on Kindle."),
    ("Book One is waiting",
     "Your next dystopian read is waiting behind the Bulwark. Get Book One on Kindle 👇"),
    ("Start the series",
     "Five hundred million people. Not one meal grown in soil. "
     "Start The Drowned Concordat with Book One, out now on Kindle."),
]


def post_kind():
    """Which card to make. The workflow sets POST_KIND from the schedule that fired
    (daily 17:00 UTC = quote, Wed 10:00 UTC = website, Sat 10:00 UTC = amazon)."""
    kind = os.environ.get("POST_KIND", "").strip().lower()
    return kind if kind in {"quote", "reel", "website", "amazon"} else "quote"


START = datetime(2026, 10, 22, tzinfo=timezone.utc)  # day 0 of the quote rotation


def day_number(now=None):
    """Days since START. Drives the rotation, so extra runs never skip a quote."""
    return ((now or datetime.now(timezone.utc)) - START).days


def _footer(d):
    from PIL import ImageFont

    margin = 90
    d.text((margin, H - 95), "THE DROWNED CONCORDAT · BOOK ONE",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed.ttf"), 26), fill=GREY)
    d.text((W - margin, H - 95), "HAMISH C. RANNOCH",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed-Bold.ttf"), 26),
           fill=ORANGE, anchor="ra")


def draw_amazon_card(headline, cover_path, out_path):
    """Book One cover on a blurred version of itself, with a Kindle call to action."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    cover = Image.open(cover_path).convert("RGB")
    r = max(W / cover.width, H / cover.height)
    bg = cover.resize((round(cover.width * r), round(cover.height * r)), Image.LANCZOS)
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
    im = Image.blend(bg, Image.new("RGB", (W, H), INK), 0.72)

    ch = 860
    c = cover.resize((round(cover.width * ch / cover.height), ch), Image.LANCZOS)
    cx, cy = (W - c.width) // 2, 70
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((cx + 10, cy + 18, cx + c.width + 10, cy + ch + 18), fill=(0, 0, 0, 190))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    im.paste(shadow, (0, 0), shadow)
    im.paste(c, (cx, cy))

    d = ImageDraw.Draw(im)
    y = cy + ch + 55
    d.text((W // 2, y), headline.upper(), anchor="ma",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed-Bold.ttf"), 44), fill=ORANGE)
    d.text((W // 2, y + 70), "The Rise of the Covenant", anchor="ma",
           font=ImageFont.truetype(str(FONTS / "FreeSerifItalic.ttf"), 58), fill=CREAM)
    d.text((W // 2, y + 150), "Find it on Amazon · link in caption", anchor="ma",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed.ttf"), 28), fill=GREY)
    _footer(d)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, "JPEG", quality=90, optimize=True)


def draw_website_card(headline, bg_path, out_path):
    """Delta artwork with a headline and the website address."""
    from PIL import ImageDraw, ImageFont

    im = _darken(_background(bg_path))
    d = ImageDraw.Draw(im)
    margin = 90
    font, lines, size = _fit_text(d, headline, FONTS / "FreeSerifItalic.ttf", W - 2 * margin, max_lines=3)
    lh = int(size * 1.22)
    y = H - 330 - lh * len(lines)
    _series_mark(d, margin, y - 90)
    for i, l in enumerate(lines):
        d.text((margin, y + i * lh), l, font=font, fill=CREAM)
    rule_y = y + lh * len(lines) + 28
    d.line((margin, rule_y, margin + 80, rule_y), fill=ORANGE, width=4)
    d.text((margin, rule_y + 26), "THEDROWNEDCONCORDAT.COM",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed-Bold.ttf"), 50), fill=ORANGE)
    d.text((margin, rule_y + 95), "The books · the world · the author",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed.ttf"), 30), fill=CREAM)
    _footer(d)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, "JPEG", quality=90, optimize=True)


# ------------------------------------------------------------ daily reel ---
# A 10-second 1080x1920 video for Instagram Reels and TikTok: a slow pan across
# the artwork under the day's line. Text is kept clear of the areas TikTok and
# Instagram cover with their own buttons and captions (right edge, bottom).
# It has a silent audio track so a trending sound can be added in TikTok.

VW, VH, FPS, SECONDS = 1080, 1920, 30, 10
REEL_OFFSET = 20  # use a different line/background from the same day's photo card


def _ffmpeg():
    import shutil

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _reel_text_layer(text):
    """Transparent 1080x1920 layer with the line, labels and series mark."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    layer = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    left, max_w = 80, 840  # leave the right edge for TikTok's buttons
    font, lines, size = _fit_text(d, text, FONTS / "FreeSerifItalic.ttf", max_w, max_lines=6)
    lh = int(size * 1.24)
    block = 90 + lh * len(lines) + 150
    y = max(1110, 1330 - block // 2)

    mark_y = y
    y += 90
    shadow = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i, l in enumerate(lines):
        sd.text((left + 2, y + i * lh + 3), l, font=font, fill=(0, 0, 0, 220))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))
    d = ImageDraw.Draw(layer)
    _series_mark(d, left, mark_y)
    for i, l in enumerate(lines):
        d.text((left, y + i * lh), l, font=font, fill=CREAM + (255,))
    rule_y = y + lh * len(lines) + 28
    d.line((left, rule_y, left + 80, rule_y), fill=ORANGE + (255,), width=4)
    d.text((left, rule_y + 22), "THE RISE OF THE COVENANT · OUT NOW",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed-Bold.ttf"), 32), fill=CREAM + (255,))
    d.text((left, rule_y + 70), "THE DROWNED CONCORDAT · HAMISH C. RANNOCH",
           font=ImageFont.truetype(str(FONTS / "DejaVuSansCondensed.ttf"), 26), fill=ORANGE + (255,))
    return layer


def draw_reel(text, bg_path, out_path):
    import subprocess

    from PIL import Image, ImageFilter

    src = Image.open(bg_path).convert("RGB")
    landscape = src.width / src.height >= 1

    # static, blurred, very dark fill behind everything
    r = max(VW / src.width, VH / src.height)
    fill = src.resize((round(src.width * r), round(src.height * r)), Image.LANCZOS)
    fx, fy = (fill.width - VW) // 2, (fill.height - VH) // 2
    fill = fill.crop((fx, fy, fx + VW, fy + VH)).filter(ImageFilter.GaussianBlur(40))
    base = Image.blend(fill, Image.new("RGB", (VW, VH), INK), 0.7)

    # darkening gradient so the text area is calm
    grad = Image.new("L", (1, VH))
    for y in range(VH):
        f = y / VH
        start = 0.45 if landscape else 0.38
        grad.putpixel((0, y), int(255 * (0.0 if f < start else min(0.92, 0.92 * ((f - start) / 0.2)))))
    grad = grad.resize((VW, VH))
    ink = Image.new("RGB", (VW, VH), INK)

    if landscape:
        band_h, band_y = 1000, 120
        s = band_h / src.height
        band = src.resize((round(src.width * s), band_h), Image.LANCZOS)
        travel = max(0, band.width - VW)
        mask = Image.new("L", (VW, band_h), 255)
        for y in range(band_h):
            a = min(1.0, y / 110, (band_h - y) / 260)
            mask.paste(int(255 * max(0.0, a)), (0, y, VW, y + 1))
    else:
        s = max(VW / src.width, VH / src.height)

    layer = _reel_text_layer(text)
    alpha = layer.getchannel("A")

    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    frames = FPS * SECONDS
    for i in range(frames):
        t = i / (frames - 1)
        frame = base.copy()
        if landscape:
            x = travel * _ease(t)
            part = band.transform((VW, band_h), Image.EXTENT, (x, 0, x + VW, band_h), Image.BICUBIC)
            frame.paste(part, (0, band_y), mask)
        else:
            z = 1.0 + 0.10 * _ease(t)  # slow push-in
            vw, vh = VW / (s * z), VH / (s * z)
            cx, cy = src.width / 2, src.height * 0.45
            box = (cx - vw / 2, max(0, cy - vh / 2), cx + vw / 2, max(0, cy - vh / 2) + vh)
            frame = src.transform((VW, VH), Image.EXTENT, box, Image.BICUBIC)
        frame = Image.composite(ink, frame, grad)
        # text is on screen from the first frame, so the Reel/TikTok thumbnail shows it
        frame.paste(layer, (0, 0), alpha)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")


# ------------------------------------------------------------------ steps ---

def build(n=None, kind=None):
    if n is None:
        n = day_number()
    kind = kind or post_kind()
    week = n // 7
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    card = GENERATED / f"{stamp}-{kind}-{os.environ.get('GITHUB_RUN_NUMBER', 'local')}.jpg"

    if kind == "website":
        headline, body = WEBSITE_POSTS[week % len(WEBSITE_POSTS)]
        bg = load_backgrounds()[week % len(load_backgrounds())]
        draw_website_card(headline, bg, card)
        caption, source = f"{body}\n\n🔗 {WEBSITE_URL}\n\n{HASHTAGS}", bg.name
    elif kind == "reel":
        text, bg, cta = pick(n + REEL_OFFSET)
        card = card.with_suffix(".mp4")
        draw_reel(text, bg, card)
        caption, source = f"{text}\n\n{cta}\n\n{HASHTAGS}", bg.name
    elif kind == "amazon":
        headline, body = AMAZON_POSTS[week % len(AMAZON_POSTS)]
        cover = COVERS[week % len(COVERS)]
        draw_amazon_card(headline, cover, card)
        caption, source = f"{body}\n\n🔗 {AMAZON_URL}\n\n{HASHTAGS}", cover.name
    else:
        text, bg, cta = pick(n)
        draw_card(text, bg, card)
        caption, source = f"{text}\n\n{cta}\n\n{HASHTAGS}", bg.name

    # keep only the most recent cards and videos
    for pattern, keep in (("*.jpg", KEEP_CARDS), ("*.mp4", KEEP_VIDEOS)):
        for p in sorted(GENERATED.glob(pattern))[:-keep]:
            p.unlink()

    post = {
        "kind": kind,
        "text": caption,
        "image_path": card.relative_to(ROOT).as_posix(),
        "background": source,
    }
    POST_FILE.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Post #{n + 1} ({kind})\nCaption:\n{caption}\nImage source: {source}\nCard: {post['image_path']}")
    return post


def wait_until_public(url, timeout=180):
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.head(url, timeout=20)
        if r.status_code == 200:
            print(f"Public: {url} ({r.headers.get('content-type')}, {r.headers.get('content-length')} bytes)")
            return
        print(f"Waiting for card to go public ({r.status_code})…")
        time.sleep(10)
    raise RuntimeError(f"Card never became public: {url}")


def post():
    import requests

    data = json.loads(POST_FILE.read_text(encoding="utf-8"))
    image_url = RAW_BASE + data["image_path"]
    wait_until_public(image_url)
    print(f"Caption:\n{data['text']}\nImage: {image_url}")

    if os.environ.get("DRY_RUN", "").lower() == "true":
        print("Dry run: card is public, not sending to Make.")
        return
    webhook_url = os.environ.get("SOCIAL_WEBHOOK_URL")
    if not webhook_url:
        print("Webhook URL not found. Running in test mode.")
        return
    payload = {"kind": data.get("kind", "quote"), "text": data["text"]}
    if image_url.endswith(".mp4"):
        payload["video_url"] = image_url
        payload["file_name"] = data["image_path"].rsplit("/", 1)[-1]
    else:
        payload["image_url"] = image_url
    response = requests.post(webhook_url, json=payload, timeout=30)
    print(f"Status: {response.status_code} {response.text[:200]}")
    response.raise_for_status()


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "build"
    if step == "build":
        build(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif step == "post":
        post()
    else:
        sys.exit(f"Unknown step: {step} (use 'build' or 'post')")
