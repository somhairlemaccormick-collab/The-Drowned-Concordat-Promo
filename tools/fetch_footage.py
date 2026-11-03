#!/usr/bin/env python3
"""Find and download free-to-use storm / flood / climate footage for the long-form explainers.

Sources (no API keys needed):
  * NASA Image and Video Library (images-api.nasa.gov) - NASA material is generally not copyrighted;
    credit "NASA". Items whose description names a non-NASA copyright holder are skipped.
  * Wikimedia Commons - only Public Domain, CC0 and CC BY files (credit required for CC BY; no ShareAlike).

Each candidate is trimmed to 15 s from its middle, scaled to 1920x1080 (letter/pillarboxed if needed),
saved as footage/<source>-<slug>.mp4, and listed in footage/credits.csv. A contact sheet
(footage/_contact.jpg) shows a frame of each, for picking.

Usage: python tools/fetch_footage.py OUTDIR "query one" "query two" ...   (env PER_QUERY, default 4)
"""
import csv, json, os, re, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
QUERIES = sys.argv[2:]
PER = int(os.environ.get("PER_QUERY", "4"))
UA = {"User-Agent": "DrownedConcordatFootageFetcher/1.0 (book promo explainer videos)"}
OK_LICENSES = re.compile(r"^(public domain|pd|cc0|cc[- ]?by[- ]?(1\.0|2\.0|2\.5|3\.0|4\.0)?)$", re.I)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


def trim(src, dst):
    """15 s from the middle, 1920x1080, no audio (we narrate over it)."""
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                             capture_output=True, text=True).stdout or 0)
    if d < 4:
        return False
    start = max(0, d / 2 - 7.5) if d > 15 else 0
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", src, "-t", "15", "-an",
                        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", dst])
    return r.returncode == 0


rows, seen = [], set()

def take(source, title, page, credit, licence, url, query):
    name = f"{source}-{slug(title)}"
    if name in seen:
        return
    seen.add(name)
    raw = OUT / f".{name}.raw"
    try:
        raw.write_bytes(get(url))
        if trim(str(raw), str(OUT / f"{name}.mp4")):
            rows.append({"file": f"{name}.mp4", "query": query, "title": title, "source": source,
                         "licence": licence, "credit": credit, "page": page})
            print("ok  ", name)
    except Exception as e:
        print("fail", name, e)
    finally:
        raw.unlink(missing_ok=True)


for q in QUERIES:
    # --- NASA
    try:
        data = json.loads(get("https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": q, "media_type": "video"})))
        n = 0
        for item in data["collection"]["items"]:
            if n >= PER:
                break
            meta = item["data"][0]
            desc = (meta.get("description", "") + " " + meta.get("photographer", "")).lower()
            if "copyright" in desc or "©" in desc or "courtesy of" in desc:
                continue  # third-party material inside NASA's library
            files = json.loads(get(item["href"]))
            mp4 = [f for f in files if f.endswith(".mp4")]
            pick = next((f for f in mp4 if "~medium" in f), None) or next((f for f in mp4 if "~orig" in f), None) or (mp4[0] if mp4 else None)
            if not pick:
                continue
            pick = pick.replace("http://", "https://")
            take("nasa", meta.get("title", meta["nasa_id"]), f"https://images.nasa.gov/details/{urllib.parse.quote(meta['nasa_id'])}",
                 "NASA" + (f" / {meta.get('center')}" if meta.get("center") else ""), "NASA media (not copyrighted)", pick, q)
            n += 1
    except Exception as e:
        print("NASA search failed:", q, e)
    # --- Wikimedia Commons
    try:
        api = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 20,
            "gsrsearch": f"{q} filetype:video", "prop": "imageinfo", "iiprop": "url|extmetadata|mime"})
        pages = json.loads(get(api)).get("query", {}).get("pages", {})
        n = 0
        for p in pages.values():
            if n >= PER:
                break
            ii = (p.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata", {})
            lic = re.sub("<[^>]+>", "", em.get("LicenseShortName", {}).get("value", "")).strip()
            if not OK_LICENSES.match(lic) or "sa" in lic.lower().split("-"):
                continue
            artist = re.sub("<[^>]+>", "", em.get("Artist", {}).get("value", "")).strip() or "Unknown"
            take("commons", p["title"].replace("File:", "").rsplit(".", 1)[0], ii.get("descriptionurl", ""),
                 artist, lic, ii["url"], q)
            n += 1
    except Exception as e:
        print("Commons search failed:", q, e)

with open(OUT / "credits.csv", "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["file", "query", "title", "source", "licence", "credit", "page"])
    if f.tell() == 0:
        w.writeheader()
    w.writerows(rows)

# contact sheet
from PIL import Image, ImageDraw
clips = sorted(OUT.glob("*.mp4"))
if clips:
    W, H, cols = 384, 216, 4
    sheet = Image.new("RGB", (W * cols, (H + 22) * ((len(clips) + cols - 1) // cols)), "white")
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(clips):
        fr = OUT / ".frame.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "6", "-i", str(c), "-frames:v", "1", "-vf", f"scale={W}:{H}", str(fr)])
        x, y = (i % cols) * W, (i // cols) * (H + 22)
        if fr.exists():
            sheet.paste(Image.open(fr), (x, y))
        d.text((x + 3, y + H + 4), c.stem[:58], fill="black")
    sheet.save(OUT / "_contact.jpg", quality=80)
print(len(rows), "clips added")
