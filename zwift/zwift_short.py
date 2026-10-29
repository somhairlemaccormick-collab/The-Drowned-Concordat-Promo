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
FONT_M = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"
ORANGE = (252, 102, 0)


def overlay_png(path, title, sub):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fb = ImageFont.truetype(FONT_B, 92)
    fm = ImageFont.truetype(FONT_M, 50)
    # wrap title to 2 lines max
    words, lines, cur = title.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fb) > W - 120 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    y = 150 if len(lines) == 1 else 90
    for ln in lines[:2]:
        d.text((W / 2, y), ln, font=fb, fill="white", anchor="ma",
               stroke_width=4, stroke_fill=(0, 0, 0, 160))
        y += 110
    d.rectangle([W / 2 - 70, y + 20, W / 2 + 70, y + 30], fill=ORANGE)
    d.text((W / 2, y + 60), sub, font=fm, fill=(235, 235, 235), anchor="ma")
    img.save(path)


def build(out, title, sub, clips):
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
            f"[s{i}c]crop=230:200:0:0,scale=440:-2[pp{i}];"
            f"[bg{i}][sq{i}]overlay=0:500[t{i}];"
            f"[t{i}][pp{i}]overlay=(W-w)/2:1600[v{i}];"
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];"
        )
    n = len(clips)
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac];"
    fc = "".join(parts) + concat + f"[vc][{n}:v]overlay=0:0[vo]"
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-i", png,
           "-filter_complex", fc, "-map", "[vo]", "-map", "[ac]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
