"""Daily Instagram promo for The Drowned Concordat, Book One.

Each run:
  1. `build`  - picks the next line from lines.txt and the next background from
                backgrounds/, draws a 1080x1350 JPEG card into generated/, and
                writes the caption + image path to post.json.
  2. (the workflow commits and pushes the card so it has a public URL)
  3. `post`   - waits until the card is publicly reachable, then sends the caption
                and image URL to the Make webhook, which publishes to Instagram.

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


# ------------------------------------------------------------------ steps ---

def build(n=None):
    if n is None:
        n = int(os.environ.get("GITHUB_RUN_NUMBER", "1")) - 1
    text, bg, cta = pick(n)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    card = GENERATED / f"{stamp}-post{n + 1:04d}.jpg"
    draw_card(text, bg, card)

    # keep only the most recent cards
    old = sorted(GENERATED.glob("*.jpg"))[:-KEEP_CARDS]
    for p in old:
        p.unlink()

    post = {
        "text": f"{text}\n\n{cta}\n\n{HASHTAGS}",
        "image_path": card.relative_to(ROOT).as_posix(),
        "background": bg.name,
    }
    POST_FILE.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Post #{n + 1}: {text}\nBackground: {bg.name}\nCard: {post['image_path']}")
    return post


def wait_until_public(url, timeout=180):
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.head(url, timeout=20)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
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
    response = requests.post(webhook_url, json={"text": data["text"], "image_url": image_url}, timeout=30)
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
