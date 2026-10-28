"""Weekly review of the Instagram promo: what landed, and the new mix.

Usage:
    python tools/analyze.py stats/raw/2026-11-04.txt

The input is the export written to Google Drive by the Make scenario
"Instagram stats pull (on demand)": one line per post per metric,
    post_id|YYYY-MM-DD HH:mm|REELS/FEED|IMAGE/VIDEO/CAROUSEL_ALBUM|metric|value|caption start
(markdown escapes such as \\# or \\_ added by Google Drive are tolerated).

It updates:
  stats/history.csv   latest metrics for every post (one row per post)
  strategy.json       format weights and favourite lines for auto_poster.py
  stats/report-<date>.md  the weekly report (also printed)

Scoring: engagement rate = (likes + 2 x comments + 3 x saves + 3 x shares) / reach.
Saves and shares weigh most because they are the strongest signals that a post
landed with strangers, not just friends. Posts younger than 48 hours are left
out because their numbers are still moving.
"""

import csv
import json
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "log" / "posts.csv"
HISTORY = ROOT / "stats" / "history.csv"
STRATEGY = ROOT / "strategy.json"
METRICS = ["reach", "views", "likes", "comments", "saved", "shares"]
QUOTE_FORMATS = ["card", "poster", "record", "ration", "pitch"]
MIN_POSTS = 4          # posts a design needs before its weight moves
WEIGHT_RANGE = (0.4, 2.5)
MIN_AGE = timedelta(hours=48)


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())[:30]


def er(row):
    reach = max(float(row.get("reach") or 0), 1.0)
    pts = (float(row.get("likes") or 0) + 2 * float(row.get("comments") or 0)
           + 3 * float(row.get("saved") or 0) + 3 * float(row.get("shares") or 0))
    return 100 * pts / reach


def parse_export(path):
    posts = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.replace("\\", "").strip()
        parts = line.split("|", 6)
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        pid, when, product, mtype, metric, value, caption = (p.strip() for p in parts)
        p = posts.setdefault(pid, {"post_id": pid, "posted": when, "product": product,
                                   "media_type": mtype, "caption": caption})
        if metric in METRICS:
            try:
                p[metric] = float(value or 0)
            except ValueError:
                p[metric] = 0.0
    return posts


def load_log():
    if not LOG_FILE.exists():
        return []
    with LOG_FILE.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def match(posts, log):
    """Attach kind/format/line from the post log, matching on caption start."""
    by_caption = {}
    for row in log:
        by_caption.setdefault(norm(row["caption_start"]), []).append(row)
    for p in posts.values():
        rows = by_caption.get(norm(p["caption"]))
        if rows:
            r = rows[-1]
            p.update(kind=r["kind"], format=r["format"], line=r["line"], slot=r["slot"])
    return posts


def load_history():
    if not HISTORY.exists():
        return {}
    with HISTORY.open(encoding="utf-8") as fh:
        return {r["post_id"]: r for r in csv.DictReader(fh)}


def save_history(hist):
    cols = ["post_id", "posted", "product", "media_type", "kind", "format", "slot", "line",
            "caption"] + METRICS
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(hist.values(), key=lambda r: r["posted"]):
            w.writerow(r)


def group_stats(rows):
    return {
        "n": len(rows),
        "reach": statistics.mean(float(r.get("reach") or 0) for r in rows),
        "er": statistics.mean(er(r) for r in rows),
        "saves_shares": statistics.mean(float(r.get("saved") or 0) + float(r.get("shares") or 0) for r in rows),
    }


