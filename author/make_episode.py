#!/usr/bin/env python3
"""Build one "Hamish talks about the book" Short (1080x1920, ~30 s).

Structure: Hamish on camera (open) -> a Delta clip under his voice (voiceover) -> Hamish on camera (close).
Run by .github/workflows/author-short.yml in three steps:

  python author/make_episode.py voice   [--id EPISODE]  # picks the episode, writes work/*.wav + work/plan.json
  (SadTalker animates work/portrait.jpg with work/open.wav and work/close.wav -> work/open.mp4, work/close.mp4)
  python author/make_episode.py compose                  # stitches it all, burns captions, writes post.json

Episodes live in author/episodes.json; posted ones are listed in author/posted.txt.
"""
import argparse, json, os, re, subprocess, sys, wave
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
AUTHOR = ROOT / "author"
WORK = ROOT / "work"
W, H = 1080, 1920
ORANGE = (236, 128, 52)
FONT_B = ROOT / "fonts" / "InterDisplay-ExtraBold.otf"
VOICE_FX = ("aresample=44100,rubberband=pitch=0.93:formant=preserved,bass=g=5:f=110:w=0.8,"
            "equalizer=f=320:t=q:w=1.2:g=1.5,equalizer=f=3500:t=q:w=1.5:g=-1.5,"
            "asoftclip=type=tanh:threshold=0.7,lowpass=f=8500,"
            "acompressor=threshold=0.15:ratio=2.5:attack=10:release=150")
GAP = 0.38  # pause between sentences, seconds


def run(*cmd):
    subprocess.run(cmd, check=True)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?:])\s+", text) if s.strip()]


def wav_len(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def font(size):
    for p in (FONT_B, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- step 1: voice
def voice(args):
    episodes = json.loads((AUTHOR / "episodes.json").read_text(encoding="utf-8"))
    posted_file = AUTHOR / "posted.txt"
    done = set(posted_file.read_text().split()) if posted_file.exists() else set()
    if args.id:
        ep = next(e for e in episodes if e["id"] == args.id)
    else:
        left = [e for e in episodes if e["id"] not in done]
        if not left:
            sys.exit("NO_EPISODES_LEFT")
        ep = left[0]
    WORK.mkdir(exist_ok=True)
    spk = json.load(open(args.model + ".json"))["speaker_id_map"][args.speaker]
    plan = {"episode": ep, "parts": {}}
    for part in ("open", "voiceover", "close"):
        pieces, timings, t = [], [], 0.0
        for i, s in enumerate(sentences(ep[part])):
            raw = WORK / f"{part}-{i}-raw.wav"
            p = subprocess.run([args.piper, "--model", args.model, "--speaker", str(spk),
                                "--length_scale", str(args.pace), "--output_file", str(raw)],
                               input=s.encode(), check=True, capture_output=True)
            fx = WORK / f"{part}-{i}.wav"
            run("ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", VOICE_FX, "-ac", "1", "-ar", "44100", str(fx))
            d = wav_len(fx)
            timings.append({"text": s, "start": round(t, 3), "end": round(t + d, 3)})
            pieces.append(fx)
            t += d + GAP
        # join sentences with short silences
        lst = WORK / f"{part}.txt"
        sil = WORK / "gap.wav"
        run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(GAP), str(sil))
        lst.write_text("".join(f"file '{p.name}'\nfile 'gap.wav'\n" for p in pieces))
        out = WORK / f"{part}.wav"
        run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "pcm_s16le", str(out))
        # SadTalker wants 16 kHz
        run("ffmpeg", "-v", "error", "-y", "-i", str(out), "-ar", "16000", str(WORK / f"{part}-16k.wav"))
        plan["parts"][part] = {"duration": round(wav_len(out), 3), "captions": timings}
    # portrait, scaled down so the CPU animation finishes in reasonable time
    im = Image.open(AUTHOR / ep["portrait"]).convert("RGB")
    im.thumbnail((720, 900))
    im.save(WORK / "portrait.jpg", quality=95)
    (WORK / "plan.json").write_text(json.dumps(plan, indent=1))
    print(f"Episode {ep['id']}: " + ", ".join(f"{k} {v['duration']}s" for k, v in plan["parts"].items()))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"episode={ep['id']}\n")


