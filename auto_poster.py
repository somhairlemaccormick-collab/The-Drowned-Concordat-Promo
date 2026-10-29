"""Daily Instagram promo for The Drowned Concordat, Book One.

Each run:
  1. `build`  - makes today's post into generated/ and writes the caption and
                file path(s) to post.json.
  2. (the workflow commits and pushes the files so they have a public URL)
  3. `post`   - waits until the files are publicly reachable, then sends the
                caption and URL(s) to the Make webhook, which publishes them.

Post kinds (the workflow picks one from the schedule that fired):
  quote     daily 1080x1350 card. The design comes from the line's tag in
            lines.txt: artwork card, Bulwark Notice poster, Council record or
            gel ration label.
  reel      daily 12-second 1080x1920 video with rising water, an ambient sound
            bed and a Book One end card (Instagram Reels, YouTube Shorts, TikTok).
  carousel  Monday and Friday: a swipeable 5-6 slide post ending on the cover.
  website   Wednesday: website card.     amazon  Saturday: Kindle card.

Rules: promote only published books (currently Book One). Never Business Time.
No spoilers: everything here is setting and premise level only.
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINES_FILE = ROOT / "lines.txt"
BACKGROUNDS = ROOT / "backgrounds"
FONTS = ROOT / "fonts"
GENERATED = ROOT / "generated"
POST_FILE = ROOT / "post.json"
KEEP_CARDS = 40  # older generated cards are deleted to keep the repo small
KEEP_VIDEOS = 14

RAW_BASE = (
    "https://raw.githubusercontent.com/somhairlemaccormick-collab/"
    "The-Drowned-Concordat-Promo/main/"
)
CDN_BASE = "https://cdn.jsdelivr.net/gh/somhairlemaccormick-collab/The-Drowned-Concordat-Promo@{sha}/"
# GitHub Pages for this repo: serves every file with the right type and no size cap.
PAGES_BASE = "https://somhairlemaccormick-collab.github.io/The-Drowned-Concordat-Promo/"

WEBSITE_URL = "https://thedrownedconcordat.com/"
AMAZON_URL = "https://www.amazon.com/dp/B0HJLRN48X"

# A handful of focused tags reaches further than a long list.
HASHTAGS = "#TheDrownedConcordat #dystopianbooks #scifibooks #climatefiction #booktok #bookstagram"

# Rotating calls to action under each line. Instagram captions don't make links
# clickable, so links are written out plainly.
CALLS_TO_ACTION = [
    # Captions that opened with or leaned on links did worst on the account, so
    # most daily posts point to the bio; the full link goes out one day in three
    # (and always on the Wednesday website / Saturday Amazon posts).
    "📖 The Rise of the Covenant, Book One of The Drowned Concordat. Out now on Kindle, link in bio.",
    "🌊 Step behind the Bulwark. The Drowned Concordat, Book One: The Rise of the Covenant.\n"
    f"🔗 {AMAZON_URL}",
    "📚 Start the series with Book One, The Rise of the Covenant. Link in bio.",
]

# A question after the line gives people a reason to comment.
COMMENT_PROMPTS = [
    "💬 Would you trust the ration? Tell me below 👇",
    "💬 Which side of the Bulwark would you want to live on? 👇",
    "💬 Gel for every meal: could you do it? 👇",
    "💬 What's the first real meal you'd miss? 👇",
    "💬 Who would you rather trust: the Council or the numbers? 👇",
    "💬 Save this for your TBR pile 📌",
    "💬 Tag someone who'd survive the Delta 👇",
]

# Small label above the line on artwork cards and Reels.
KICKERS = [
    "OVERHEARD IN THE DELTA",
    "FROM BEHIND THE BULWARK",
    "DISPATCH FROM GELDERLAND",
    "A NOTE FROM THE FLOOD LINE",
]
PITCH_KICKER = "BOOK ONE · OUT NOW ON KINDLE"

W, H = 1080, 1350
ORANGE = (236, 128, 52)
TEAL = (78, 205, 196)
CREAM = (240, 236, 228)
GREY = (170, 180, 185)
INK = (5, 10, 14)
PAPER = (226, 219, 201)
TYPE_INK = (38, 34, 30)
STAMP_RED = (176, 38, 32)

SERIF_IT = FONTS / "FreeSerifItalic.ttf"
SANS = FONTS / "DejaVuSansCondensed.ttf"
SANS_BOLD = FONTS / "DejaVuSansCondensed-Bold.ttf"
DISPLAY = FONTS / "InterDisplay-ExtraBold.otf"
DISPLAY_BLACK = FONTS / "InterDisplay-Black.otf"
MONO = FONTS / "DejaVuSansMono-Bold.ttf"

COVERS = [ROOT / "images" / "book1-rise-of-the-covenant-ebook.jpg",
          ROOT / "images" / "book1-rise-of-the-covenant-painted.jpg"]

FORMATS = {"card", "poster", "record", "ration", "pitch"}


# ------------------------------------------------------------------ lines ---

def load_lines():
    lines = []
    for raw in LINES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def parse_line(line):
    """'[poster] Some *accent* text' -> ('poster', 'Some *accent* text')."""
    m = re.match(r"^\[(\w+)\]\s*(.*)$", line)
    if m and m.group(1).lower() in FORMATS:
        return m.group(1).lower(), m.group(2)
    return "card", line


def plain(text):
    """The line as it appears in captions and titles: no asterisks."""
    return text.replace("*", "")


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


def font(path, size):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size)


# ------------------------------------------------------------ rich text ---
# Text with *accent* words, wrapped and drawn word by word.

def _tokens(text):
    out, on = [], False
    for w in text.split():
        if w.startswith("*"):
            on, w = True, w[1:]
        close = False
        m = re.match(r"^(.*?)\*(\W*)$", w)
        if m:
            w, close = m.group(1) + m.group(2), True
        out.append((w, on))
        if close:
            on = False
    return out


def _wrap(tokens, f, max_w):
    lines = [[]]
    for t in tokens:
        trial = lines[-1] + [t]
        if lines[-1] and f.getlength(" ".join(w for w, _ in trial)) > max_w:
            lines.append([t])
        else:
            lines[-1] = trial
    return lines


def fit_rich(text, font_path, max_w, max_lines, sizes, upper=False):
    """Largest size from `sizes` at which the text fits; lines are balanced so
    the last one isn't a single dangling word."""
    toks = _tokens(text.upper() if upper else text)
    for size in sizes:
        f = font(font_path, size)
        lines = _wrap(toks, f, max_w)
        if len(lines) <= max_lines and all(f.getlength(w) <= max_w for w, _ in toks):
            k, w = len(lines), max_w
            while w > max_w * 0.55:
                tighter = _wrap(toks, f, w - 8)
                if len(tighter) != k:
                    break
                w, lines = w - 8, tighter
            return f, lines, size
    return f, lines, size


