#!/usr/bin/env python3
"""Photo slideshow Shorts for KingMonkai Cycling, one per topic in slideshows.json.

  python3 zwift/slideshow.py --photos DIR --list
  python3 zwift/slideshow.py --photos DIR --preview OUT.mp4 [--topic ID] [--music DIR]   # build only
  python3 zwift/slideshow.py --photos DIR [--topic ID] [--music DIR] [--privacy unlisted]  # build + post

Without --topic it takes the next topic not yet in slideshows_posted.txt.
Each photo gets ~3 s with a slow pan (landscape) or slow zoom (portrait/square) over a blurred
copy of itself, 0.4 s crossfades, and the same headline style as the Zwift Shorts.
An outro clip from zwift/outros/ is crossfaded onto the end, rotating through the folder in name
order (a topic can pin one with "outro": "<file name>"). Clips are stored ready-made at 1080x1920,
30 fps, no audio; music runs over the whole Short. Pass --no-outro to leave it off.
"""
import argparse, json, os, subprocess, sys, tempfile
from PIL import Image, ImageFilter, ImageOps, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from zwift_short import overlay_png, W, H  # noqa: E402
import make_and_post as mp  # noqa: E402

TOPICS = os.path.join(HERE, "slideshows.json")
POSTED = os.path.join(HERE, "slideshows_posted.txt")
OUTROS = os.path.join(HERE, "outros")


def pick_outro(topic, n_posted):
    if not os.path.isdir(OUTROS):
        return None
    clips = sorted(x for x in os.listdir(OUTROS) if x.lower().endswith(".mp4"))
    if topic.get("outro") in clips:
        return os.path.join(OUTROS, topic["outro"])
    return os.path.join(OUTROS, clips[n_posted % len(clips)]) if clips else None
FPS, SECS, FADE = 30, 3.0, 0.4
PH = 1200  # height of the photo band (centre of the screen)
TOP = 510  # photo band starts below the headline


def prep(path):
    """Return (background, foreground, mode) for one photo, scaled once."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    bg = ImageOps.fit(im, (W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    if im.width / im.height > W / PH * 1.15:  # landscape: fill the band's height and pan across
        fg = im.resize((round(im.width * PH / im.height), PH), Image.LANCZOS)
        return bg, fg, "pan"
    # portrait / square: fit the band, zoom slowly
    s = min(W / im.width, PH / im.height) * 1.12
    fg = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return bg, fg, "zoom"


def frame(bg, fg, mode, t):
    """t from 0 to 1 across the photo's time on screen."""
    f = bg.copy()
    if mode == "pan":
        x = round((fg.width - W) * t)
        f.paste(fg.crop((x, 0, x + W, PH)), (0, TOP))
    else:
        z = 1 + 0.08 * t
        w, h = round(fg.width / 1.12 * z), round(fg.height / 1.12 * z)
        g = fg.resize((w, h), Image.BILINEAR)
        cx, cy = (w - min(w, W)) // 2, (h - min(h, PH)) // 2
        g = g.crop((cx, cy, cx + min(w, W), cy + min(h, PH)))
        f.paste(g, ((W - g.width) // 2, TOP + (PH - g.height) // 2))
    return f


def probe_dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path]).decode().strip())