# ---------------------------------------------------------------- step 2: compose
def caption_png(text, path):
    img = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(58)
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if cur and d.textlength(t, font=f) > W - 160:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    y = 420 - len(lines) * 74 - 20
    for ln in lines:
        d.text((W / 2, y), ln, font=f, fill="white", anchor="ma", stroke_width=5, stroke_fill=(0, 0, 0, 235))
        y += 74
    img.save(path)


def frame_png(title, path):
    """Top kicker + AI label, constant over the whole video."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(260):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(170 * (1 - y / 260))))
    d.text((W / 2, 92), "HAMISH C. RANNOCH", font=font(40), fill=ORANGE, anchor="ma")
    d.text((W / 2, 150), title.upper(), font=font(52), fill="white", anchor="ma",
           stroke_width=4, stroke_fill=(0, 0, 0, 220))
    d.text((W - 30, H - 40), "AI-animated narrator", font=font(26), fill=(255, 255, 255, 150), anchor="rs")
    img.save(path)


def compose(args):
    plan = json.loads((WORK / "plan.json").read_text())
    ep = plan["episode"]
    parts = plan["parts"]
    segs = []
    for part in ("open", "voiceover", "close"):
        dur = parts[part]["duration"] + 0.25
        seg = WORK / f"seg-{part}.mp4"
        if part == "voiceover":
            src = ["-stream_loop", "-1", "-i", str(ROOT / "images" / ep["cutaway"])]
            vf = (f"[0:v]scale=-2:{H},crop={W}:{H},gblur=sigma=30,eq=brightness=-0.2[bg];"
                  f"[0:v]crop=720:720,scale=1080:1080,setsar=1[fg];[bg][fg]overlay=0:360,fps=30[v]")
        else:
            src = ["-i", str(WORK / f"{part}.mp4")]
            vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30,"
                  f"eq=brightness=-0.2[bg];[0:v]scale={W}:-2,setsar=1[fg];[bg][fg]overlay=0:(H-h)/2-60,fps=30[v]")
        run("ffmpeg", "-v", "error", "-y", *src, "-i", str(WORK / f"{part}.wav"), "-filter_complex", vf,
            "-map", "[v]", "-map", "1:a", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-af", "apad", str(seg))
        segs.append((seg, dur))

    # join the three segments
    lst = WORK / "segs.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s, _ in segs))
    joined = WORK / "joined.mp4"
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined))

    # captions + frame
    frame_png(ep["title"], WORK / "frame.png")
    inputs, chain, t0, k = ["-i", str(joined), "-i", str(WORK / "frame.png")], "[0:v][1:v]overlay=0:0[c0]", 0.0, 0
    for (part, (seg, dur)) in zip(("open", "voiceover", "close"), segs):
        for c in parts[part]["captions"]:
            k += 1
            png = WORK / f"cap{k}.png"
            caption_png(c["text"], png)
            inputs += ["-i", str(png)]
            a, b = t0 + c["start"], t0 + c["end"] + 0.25
            chain += f";[c{k - 1}][{k + 1}:v]overlay=0:1380:enable='between(t,{a:.2f},{b:.2f})'[c{k}]"
        t0 += dur
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = ROOT / "generated" / f"{stamp}-author-{ep['id']}.mp4"
    out.parent.mkdir(exist_ok=True)
    run("ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", chain, "-map", f"[c{k}]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart", str(out))

    caption = (f"{ep['title']}. {ep['open']}\n\n"
               "The Drowned Concordat, Book One, is out now on Kindle (link in bio).\n\n"
               "Hamish is an AI-animated narrator voicing the author's words.\n\n"
               "#TheDrownedConcordat #scifi #dystopia #climatefiction #booktok #bookstagram #kindle #Shorts")
    post = {"kind": "reel", "text": caption, "title": f"{ep['title']} | The Drowned Concordat",
            "image_path": out.relative_to(ROOT).as_posix(), "background": ep["cutaway"], "synthetic": True}
    (ROOT / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(AUTHOR / "posted.txt", "a") as f:
        f.write(ep["id"] + "\n")
    print("Built", out, f"{sum(d for _, d in segs):.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["voice", "compose"])
    ap.add_argument("--id")
    ap.add_argument("--piper", default="piper/piper")
    ap.add_argument("--model", default="vctk.onnx")
    ap.add_argument("--speaker", default="p281")
    ap.add_argument("--pace", type=float, default=1.25)
    a = ap.parse_args()
    voice(a) if a.step == "voice" else compose(a)