def line_width(line, f):
    return f.getlength(" ".join(w for w, _ in line))


def draw_rich(layer, x, y, lines, f, lh, fill, accent, align="left", shadow=True, highlight=None):
    """Draw wrapped rich text onto an RGBA layer. align='center' centres on x.
    highlight=(r,g,b,a) paints a marker stripe behind accent words instead of
    recolouring them."""
    from PIL import Image, ImageDraw, ImageFilter

    def place(d, colour_for, dx=0, dy=0):
        for i, line in enumerate(lines):
            cx = x - line_width(line, f) / 2 if align == "center" else x
            for w, a in line:
                d.text((cx + dx, y + i * lh + dy), w, font=f, fill=colour_for(a))
                cx += f.getlength(w + " ")

    if shadow:
        sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        place(ImageDraw.Draw(sh), lambda a: (0, 0, 0, 215), 2, 4)
        layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(layer)
    if highlight:
        asc, desc = f.getmetrics()
        for i, line in enumerate(lines):
            cx = x - line_width(line, f) / 2 if align == "center" else x
            for w, a in line:
                wl = f.getlength(w)
                if a:
                    top = y + i * lh + asc * 0.35
                    d.rectangle((cx - 6, top, cx + wl + 6, y + i * lh + asc + desc * 0.4), fill=highlight)
                cx += f.getlength(w + " ")
    place(d, lambda a: (accent if a and not highlight else fill) + (255,))


def spaced(d, xy, text, f, fill, tracking=4, anchor="la"):
    """Letter-spaced capitals. anchor 'la' (left), 'ma' (centre) or 'ra' (right)."""
    total = sum(f.getlength(c) for c in text) + tracking * (len(text) - 1)
    x, y = xy
    if anchor == "ma":
        x -= total / 2
    elif anchor == "ra":
        x -= total
    for c in text:
        d.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + tracking
    return total


# ---------------------------------------------------------------- shared ---

def _cover_fill(src, w, h):
    from PIL import Image

    r = max(w / src.width, h / src.height)
    fill = src.resize((round(src.width * r), round(src.height * r)), Image.LANCZOS)
    left, top = (fill.width - w) // 2, (fill.height - h) // 2
    return fill.crop((left, top, left + w, top + h))


def _background(path):
    """Artwork for a 1080x1350 card: landscapes stay sharp across the top and
    fade into a blurred fill; portraits fill the frame."""
    from PIL import Image, ImageFilter

    src = Image.open(path).convert("RGB")
    fill = _cover_fill(src, W, H)
    if src.width / src.height >= 1:
        canvas = fill.filter(ImageFilter.GaussianBlur(30))
        band = 820
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
    return fill


def _darken(im, start=0.28, peak=0.95):
    """Ink gradient over the lower part of the image so text sits on calm dark."""
    from PIL import Image

    w, h = im.size
    g = Image.new("L", (1, h))
    for y in range(h):
        f = y / h
        a = 0.06 if f < start else min(peak, 0.06 + (peak - 0.06) * ((f - start) / 0.38) ** 1.1)
        g.putpixel((0, y), int(255 * a))
    return Image.composite(Image.new("RGB", (w, h), INK), im, g.resize((w, h)))


def _series_mark(d, x, y, r=22, colour=ORANGE, width=5):
    """The series' orange slashed circle."""
    d.ellipse((x, y, x + 2 * r, y + 2 * r), outline=colour, width=width)
    d.line((x + 2 * r - 6, y + 4, x + 6, y + 2 * r - 4), fill=colour, width=width)


def _footer(d, colour=GREY, accent=ORANGE, y=H - 92):
    margin = 90
    d.text((margin, y), "THE DROWNED CONCORDAT · BOOK ONE", font=font(SANS, 26), fill=colour)
    d.text((W - margin, y), "HAMISH C. RANNOCH", font=font(SANS_BOLD, 26), fill=accent, anchor="ra")


def _save(im, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out_path, "JPEG", quality=90, optimize=True)


# ------------------------------------------------------- card: artwork ---

def draw_card(text, bg_path, out_path, kicker="OVERHEARD IN THE DELTA", n=0, slide=None):
    """Artwork with a label, a big bold line (accent word in teal) and the
    Book One strap. `slide=(i, total)` adds a carousel counter / swipe cue."""
    from PIL import Image, ImageDraw

    margin = 90
    f, lines, size = fit_rich(text, DISPLAY, W - 2 * margin, 6, range(84, 47, -4))
    lh = int(size * 1.16)
    bottom = H - 250
    y = bottom - lh * len(lines)
    # start the dark gradient well above the label, however tall the text is
    start = min(0.28, max(0.08, (y - 86 - 360) / H))
    im = _darken(_background(bg_path), start=start).convert("RGBA")
    _kicker(im, margin, y - 86, kicker)
    draw_rich(im, margin, y, lines, f, lh, CREAM, TEAL)

    d = ImageDraw.Draw(im)
    rule_y = y + lh * len(lines) + 30
    d.line((margin, rule_y, margin + 90, rule_y), fill=ORANGE, width=5)
    strap = "THE RISE OF THE COVENANT · OUT NOW"
    d.text((margin, rule_y + 22), strap, font=font(SANS_BOLD, 30), fill=CREAM)
    if slide:
        _slide_marks(d, *slide)
    _footer(d)
    _save(im, out_path)


