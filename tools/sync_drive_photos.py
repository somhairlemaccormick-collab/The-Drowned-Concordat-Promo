#!/usr/bin/env python3
"""Copy new images from the Drive folder "Drowned Concordat Content Photos" into backgrounds/,
where the Instagram cards and Reels pick their artwork.

Images are resized to at most 2160 px on the long side and saved as JPEG (quality 88), named
drive-<original name>.jpg, so the repo stays small. Files already copied are skipped; images removed
from Drive are left in place (delete them from backgrounds/ to retire them).

Names listed in tools/drive_skip.txt are left out (spoilers); finished posts that already carry
text (instagram_post_*) go to ready_posts/ unchanged in layout, to be posted as they are.

Usage: python tools/sync_drive_photos.py DOWNLOAD_DIR
"""
import sys, re
from pathlib import Path
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()  # iPhone .heic photos
except ImportError:
    pass

src = Path(sys.argv[1])
ROOT = Path(__file__).resolve().parent.parent
dst = ROOT / "backgrounds"
ready = ROOT / "ready_posts"
skip = [l.strip().lower() for l in (ROOT / "tools" / "drive_skip.txt").read_text().splitlines()
        if l.strip() and not l.startswith("#")]


def skipped(stem):
    s = stem.lower()
    return any(s.startswith(k[:-1]) if k.endswith("*") else s == k for k in skip)


added = 0
for f in sorted(src.rglob("*")):
    if not f.is_file() or f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        continue
    if f.stem.lower().startswith("instagram_post_"):
        out = ready / (re.sub(r"[^a-z0-9]+", "-", f.stem.lower()).strip("-") + ".jpg")
        if not out.exists():
            ready.mkdir(exist_ok=True)
            im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
            im.thumbnail((2160, 2160), Image.LANCZOS)
            im.save(out, "JPEG", quality=90, optimize=True)
            print("ready post", out.name, im.size)
            added += 1
        continue
    if skipped(f.stem):
        print("skip (listed in drive_skip.txt)", f.name)
        continue
    name = "drive-" + re.sub(r"[^a-z0-9]+", "-", f.stem.lower()).strip("-")[:60] + ".jpg"
    out = dst / name
    if out.exists():
        continue
    try:
        im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
    except Exception as e:
        print("skip", f.name, e)
        continue
    if min(im.size) < 800:
        print("skip (too small for a card)", f.name, im.size)
        continue
    im.thumbnail((2160, 2160), Image.LANCZOS)
    im.save(out, "JPEG", quality=88, optimize=True)
    print("added", name, im.size)
    added += 1
print(f"{added} new image(s)")