def render(out, photos, hook, sub, music=None, outro=None):
    tmp = tempfile.mkdtemp()
    ov_path = os.path.join(tmp, "ov.png")
    overlay_png(ov_path, hook, sub)
    ov = Image.open(ov_path)
    slides = [prep(p) for p in photos]
    n = round(SECS * FPS)
    fade = round(FADE * FPS)
    total = len(slides) * n
    dur = total / FPS
    slides_out = os.path.join(tmp, "slides.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", slides_out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i, (bg, fg, mode) in enumerate(slides):
        for k in range(n):
            # each slide's motion spans its own time plus the fade into the next
            img = frame(bg, fg, mode, k / (n + fade))
            if k >= n - fade and i + 1 < len(slides):
                nb, nf, nm = slides[i + 1]
                a = (k - (n - fade) + 1) / (fade + 1)
                img = Image.blend(img, frame(nb, nf, nm, 0), a)
            img = img.convert("RGBA")
            img.alpha_composite(ov)
            p.stdin.write(img.convert("RGB").tobytes())
    p.stdin.close()
    if p.wait():
        sys.exit("ffmpeg failed")

    # Join the outro (if any) with a crossfade, then lay the music over the full length.
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", slides_out]
    if outro:
        cmd += ["-i", outro]
        cmd += ["-filter_complex", f"[0:v]fps={FPS},settb=1/{FPS},setsar=1[s];[1:v]fps={FPS},scale={W}:{H},settb=1/{FPS},setsar=1[o];"
                f"[s][o]xfade=transition=fade:duration={FADE}:offset={dur - FADE:.3f},format=yuv420p[v]"]
        vmap = "[v]"
        dur = dur + probe_dur(outro) - FADE
    else:
        vmap = "0:v"
    nin = 2 if outro else 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        cmd += ["-map", vmap, "-map", f"{nin}:a",
                "-af", f"atrim=0:{dur:.3f},afade=t=in:d=0.5,afade=t=out:st={dur - 2:.3f}:d=2",
                "-c:a", "aac", "-b:a", "160k", "-t", f"{dur:.3f}"]
    else:
        cmd += ["-map", vmap]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out]
    if subprocess.call(cmd):
        sys.exit("ffmpeg failed (final mux)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", required=True)
    ap.add_argument("--topic")
    ap.add_argument("--music")
    ap.add_argument("--preview")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-outro", action="store_true")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    a = ap.parse_args()

    topics = json.load(open(TOPICS, encoding="utf-8"))
    done = set(open(POSTED).read().split()) if os.path.exists(POSTED) else set()
    if a.list:
        for t in topics:
            print(("posted  " if t["id"] in done else "waiting ") + t["id"], len(t["photos"]), "photos")
        return
    if a.topic:
        t = next(t for t in topics if t["id"] == a.topic)
    else:
        left = [t for t in topics if t["id"] not in done]
        if not left:
            print("All slideshows posted.")
            return
        t = left[0]
    photos = [os.path.join(a.photos, f) for f in t["photos"]]
    missing = [p for p in photos if not os.path.exists(p)]
    if missing:
        sys.exit(f"Missing photos: {missing}")

    track = mp.pick_track(a.music, "2026-01-01") if a.music else None
    if track and a.music:  # rotate by how many slideshows have gone out
        tracks = sorted(x for x in os.listdir(a.music) if x.lower().endswith((".mp3", ".m4a", ".wav", ".aac", ".ogg")))
        track = os.path.join(a.music, tracks[len(done) % len(tracks)])
    out = a.preview or os.path.join(tempfile.mkdtemp(), f"slides-{t['id']}.mp4")
    outro = None if a.no_outro else pick_outro(t, len(done))
    print(f"Building {t['id']}: {len(photos)} photos, ~{len(photos) * SECS:.0f}s"
          + (f" + outro {os.path.basename(outro)}" if outro else ""))
    render(out, photos, t["hook"], t["sub"], music=track, outro=outro)
    if a.preview:
        print("Preview written:", out)
        return

    plain = t["hook"].replace("*", "")
    text = f"{plain}\n\n{t['description']}"
    if t.get("credit"):
        text += f"\n\n📸 {t['credit']}"
    if track:
        credit = os.path.splitext(track)[0] + ".txt"
        if os.path.exists(credit):
            text += "\n\nMusic: " + open(credit).read().strip()
    text += "\n\n" + " ".join(t["tags"])
    fname = f"slides-{t['id']}.mp4"
    # The outro clips are AI-generated (Gemini), so tell YouTube via Make's containsSyntheticMedia.
    mp.publish(out, fname, f"{plain} 🚴 #shorts", text, a.privacy, f"Slideshow {t['id']}",
               extra={"synthetic": True} if outro else None)
    mp.record(POSTED, t["id"], f"Slideshow posted: {t['id']}")
    print("Done:", t["id"])


if __name__ == "__main__":
    main()