def _kicker(layer, x, y, text, size=30):
    """Series mark plus a letter-spaced orange label, with a soft shadow."""
    from PIL import Image, ImageDraw, ImageFilter

    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    _series_mark(sd, x + 2, y + 3, colour=(0, 0, 0, 230))
    spaced(sd, (x + 64, y + 11), text, font(DISPLAY_BLACK, size), (0, 0, 0, 230), tracking=5)
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(layer)
    _series_mark(d, x, y)
    spaced(d, (x + 62, y + 8), text, font(DISPLAY_BLACK, size), ORANGE, tracking=5)


def _slide_marks(d, i, total):
    """Carousel: 'i / total' top right, and a swipe cue on the first slide."""
    d.rounded_rectangle((W - 190, 50, W - 60, 104), radius=27, fill=(5, 10, 14, 170))
    d.text((W - 125, 77), f"{i} / {total}", font=font(DISPLAY, 30), fill=CREAM, anchor="mm")
    if i == 1:
        spaced(d, (W - 90, H - 182), "SWIPE  →", font(DISPLAY_BLACK, 34), TEAL, tracking=4, anchor="ra")


# ------------------------------------------------ card: Bulwark Notice ---

def _duotone(path, w, h, dark=INK, light=(122, 150, 155)):
    from PIL import Image, ImageOps

    src = _cover_fill(Image.open(path).convert("RGB"), w, h)
    g = ImageOps.autocontrast(ImageOps.grayscale(src), cutoff=2)
    return ImageOps.colorize(g, dark, light)


def _hazard(d, x0, y0, x1, y1, a=ORANGE, b=INK, step=46):
    d.rectangle((x0, y0, x1, y1), fill=b)
    hgt = y1 - y0
    for x in range(x0 - hgt, x1 + hgt, step * 2):
        d.polygon([(x, y1), (x + step, y1), (x + step + hgt, y0), (x + hgt, y0)], fill=a)


