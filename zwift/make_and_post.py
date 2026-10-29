#!/usr/bin/env python3
"""Make one YouTube Short from a day's Zwift clips and send it to the KingMonkai Cycling channel.

  python3 zwift/make_and_post.py --clips DIR            # newest ride day not yet posted
  python3 zwift/make_and_post.py --clips DIR --date 2026-10-27 [--privacy unlisted]
  python3 zwift/make_and_post.py --clips DIR --list     # just show what's waiting

DIR holds Zwift's own clips (Zwift-YYYY-MM-DD-HH-MM-SS.mp4). Posting works by force-pushing an
orphan commit (the video, post.json and the zwift-post workflow) to the zwift-media branch; the
workflow then sends it to Make. The branch only ever holds the latest Short, so the repo stays small.
Posted days are listed in zwift/posted.txt on main.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
POSTED = os.path.join(HERE, "posted.txt")
sys.path.insert(0, HERE)
from zwift_short import build  # noqa: E402

PAT = re.compile(r"Zwift-(\d{4}-\d{2}-\d{2})-(\d{2})-(\d{2})-(\d{2})\.mp4$")
BOT = ["-c", "user.name=github-actions[bot]",
       "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]


def git(*a, cwd=REPO):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def clips_by_day(d):
    days = {}
    for p in sorted(glob.glob(os.path.join(d, "Zwift-*.mp4"))):
        m = PAT.search(os.path.basename(p))
        if m:
            days.setdefault(m.group(1), []).append(p)
    return days


def posted():
    return set(open(POSTED).read().split()) if os.path.exists(POSTED) else set()


def nice(date):
    return datetime.strptime(date, "%Y-%m-%d").strftime("%-d %b %Y")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True)
    ap.add_argument("--date")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    days, done = clips_by_day(a.clips), posted()
    waiting = sorted((d for d in days if d not in done), reverse=True)
    if a.list:
        for d in waiting:
            print(d, len(days[d]), "clips")
        return
    if a.date:
        date = a.date
    else:
        # skip a day whose newest clip is under an hour old: the ride may still be going
        waiting = [d for d in waiting if time.time() - max(os.path.getmtime(p) for p in days[d]) > 3600]
        if not waiting:
            print("Nothing new to post.")
            return
        date = waiting[0]
    clips = days.get(date)
    if not clips:
        sys.exit(f"No clips for {date}")
    clips = clips[:8]  # 8 x 15 s = 2 min, well inside the 3-minute Short limit

    secs = 15 * len(clips)
    title = f"Zwift ride · {nice(date)}"
    yt_title = f"{title} #shorts"
    text = (f"{len(clips)} moment{'s' if len(clips) > 1 else ''} from a ride on Zwift, {nice(date)}.\n\n"
            "#zwift #indoorcycling #cycling #shorts")
    fname = f"zwift-{date}.mp4"

    work = tempfile.mkdtemp()
    out = os.path.join(work, fname)
    print(f"Building {fname} from {len(clips)} clips (~{secs}s)")
    build(out, "Zwift ride", nice(date), clips)

    # orphan commit on zwift-media holding just this Short
    br = os.path.join(work, "branch")
    os.makedirs(os.path.join(br, ".github", "workflows"))
    shutil.move(out, os.path.join(br, fname))
    shutil.copy(os.path.join(HERE, "zwift-post.yml"), os.path.join(br, ".github", "workflows", "zwift-post.yml"))
    json.dump({"title": yt_title, "text": text, "file_name": fname, "privacy": a.privacy},
              open(os.path.join(br, "post.json"), "w"), indent=1)
    url = git("remote", "get-url", "origin").strip()
    git("init", "-q", "-b", "zwift-media", cwd=br)
    git("add", "-A", cwd=br)
    git(*BOT, "commit", "-qm", f"Zwift Short {date}", cwd=br)
    git("push", "-f", url, "zwift-media", cwd=br)
    print("Pushed to zwift-media; GitHub will send it to Make.")

    # record it on main
    git("pull", "-q", "--rebase", "origin", "main")
    with open(POSTED, "a") as f:
        f.write(date + "\n")
    git("add", POSTED)
    git(*BOT, "commit", "-qm", f"Zwift Short posted: {date}")
    git("push", "-q", "origin", "HEAD:main")
    print(f"Done: {date}")


if __name__ == "__main__":
    main()