def main(export_path):
    now = datetime.now(timezone.utc)
    posts = match(parse_export(export_path), load_log())
    hist = load_history()
    for pid, p in posts.items():
        old = hist.get(pid, {})
        merged = {**old, **{k: v for k, v in p.items() if v not in (None, "")}}
        hist[pid] = merged
    save_history(hist)

    def mature(r):
        try:
            t = datetime.strptime(r["posted"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return False
        return now - t >= MIN_AGE

    tracked = [r for r in hist.values() if r.get("format") and mature(r)]
    out = [f"# Promo review {now:%Y-%m-%d}", ""]
    if not tracked:
        out.append("No tracked posts are old enough to judge yet (posts need 48 hours). Nothing changed.")
        report(out, now)
        return

    # by design / kind
    groups = {}
    for r in tracked:
        groups.setdefault(r["format"], []).append(r)
    stats = {g: group_stats(rows) for g, rows in groups.items()}
    out += ["## By post type", "", "| Type | Posts | Avg reach | Engagement % | Saves+shares |", "|---|---|---|---|---|"]
    for g, s in sorted(stats.items(), key=lambda kv: -kv[1]["er"]):
        out.append(f"| {g} | {s['n']} | {s['reach']:.0f} | {s['er']:.1f} | {s['saves_shares']:.1f} |")

    slots = {}
    for r in tracked:
        if r.get("kind") == "quote" and r.get("slot") in ("am", "pm"):
            slots.setdefault(r["slot"], []).append(r)
    if len(slots) == 2:
        a, p = group_stats(slots["am"]), group_stats(slots["pm"])
        out += ["", f"Morning cards: reach {a['reach']:.0f}, engagement {a['er']:.1f}% ({a['n']} posts). "
                    f"Evening cards: reach {p['reach']:.0f}, engagement {p['er']:.1f}% ({p['n']} posts)."]

    ranked = sorted(tracked, key=er, reverse=True)
    out += ["", "## Best posts", ""]
    for r in ranked[:5]:
        out.append(f"- {er(r):.1f}% · reach {float(r.get('reach') or 0):.0f} · {r['format']} · {r.get('line', '')[:70]}")
    out += ["", "## Weakest posts", ""]
    for r in ranked[-3:]:
        out.append(f"- {er(r):.1f}% · reach {float(r.get('reach') or 0):.0f} · {r['format']} · {r.get('line', '')[:70]}")

    # new mix
    strat = json.loads(STRATEGY.read_text(encoding="utf-8"))
    weights = strat["format_weights"]
    quotes = [r for r in tracked if r["format"] in QUOTE_FORMATS]
    changes = []
    if quotes:
        base = statistics.mean(er(r) for r in quotes) or 1.0
        for f in QUOTE_FORMATS:
            rows = [r for r in quotes if r["format"] == f]
            if len(rows) < MIN_POSTS:
                continue
            target = min(max(statistics.mean(er(r) for r in rows) / base, WEIGHT_RANGE[0]), WEIGHT_RANGE[1])
            new = round(0.5 * weights.get(f, 1.0) + 0.5 * target, 2)
            if abs(new - weights.get(f, 1.0)) >= 0.01:
                changes.append(f"{f}: {weights.get(f, 1.0)} → {new}")
            weights[f] = new

        # favourite lines: clearly above typical engagement with at least typical reach
        med_er = statistics.median(er(r) for r in quotes)
        med_reach = statistics.median(float(r.get("reach") or 0) for r in quotes)
        winners = [r for r in quotes if er(r) >= 1.5 * med_er and float(r.get("reach") or 0) >= med_reach]
        favs = list(dict.fromkeys(strat.get("favourite_lines", []) + [r["line"] for r in sorted(winners, key=er, reverse=True)]))
        strat["favourite_lines"] = favs[-6:]

    strat["format_weights"] = weights
    strat["updated"] = f"{now:%Y-%m-%d}"
    STRATEGY.write_text(json.dumps(strat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out += ["", "## New mix", ""]
    out.append("Weight changes: " + ("; ".join(changes) if changes else
               f"none yet (each design needs {MIN_POSTS}+ judged posts before it moves)."))
    out.append("Favourite lines now repeated more often: " +
               ("; ".join(f"“{l[:50]}”" for l in strat["favourite_lines"]) or "none"))
    report(out, now)


def report(lines, now):
    text = "\n".join(lines) + "\n"
    path = ROOT / "stats" / f"report-{now:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python tools/analyze.py <stats export file>")
    main(sys.argv[1])