def draw_poster(text, bg_path, out_path, n=0):
    """A Bulwark Notice: duotone artwork, orange header, big capitals."""
    from PIL import Image, ImageDraw

    im = _duotone(bg_path, W, H)
    im = Image.blend(im, Image.new("RGB", (W, H), INK), 0.38).convert("RGBA")
    d = ImageDraw.Draw(im)

    # header band
    d.rectangle((0, 0, W, 190), fill=ORANGE)
    _series_mark(d, 70, 52, r=40, colour=INK, width=8)
    spaced(d, (175, 46), "BULWARK NOTICE", font(DISPLAY_BLACK, 72), INK, tracking=3)
    d.text((178, 132), f"NO. {n + 1:03d}  ·  POST IN ALL PUBLIC LEVELS", font=font(SANS_BOLD, 26), fill=INK)
    _hazard(d, 0, 190, W, 216)

    # the line, in capitals, centred in the middle of the poster
    margin = 80
    f, lines, size = fit_rich(text, DISPLAY_BLACK, W - 2 * margin, 7, range(104, 55, -4), upper=True)
    lh = int(size * 1.08)
    block = lh * len(lines)
    y = 216 + (H - 216 - 230 - block) // 2
    draw_rich(im, W // 2, y, lines, f, lh, CREAM, ORANGE, align="center")

    d = ImageDraw.Draw(im)
    d.rectangle((0, H - 230, W, H), fill=(5, 10, 14, 235))
    _hazard(d, 0, H - 230, W, H - 214)
    spaced(d, (W // 2, H - 180), "BY ORDER OF THE COUNCIL", font(DISPLAY_BLACK, 34), ORANGE, tracking=6, anchor="ma")
    d.text((W // 2, H - 132), "THE RISE OF THE COVENANT · OUT NOW", font=font(SANS_BOLD, 28), fill=CREAM, anchor="ma")
    _footer(d, y=H - 72)
    _save(im, out_path)


# ------------------------------------------------- card: Council record ---

def _paper(w, h, seed):
    from PIL import Image, ImageChops, ImageFilter

    rnd = random.Random(seed)
    base = Image.new("RGB", (w, h), PAPER)
    noise = Image.effect_noise((w, h), 22).filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")
    im = Image.blend(base, ImageChops.multiply(base, noise), 0.22)
    # vignette and a couple of fold marks
    vig = Image.radial_gradient("L").resize((w, h))
    im = Image.composite(Image.new("RGB", (w, h), (150, 138, 112)), im, vig.point(lambda v: int(v * 0.55)))
    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    fy = h // 2 + rnd.randint(-40, 40)
    d.line((0, fy, w, fy + rnd.randint(-6, 6)), fill=(200, 190, 168), width=3)
    return im


def draw_record(text, bg_path, out_path, n=0):
    """A redacted Council record, typed on paper, with a clipped photo."""
    from PIL import Image, ImageDraw

    im = _paper(W, H, n).convert("RGBA")
    d = ImageDraw.Draw(im)
    mono_s, mono_l = font(MONO, 26), font(MONO, 30)
    m = 90

    d.text((m, 84), "COUNCIL RECORD", font=font(MONO, 50), fill=TYPE_INK)
    d.text((m, 146), "RESTRICTED · NOT FOR CIRCULATION", font=mono_s, fill=TYPE_INK)
    d.line((m, 196, W - m, 196), fill=TYPE_INK, width=3)

    rows = [("FILE", f"DLT-{(n * 379) % 9000 + 1000}"), ("LEVEL", "THE DELTA"), ("SUBJECT", None), ("STATUS", "UNDER REVIEW")]
    rnd = random.Random(n * 7 + 1)
    for i, (k, v) in enumerate(rows):
        yy = 230 + i * 52
        d.text((m, yy), f"{k:<8}", font=mono_s, fill=TYPE_INK)
        if v:
            d.text((m + 170, yy), v, font=mono_s, fill=TYPE_INK)
        else:
            d.rectangle((m + 170, yy - 2, m + 170 + rnd.randint(200, 300), yy + 30), fill=(18, 16, 14))

    # clipped photo, slightly tilted
    photo = _cover_fill(Image.open(bg_path).convert("RGB"), 330, 250)
    from PIL import ImageOps

    photo = ImageOps.expand(photo, border=14, fill=(244, 240, 230)).convert("RGBA")
    photo = photo.rotate(-4, expand=True, resample=Image.BICUBIC)
    im.alpha_composite(photo, (W - m - photo.width + 20, 196))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((W - m - 205, 186, W - m - 175, 262), radius=10, outline=(120, 120, 125), width=5)

    # the line, typed, accent words marked with a highlighter stripe
    y = 520
    d.text((m, y - 60), "EXTRACT:", font=mono_s, fill=TYPE_INK)
    f, lines, size = fit_rich(text, MONO, W - 2 * m, 7, range(46, 29, -2))
    lh = int(size * 1.42)
    draw_rich(im, m, y, lines, f, lh, TYPE_INK, TYPE_INK, shadow=False, highlight=(236, 128, 52, 150))

    # redacted lines below
    d = ImageDraw.Draw(im)
    yy = y + lh * len(lines) + 40
    for _ in range(3):
        if yy > H - 300:
            break
        x = m
        while x < W - m - 60:
            wlen = rnd.randint(60, 220)
            if rnd.random() < 0.7:
                d.rectangle((x, yy, min(x + wlen, W - m), yy + 30), fill=(18, 16, 14))
            else:
                d.text((x, yy), "x" * max(1, wlen // 18), font=mono_s, fill=(110, 102, 92))
            x += wlen + 18
        yy += 54

    # stamp
    stamp = Image.new("RGBA", (520, 150), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle((6, 6, 514, 144), radius=12, outline=STAMP_RED + (220,), width=8)
    spaced(sd, (260, 34), "CLASSIFIED", font(DISPLAY_BLACK, 74), STAMP_RED + (220,), tracking=6, anchor="ma")
    stamp = stamp.rotate(12, expand=True, resample=Image.BICUBIC)
    im.alpha_composite(stamp, (W - stamp.width - 70, H - 470))

    d = ImageDraw.Draw(im)
    d.line((m, H - 140, W - m, H - 140), fill=TYPE_INK, width=2)
    d.text((m, H - 118), "THE RISE OF THE COVENANT · OUT NOW", font=font(SANS_BOLD, 28), fill=TYPE_INK)
    _footer(d, colour=(90, 84, 76), accent=STAMP_RED, y=H - 74)
    _save(im, out_path)


# ------------------------------------------------- card: ration label ---

def draw_ration(text, bg_path, out_path, n=0):
    """A gel ration label on a blurred, dark Delta backdrop."""
    from PIL import Image, ImageDraw, ImageFilter

    bg = _cover_fill(Image.open(bg_path).convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(26))
    im = Image.blend(bg, Image.new("RGB", (W, H), INK), 0.62).convert("RGBA")

    lx0, ly0, lx1, ly1 = 120, 90, W - 120, H - 190
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((lx0 + 12, ly0 + 20, lx1 + 12, ly1 + 20), fill=(0, 0, 0, 200))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
    d = ImageDraw.Draw(im)
    d.rectangle((lx0, ly0, lx1, ly1), fill=(242, 238, 228))
    m = lx0 + 40
    r = lx1 - 40

    d.text((m, ly0 + 30), "GEL RATION", font=font(DISPLAY_BLACK, 92), fill=INK)
    d.text((m, ly0 + 138), "VAT-GROWN  ·  STANDARD ISSUE", font=font(SANS_BOLD, 28), fill=INK)
    d.rectangle((m, ly0 + 186, r, ly0 + 202), fill=INK)

    rows = [("Ration no.", f"{(n * 7919) % 900000 + 100000}"),
            ("Origin", "Vat"),
            ("Grown in soil", "0%"),
            ("Calories", "Counted")]
    f_row, f_val = font(SANS, 32), font(SANS_BOLD, 32)
    yy = ly0 + 222
    for k, v in rows:
        d.text((m, yy), k, font=f_row, fill=INK)
        d.text((r, yy), v, font=f_val, fill=INK, anchor="ra")
        yy += 52
        d.line((m, yy - 8, r, yy - 8), fill=INK, width=2)
    d.rectangle((m, yy + 4, r, yy + 14), fill=INK)

    # the line in the notice box
    yy += 44
    d.rectangle((m, yy, m + 190, yy + 46), fill=ORANGE)
    d.text((m + 95, yy + 23), "NOTICE", font=font(DISPLAY_BLACK, 30), fill=INK, anchor="mm")
    yy += 74
    box_bottom = ly1 - 190
    f, lines, size = fit_rich(text, DISPLAY, r - m, 6, range(58, 31, -2))
    lh = int(size * 1.2)
    draw_rich(im, m, yy, lines, f, lh, INK, ORANGE, shadow=False)

    # barcode
    d = ImageDraw.Draw(im)
    rnd = random.Random(n + 99)
    bx, by = m, ly1 - 150
    x = bx
    while x < bx + 360:
        wbar = rnd.choice((3, 3, 5, 7))
        d.rectangle((x, by, x + wbar - 1, by + 92), fill=INK)
        x += wbar + rnd.choice((3, 4, 6))
    d.text((bx, by + 100), "DELTA SUPPLY · KEEP DRY", font=font(SANS, 22), fill=INK)
    _series_mark(d, r - 64, by + 10, r=32, colour=ORANGE, width=7)

    d.text((W // 2, ly1 + 40), "THE RISE OF THE COVENANT · OUT NOW", font=font(SANS_BOLD, 30), fill=CREAM, anchor="ma")
    _footer(d)
    _save(im, out_path)


# ------------------------------------------------------ cover end cards ---

def draw_amazon_card(headline, cover_path, out_path, slide=None, subline="Find it on Amazon · link in caption"):
    """Book One cover on a blurred version of itself, with a Kindle call to action."""
    from PIL import Image, ImageDraw, ImageFilter

    cover = Image.open(cover_path).convert("RGB")
    bg = _cover_fill(cover, W, H).filter(ImageFilter.GaussianBlur(40))
    im = Image.blend(bg, Image.new("RGB", (W, H), INK), 0.72)

    ch = 860
    c = cover.resize((round(cover.width * ch / cover.height), ch), Image.LANCZOS)
    cx, cy = (W - c.width) // 2, 70
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((cx + 10, cy + 18, cx + c.width + 10, cy + ch + 18), fill=(0, 0, 0, 190))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    im.paste(shadow, (0, 0), shadow)
    im.paste(c, (cx, cy))

    im = im.convert("RGBA")
    d = ImageDraw.Draw(im)
    y = cy + ch + 50
    spaced(d, (W // 2, y), headline.upper(), font(DISPLAY_BLACK, 46), ORANGE, tracking=4, anchor="ma")
    d.text((W // 2, y + 72), "The Rise of the Covenant", anchor="ma", font=font(SERIF_IT, 58), fill=CREAM)
    d.text((W // 2, y + 152), subline, anchor="ma", font=font(SANS, 28), fill=GREY)
    if slide:
        _slide_marks(d, *slide)
    _footer(d)
    _save(im, out_path)


def draw_website_card(headline, bg_path, out_path):
    """Delta artwork with a headline and the website address."""
    from PIL import ImageDraw

    im = _darken(_background(bg_path)).convert("RGBA")
    margin = 90
    f, lines, size = fit_rich(headline, DISPLAY, W - 2 * margin, 3, range(92, 55, -4))
    lh = int(size * 1.14)
    y = H - 330 - lh * len(lines)
    _kicker(im, margin, y - 86, "THE OFFICIAL SITE")
    draw_rich(im, margin, y, lines, f, lh, CREAM, TEAL)
    d = ImageDraw.Draw(im)
    rule_y = y + lh * len(lines) + 28
    d.line((margin, rule_y, margin + 90, rule_y), fill=ORANGE, width=5)
    d.text((margin, rule_y + 26), "THEDROWNEDCONCORDAT.COM", font=font(DISPLAY_BLACK, 52), fill=ORANGE)
    d.text((margin, rule_y + 98), "The books · the world · the author", font=font(SANS, 30), fill=CREAM)
    _footer(d)
    _save(im, out_path)


# ---------------------------------------------------- weekly link posts ---
# Extra posts on top of the daily quote card: Wednesday points to the website,
# Saturday to Amazon. Each has a few headline/caption variants that rotate weekly.

WEBSITE_POSTS = [
    ("Step inside the *Delta*.",
     "Step inside the world of The Drowned Concordat: the Delta, the Bulwark and the books. 🌊"),
    ("New to the Delta? *Start here.*",
     "New to The Drowned Concordat? The series, the world and the author, all in one place."),
    ("The world behind the *wall*.",
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


# ------------------------------------------------------------ carousels ---
# Swipeable posts, Mondays and Fridays. Every slide is premise-level, taken from
# lines.txt; the last slide is always the Book One cover.

CAROUSELS = [
    {
        "slides": [
            ("WELCOME TO THE DELTA", "Five hundred million people. Not one meal grown in *soil*."),
            ("THE WALL", "On one side, the ocean. On the other, everyone who *survived* it."),
            ("THE FOOD", "Breakfast is gel. Lunch is gel. Dinner is *gel*."),
            ("THE PEOPLE IN CHARGE", "The Council keeps the Delta fed. The Enforcers keep it *quiet*."),
        ],
        "caption": "New here? A quick tour of the Delta, the drowned world of The Drowned Concordat. Swipe through 👉",
        "prompt": "💬 Which side of the Bulwark would you want to live on? 👇",
    },
    {
        "slides": [
            ("TWO SISTERS", "Two sisters. One drowned world. Two very different ideas of how to *save* it."),
            ("ELARA", "Dr. Elara Di Canti keeps a drowned hemisphere *fed*."),
            ("BECCA", "Her sister Becca still believes the future grows in *soil*."),
            ("THE QUESTION", "What would you believe in, if your next meal *depended* on it?"),
        ],
        "caption": "Meet the two sisters at the heart of The Drowned Concordat. Swipe through 👉",
        "prompt": "💬 Team Elara or Team Becca? 👇",
    },
    {
        "slides": [
            ("LIFE BEHIND THE BULWARK", "Four things every citizen of the Delta *knows*."),
            ("1 · THE WALL", "The Bulwark is not a wall, the engineers will tell you. Everyone calls it the *wall* anyway."),
            ("2 · THE RATION", "Every ration bar has a number. So does *everyone* who eats one."),
            ("3 · THE BILGE", "Below the towers lies the Bilge, where the water never quite *leaves*."),
            ("4 · THE RULE", "Hunger is a solved problem in the Delta. *Officially.*"),
        ],
        "caption": "Life behind the Bulwark, in four rules. Swipe through 👉",
        "prompt": "💬 Which rule would you break first? 👇",
    },
]


def build_carousel(index, stamp, run):
    c = CAROUSELS[index % len(CAROUSELS)]
    bgs = load_backgrounds()
    total = len(c["slides"]) + 1
    paths = []
    for i, (kicker, text) in enumerate(c["slides"], start=1):
        p = GENERATED / f"{stamp}-carousel-{run}-{i}.jpg"
        draw_card(text, bgs[(index * 3 + i) % len(bgs)], p, kicker=kicker, slide=(i, total))
        paths.append(p)
    p = GENERATED / f"{stamp}-carousel-{run}-{total}.jpg"
    draw_amazon_card("Start with Book One", COVERS[index % len(COVERS)], p, slide=(total, total))
    paths.append(p)
    caption = f"{c['caption']}\n\n{c['prompt']}\n\n{CALLS_TO_ACTION[0]}\n\n{HASHTAGS}"
    return paths, caption


# ------------------------------------------------------------ daily reel ---
# A 12-second 1080x1920 video for Instagram Reels, YouTube Shorts and TikTok:
# the artwork drifts, a water line rises behind the text, a low ambient sound
# bed (wind, swell and drone, all generated, so no licensing) plays under it,
# and the last two seconds show the Book One cover. Text sits clear of the
# areas the apps cover with their own buttons (right edge, bottom fifth).

VW, VH, FPS = 1080, 1920, 30
QUOTE_SECONDS, END_SECONDS = 10, 2
SECONDS = QUOTE_SECONDS + END_SECONDS
REEL_OFFSET = 20  # use a different line/background from the same day's photo card
SAFE_BOTTOM = 1480


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


def _reel_text_layer(text, kicker):
    """Transparent layers: (kicker, everything else) so the kicker can flicker."""
    from PIL import Image, ImageDraw

    body = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    kick = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    left, max_w = 80, 860  # leave the right edge for the apps' buttons
    f, lines, size = fit_rich(text, DISPLAY, max_w, 6, range(84, 51, -4))
    lh = int(size * 1.16)
    block = 90 + lh * len(lines) + 140
    y = max(940, SAFE_BOTTOM - block)

    _kicker(kick, left, y, kicker, size=32)
    y += 90
    draw_rich(body, left, y, lines, f, lh, CREAM, TEAL)
    d = ImageDraw.Draw(body)
    rule_y = y + lh * len(lines) + 30
    d.line((left, rule_y, left + 90, rule_y), fill=ORANGE + (255,), width=5)
    d.text((left, rule_y + 24), "THE RISE OF THE COVENANT · OUT NOW", font=font(SANS_BOLD, 32), fill=CREAM + (255,))
    d.text((left, rule_y + 72), "THE DROWNED CONCORDAT · HAMISH C. RANNOCH", font=font(SANS, 26), fill=ORANGE + (255,))
    return kick, body


def _reel_end_card(cover_path):
    from PIL import Image, ImageDraw, ImageFilter

    cover = Image.open(cover_path).convert("RGB")
    bg = _cover_fill(cover, VW, VH).filter(ImageFilter.GaussianBlur(45))
    im = Image.blend(bg, Image.new("RGB", (VW, VH), INK), 0.74)
    ch = 960
    c = cover.resize((round(cover.width * ch / cover.height), ch), Image.LANCZOS)
    cx, cy = (VW - c.width) // 2, 200
    sh = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((cx + 12, cy + 22, cx + c.width + 12, cy + ch + 22), fill=(0, 0, 0, 200))
    im.paste(sh.filter(ImageFilter.GaussianBlur(26)), (0, 0), sh.filter(ImageFilter.GaussianBlur(26)))
    im.paste(c, (cx, cy))
    d = ImageDraw.Draw(im)
    y = cy + ch + 60
    spaced(d, (VW // 2, y), "START WITH BOOK ONE", font(DISPLAY_BLACK, 52), ORANGE, tracking=5, anchor="ma")
    d.text((VW // 2, y + 80), "The Rise of the Covenant", anchor="ma", font=font(SERIF_IT, 64), fill=CREAM)
    d.text((VW // 2, y + 170), "Out now on Kindle", anchor="ma", font=font(SANS_BOLD, 34), fill=GREY)
    return im


def _water(t, top=760, height=560):
    """Translucent teal water rising behind the text; returns (layer, y)."""
    import math

    from PIL import Image, ImageDraw

    layer = Image.new("RGBA", (VW, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    level = height - 60 - (height - 180) * _ease(t)  # rises from near the bottom
    phase = t * 6.0
    pts = [(x, level + 10 * math.sin(x / 150 + phase) + 5 * math.sin(x / 61 - phase * 1.7)) for x in range(0, VW + 12, 12)]
    d.polygon(pts + [(VW, height), (0, height)], fill=TEAL + (46,))
    d.line(pts, fill=TEAL + (150,), width=3)
    pts2 = [(x, y + 26) for x, y in pts]
    d.line(pts2, fill=TEAL + (60,), width=2)
    return layer, top


AUDIO_FILTER = (
    "[1:a]lowpass=f=650,highpass=f=45,tremolo=f=0.15:d=0.75,volume=0.55[surf];"
    "[2:a]volume=0.22,tremolo=f=0.21:d=0.5[d1];"
    "[3:a]volume=0.10,tremolo=f=0.13:d=0.6[d2];"
    "[surf][d1][d2]amix=inputs=3:normalize=0,"
    f"afade=t=in:d=1.2,afade=t=out:st={SECONDS - 1.8}:d=1.8,"
    "volume=2.5,alimiter=limit=0.9,aformat=channel_layouts=stereo[a]"
)


def draw_reel(text, bg_path, out_path, kicker="OVERHEARD IN THE DELTA", cover_path=None):
    import subprocess

    from PIL import Image, ImageFilter

    src = Image.open(bg_path).convert("RGB")
    landscape = src.width / src.height >= 1

    # static, blurred, very dark fill behind everything
    fill = _cover_fill(src, VW, VH).filter(ImageFilter.GaussianBlur(40))
    base = Image.blend(fill, Image.new("RGB", (VW, VH), INK), 0.7)

    # darkening gradient so the text area is calm
    grad = Image.new("L", (1, VH))
    start = 0.42 if landscape else 0.36
    for y in range(VH):
        f = y / VH
        grad.putpixel((0, y), int(255 * (0.0 if f < start else min(0.9, 0.9 * ((f - start) / 0.2)))))
    grad = grad.resize((VW, VH))
    ink = Image.new("RGB", (VW, VH), INK)

    if landscape:
        band_h, band_y = 1000, 110
        s = band_h / src.height
        band = src.resize((round(src.width * s), band_h), Image.LANCZOS)
        travel = max(0, band.width - VW)
        mask = Image.new("L", (VW, band_h), 255)
        for y in range(band_h):
            a = min(1.0, y / 110, (band_h - y) / 260)
            mask.paste(int(255 * max(0.0, a)), (0, y, VW, y + 1))
    else:
        s = max(VW / src.width, VH / src.height)

    kick, body = _reel_text_layer(text, kicker)
    kick_dim = kick.copy()
    kick_dim.putalpha(kick.getchannel("A").point(lambda v: v * 35 // 100))
    end = _reel_end_card(cover_path or COVERS[0])
    flicker = {7, 8, 13, 21, 22}  # frames where the label flickers (frame 0 stays clean for the thumbnail)

    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.6:r=44100:d={SECONDS}",
           "-f", "lavfi", "-i", f"sine=frequency=55:sample_rate=44100:duration={SECONDS}",
           "-f", "lavfi", "-i", f"sine=frequency=82.41:sample_rate=44100:duration={SECONDS}",
           "-filter_complex", AUDIO_FILTER, "-map", "0:v", "-map", "[a]",
           "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    quote_frames = FPS * QUOTE_SECONDS
    fade = int(FPS * 0.4)
    last_quote = None
    for i in range(FPS * SECONDS):
        if i < quote_frames:
            t = i / (quote_frames - 1)
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
            frame = Image.composite(ink, frame, grad).convert("RGBA")
            water, wy = _water(t)
            frame.alpha_composite(water, (0, wy))
            frame.alpha_composite(kick_dim if i in flicker else kick)
            frame.alpha_composite(body)
            frame = frame.convert("RGB")
            last_quote = frame
        else:
            k = i - quote_frames
            frame = Image.blend(last_quote, end, min(1.0, (k + 1) / fade)) if k < fade else end
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")


def youtube_title(text, limit=100):
    """YouTube titles: max 100 characters, no < or >. Ends with #Shorts."""
    suffix = " #Shorts"
    clean = plain(text).replace("<", "").replace(">", "")
    room = limit - len(suffix)
    if len(clean) > room:
        clean = clean[: room - 1].rsplit(" ", 1)[0].rstrip(",.;:—- ") + "…"
    return clean + suffix


# ------------------------------------------------------------------ steps ---

def post_kind():
    """Which post to make. The workflow sets POST_KIND (and POST_SLOT for quote cards) from the schedule that fired."""
    kind = os.environ.get("POST_KIND", "").strip().lower()
    return kind if kind in {"quote", "reel", "website", "amazon", "carousel"} else "quote"


START = datetime(2026, 10, 22, tzinfo=timezone.utc)  # day 0 of the quote rotation


def day_number(now=None):
    """Days since START. Drives the rotation, so extra runs never skip a quote.

    POST_DATE=YYYY-MM-DD (set by a manual run) makes the run produce that day's
    posts instead, e.g. to catch up on a day the scheduler skipped.
    """
    forced = os.environ.get("POST_DATE", "").strip()
    if forced and now is None:
        now = datetime.strptime(forced, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
        print(f"Catch-up run: making the posts for {forced}")
    return ((now or datetime.now(timezone.utc)) - START).days


def kicker_for(fmt, n):
    return PITCH_KICKER if fmt == "pitch" else KICKERS[n % len(KICKERS)]


def draw_quote(line, bg, out_path, n):
    fmt, text = parse_line(line)
    if fmt == "poster":
        draw_poster(text, bg, out_path, n=n)
    elif fmt == "record":
        draw_record(text, bg, out_path, n=n)
    elif fmt == "ration":
        draw_ration(text, bg, out_path, n=n)
    else:
        draw_card(text, bg, out_path, kicker=kicker_for(fmt, n), n=n)
    return fmt, text


# ------------------------------------------------------ test and learn ---
# strategy.json holds the current mix: how often each card design is used and a
# short list of proven lines that get repeated more often. A weekly review
# (tools/analyze.py) rewrites it from real Instagram results. Every post is
# logged to log/posts.csv so results can be matched back to what was posted.

STRATEGY_FILE = ROOT / "strategy.json"
LOG_FILE = ROOT / "log" / "posts.csv"
DEFAULT_STRATEGY = {
    "format_weights": {"card": 1.0, "poster": 1.0, "record": 1.0, "ration": 1.0, "pitch": 0.5},
    "favourite_lines": [],
    "favourite_share": 0.25,
}


def load_strategy():
    try:
        data = json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = dict(DEFAULT_STRATEGY)
    out.update({k: v for k, v in data.items() if k in DEFAULT_STRATEGY})
    return out


def post_slot():
    slot = os.environ.get("POST_SLOT", "").strip().lower()
    return slot if slot in {"am", "pm"} else "pm"


def choose_quote(n, slot):
    """Pick (line, background, cta, prompt_index) for a quote card.

    The card design is drawn at random using the strategy's weights, so every
    design keeps being tested while the winners appear more often. Some posts
    reuse a proven line instead. Lines of each design rotate in order.
    """
    lines, bgs = load_lines(), load_backgrounds()
    strat = load_strategy()
    off = 1 if slot == "am" else 0
    k = n * 2 + off  # one step per quote post
    rng = random.Random(f"{n}-{slot}")

    favs = [l for l in lines if plain(parse_line(l)[1]) in set(strat["favourite_lines"])]
    if favs and rng.random() < float(strat["favourite_share"]):
        line = favs[k % len(favs)]
    else:
        by_fmt = {}
        for l in lines:
            by_fmt.setdefault(parse_line(l)[0], []).append(l)
        fmts = [f for f in by_fmt if strat["format_weights"].get(f, 1.0) > 0]
        weights = [strat["format_weights"].get(f, 1.0) for f in fmts]
        fmt = rng.choices(fmts, weights=weights)[0]
        cands = by_fmt[fmt]
        line = cands[(n + off * 3) % len(cands)]
    return line, bgs[k % len(bgs)], CALLS_TO_ACTION[k % len(CALLS_TO_ACTION)], k


def log_post(slot, kind, fmt, line, caption):
    """Append one row to log/posts.csv (kept in the repo)."""
    import csv

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["posted_utc", "slot", "kind", "format", "line", "caption_start"])
        start = " ".join(caption.split())[:60]
        w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), slot, kind, fmt, plain(line), start])


def build(n=None, kind=None):
    if n is None:
        n = day_number()
    kind = kind or post_kind()
    week = n // 7
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run = os.environ.get("GITHUB_RUN_NUMBER", "local")
    card = GENERATED / f"{stamp}-{kind}-{run}.jpg"
    prompt = COMMENT_PROMPTS[n % len(COMMENT_PROMPTS)]
    paths = None

    if kind == "website":
        headline, body = WEBSITE_POSTS[week % len(WEBSITE_POSTS)]
        bg = load_backgrounds()[week % len(load_backgrounds())]
        draw_website_card(headline, bg, card)
        caption, source = f"{body}\n\n🔗 {WEBSITE_URL}\n\n{HASHTAGS}", bg.name
        log_fmt, log_line = "website", headline
    elif kind == "reel":
        line, bg, cta = pick(n + REEL_OFFSET)
        fmt, text = parse_line(line)
        card = card.with_suffix(".mp4")
        draw_reel(text, bg, card, kicker=kicker_for(fmt, n), cover_path=COVERS[week % len(COVERS)])
        caption, source = f"{plain(text)}\n\n{prompt}\n\n{cta}\n\n{HASHTAGS} #Shorts", bg.name
        title = youtube_title(text)
        log_fmt, log_line = "reel", text
    elif kind == "amazon":
        headline, body = AMAZON_POSTS[week % len(AMAZON_POSTS)]
        cover = COVERS[week % len(COVERS)]
        draw_amazon_card(headline, cover, card)
        caption, source = f"{body}\n\n🔗 {AMAZON_URL}\n\n{HASHTAGS}", cover.name
        log_fmt, log_line = "amazon", headline
    elif kind == "carousel":
        # Mondays and Fridays: two carousels a week, rotating through CAROUSELS
        index = week * 2 + (1 if datetime.now(timezone.utc).weekday() >= 3 else 0)
        paths, caption = build_carousel(index, stamp, run)
        card, source = paths[0], f"carousel {index % len(CAROUSELS) + 1}"
        log_fmt, log_line = f"carousel-{index % len(CAROUSELS) + 1}", CAROUSELS[index % len(CAROUSELS)]["slides"][0][1]
    else:
        slot = post_slot()
        card = GENERATED / f"{stamp}-{kind}-{slot}-{run}.jpg"
        line, bg, cta, k = choose_quote(n, slot)
        fmt, text = draw_quote(line, bg, card, k)
        prompt = COMMENT_PROMPTS[k % len(COMMENT_PROMPTS)]
        caption, source = f"{plain(text)}\n\n{prompt}\n\n{cta}\n\n{HASHTAGS}", f"{bg.name} ({fmt})"
        log_fmt, log_line = fmt, text

    # keep only the most recent cards and videos
    for pattern, keep in (("*.jpg", KEEP_CARDS), ("*.mp4", KEEP_VIDEOS)):
        for p in sorted(GENERATED.glob(pattern))[:-keep]:
            p.unlink()

    if os.environ.get("GITHUB_ACTIONS") == "true":
        log_post(post_slot() if kind == "quote" else "-", kind, log_fmt, log_line, caption)

    post = {
        "kind": kind,
        "text": caption,
        "image_path": card.relative_to(ROOT).as_posix(),
        "background": source,
    }
    if paths:
        post["image_paths"] = [p.relative_to(ROOT).as_posix() for p in paths]
    if kind == "reel":
        post["title"] = title
    POST_FILE.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Post #{n + 1} ({kind})\nCaption:\n{caption}\nSource: {source}\nFile: {post['image_path']}")
    return post


def _head_ok(url):
    import requests

    try:
        r = requests.head(url, timeout=20, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code == 200 and not r.headers.get("content-type", "").startswith("text/"):
        return r
    return None


def public_url(path, sha):
    """Find a public link Instagram/YouTube can fetch, in order of reliability:
    1. GitHub Pages (if enabled for the repo) - waits for the new file to deploy
    2. jsDelivr pinned to the commit - can refuse files once the repo passes 50 MB
    3. GitHub raw - works, but serves videos with a generic type
    """
    pages_on = _head_ok(PAGES_BASE + "fonts/FreeSerifItalic.ttf") is not None
    candidates = []
    if pages_on:
        candidates.append((PAGES_BASE + path, 600))
    if sha:
        candidates.append((CDN_BASE.format(sha=sha) + path, 120))
    candidates.append((RAW_BASE + path, 180))

    for url, timeout in candidates:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = _head_ok(url)
            if r:
                print(f"Public: {url} ({r.headers.get('content-type')}, {r.headers.get('content-length')} bytes)")
                return url
            time.sleep(15)
        print(f"Not reachable, trying next host: {url}")
    raise RuntimeError(f"File never became public: {path}")


def post():
    import requests

    data = json.loads(POST_FILE.read_text(encoding="utf-8"))
    sha = os.environ.get("PUBLISHED_SHA", "").strip()
    kind = data.get("kind", "quote")

    if kind == "carousel":
        urls = [public_url(p, sha) for p in data["image_paths"]]
        payload = {"kind": "carousel", "text": data["text"], "image_urls": urls,
                   # ready-made list for Make's Instagram "Create a carousel post" module
                   "files": [{"media_type": "IMAGE", "image_url": u} for u in urls]}
        # numbered fields too, for mapping into Make's carousel module slot by slot
        for i, u in enumerate(urls, start=1):
            payload[f"image_url_{i}"] = u
        payload["slide_count"] = len(urls)
        print(f"Caption:\n{data['text']}\nSlides:\n" + "\n".join(urls))
        if os.environ.get("CAROUSELS_ENABLED", "").lower() == "false":
            print("Carousels are switched off (repo variable CAROUSELS_ENABLED=false). Not sending to Make.")
            return
    else:
        image_url = public_url(data["image_path"], sha)
        print(f"Caption:\n{data['text']}\nImage: {image_url}")
        payload = {"kind": kind, "text": data["text"]}
        if data.get("title"):
            payload["title"] = data["title"]
        if data.get("synthetic"):
            payload["synthetic"] = "true"  # AI-animated content: Make sets the YouTube AI-disclosure flag
        if image_url.endswith(".mp4"):
            payload["video_url"] = image_url
            payload["file_name"] = data["image_path"].rsplit("/", 1)[-1]
        else:
            payload["image_url"] = image_url

    if os.environ.get("DRY_RUN", "").lower() == "true":
        print("Dry run: files are public, not sending to Make.")
        return
    webhook_url = os.environ.get("SOCIAL_WEBHOOK_URL")
    if not webhook_url:
        print("Webhook URL not found. Running in test mode.")
        return
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
