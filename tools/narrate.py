#!/usr/bin/env python3
"""Render Hamish's narration (Kokoro bm_fable + the author-Shorts voice effects) for arbitrary text.

Usage: python tools/narrate.py OUTDIR "part one text" "part two text" ...
Writes OUTDIR/partN.wav (44.1 kHz mono) and OUTDIR/timings.json with per-part duration and caption chunks.
Used by .github/workflows/narrate.yml for one-off videos that aren't standard author episodes.
"""
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "author"))
from make_episode import VOICE_FX, GAP, sentences, caption_chunks, wav_len, run  # noqa: E402

import numpy as np, soundfile as sf  # noqa: E402
from kokoro import KPipeline  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
kp = KPipeline(lang_code="b")
sil = out / "gap.wav"
run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(GAP), str(sil))
result = []
for n, text in enumerate(sys.argv[2:], 1):
    pieces, caps, t = [], [], 0.0
    for i, s in enumerate(sentences(text)):
        raw = out / f"p{n}-{i}-raw.wav"
        audio = np.concatenate([np.asarray(a) for _, _, a in kp(s, voice="bm_fable", speed=0.92)])
        sf.write(str(raw), audio, 24000)
        fx = out / f"p{n}-{i}.wav"
        run("ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", VOICE_FX, "-ac", "1", "-ar", "44100", str(fx))
        raw.unlink()
        d = wav_len(fx)
        caps += caption_chunks(s, t, d)
        pieces.append(fx)
        t += d + GAP
    lst = out / f"p{n}.txt"
    lst.write_text("".join(f"file '{p.name}'\nfile 'gap.wav'\n" for p in pieces))
    wav = out / f"part{n}.wav"
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "pcm_s16le", str(wav))
    for p in pieces:
        p.unlink()
    lst.unlink()
    result.append({"text": text, "duration": round(wav_len(wav), 3), "captions": caps})
sil.unlink()
(out / "timings.json").write_text(json.dumps(result, indent=1))
print(json.dumps([(r["duration"]) for r in result]))
