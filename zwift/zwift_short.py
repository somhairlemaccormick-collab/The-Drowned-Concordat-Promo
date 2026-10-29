#!/usr/bin/env python3
"""Turn a day's Zwift clips (16:9, ~15 s each) into one vertical 1080x1920 Short.

Usage: python3 zwift_short.py OUT.mp4 "Title line" "Sub line" clip1.mp4 clip2.mp4 ...

Layout, top to bottom:
  title band (text)            0 - 500
  square crop around the rider 500 - 1580 (centre of the frame, HUD top bar included)
  the power/HR panel, enlarged 1600 - 1900
  behind it all: the same clip blurred and darkened.
"""
import subprocess, sys, tempfile, os
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FONT_B = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_X = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
FONT_M = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"
ORANGE = (252, 102, 0)


def _words(title):
    """Split a hook into (word, is_accent) pairs; *asterisks* mark the accent words."""
    out, accent = [], False
    for w in title.split():
        start, end = w.startswith("*"), w.rstrip(".,!?").endswith("*")
        accent = accent or start
        out.append((w.replace("*", "").upper(), accent))
        if end:
            accent = False
    return out


def overlay_png(path, title, sub):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # dark fade behind the headline so it reads over any scenery
    for y in range(520):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * (1 - y / 520))))
    words = _words(title)
    # biggest size that fits in 3 lines
    for size in range(124, 60, -4):
        fb = ImageFont.truetype(FONT_X, size)
        lines, cur = [], []
        for w in words:
            t = " ".join(x for x, _ in cur + [w])
            if cur and d.textlength(t, font=fb) > W - 110:
                lines.append(cur); cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
        if len(lines) <= 3:
            break
    lh = int(size * 1.08)
    y = max(40, (430 - lh * len(lines)) // 2 + 20)
    sp = d.textlength(" ", font=fb)
    for ln in lines:
        x = (W - d.textlength(" ".join(w for w, _ in ln), font=fb)) / 2
        for w, acc in ln:
            d.text((x, y), w, font=fb, fill=ORANGE if acc else "white",
                   stroke_width=6, stroke_fill=(0, 0, 0, 230))
            x += d.textlength(w, font=fb) + sp
        y += lh
    fm = ImageFont.truetype(FONT_M, 40)
    d.text((W / 2, y + 22), sub.upper(), font=fm, fill=(230, 230, 230), anchor="ma",
           stroke_width=3, stroke_fill=(0, 0, 0, 200))
    img.save(path)


def build(out, title, sub, clips, music=None):
    tmp = tempfile.mkdtemp()
    png = os.path.join(tmp, "ov.png")
    overlay_png(png, title, sub)
    inputs, parts = [], []
    for i, c in enumerate(clips):
        inputs += ["-i", c]
        # normalise each clip to 1280x720 first (some come out 1280x644)
        parts.append(
            f"[{i}:v]scale=1280:720,setsar=1,fps=30,split=3[s{i}a][s{i}b][s{i}c];"
            f"[s{i}a]scale=-2:{H},crop={W}:{H},gblur=sigma=28,eq=brightness=-0.18[bg{i}];"
            f"[s{i}b]crop=720:720:280:0,scale=1080:1080[sq{i}];"
            f"[s{i}c]crop=230:200:0:0,scale=380:-2[pp{i}];"
            f"[bg{i}][sq{i}]overlay=0:500[t{i}];"
            f"[t{i}][pp{i}]overlay=(W-w)/2:1590[v{i}];"
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];"
        )
    n = len(clips)
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac];"
    fc = "".join(parts) + concat + f"[vc][{n}:v]overlay=0:0[vo]"
    extra, amap = [], "[ac]"
    if music:
        # music on top, the game sound kept quietly underneath; fade in/out
        dur = 15 * n
        extra = ["-stream_loop", "-1", "-i", music]
        fc += (f";[{n + 1}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{dur},"
               f"afade=t=in:d=1,afade=t=out:st={dur - 2.5}:d=2.5,volume=0.85[mu];"
               f"[ac]volume=0.25[gs];[mu][gs]amix=inputs=2:duration=first:normalize=0[am]")
        amap = "[am]"
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-i", png, *extra,
           "-filter_complex", fc, "-map", "[vo]", "-map", amap, "-shortest",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
