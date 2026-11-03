# The Drowned Concordat — promo automation

Automated social posting for *The Drowned Concordat* (Hamish C. Rannoch) and the KingMonkai Cycling channel.
GitHub Actions builds every image and video here; a Make.com scenario does the actual posting.

```
GitHub Actions (build card / video) ──commit──▶ repo ──GitHub Pages URL──▶ Make webhook ──▶ Instagram / YouTube / Google Drive
```

Instagram and YouTube fetch each file from this repo's **GitHub Pages** site, which is why finished media is
committed to `generated/` (old files are pruned automatically). The Make webhook URL lives in the
`SOCIAL_WEBHOOK_URL` Actions secret; no tokens or keys are kept in tracked files.

## What posts, and when

Times are UTC (Amsterdam = UTC+1 in winter, +2 in summer). GitHub's scheduler often runs late, and occasionally skips a run.

| Workflow | Schedule | Posts | Make route |
|---|---|---|---|
| `autopost.yml` | daily 06:47, 15:51 | quote cards (morning / evening) | Instagram photo |
| `autopost.yml` | daily 11:41 | Reel | Instagram Reel + YouTube Short (Hamish) + Drive copy for TikTok |
| `autopost.yml` | Mon & Fri 09:43 | carousel | Instagram carousel |
| `autopost.yml` | Wed 09:43 / Sat 09:43 | website card / Amazon card | Instagram photo |
| `autopost.yml` | 14, 15, 21, 22 Nov 12:13 + 20:13 | free-Kindle-day promo Reels | as Reel |
| `autopost.yml` | daily 10:23, 17:23 | a card for each newly published website Dispatch (nothing if there's none) | Instagram photo |
| `author-post.yml` | Tue, Thu, Sat 16:37 | next "Hamish talks about the book" episode from the queue | as Reel (YouTube flagged AI-generated) |
| `author-render.yml` | nightly 01:23 | renders episodes ahead, keeping up to 4 in `author/rendered/` | — |
| `zwift-post.yml` (on branch `zwift-media`) | on push | KingMonkai Zwift Shorts and photo slideshows | YouTube (KingMonkai) |

The Zwift Shorts and cycling slideshows are started by two Claude scheduled tasks on the Mac
(nightly 21:13 and Sun/Wed 19:17 Amsterdam time), because the clips and photos live on the Mac.

**Manual runs:** every workflow can be started from the Actions tab. In `autopost.yml`, *dry_run* builds and
publishes the file without sending it to Make, and *date* re-makes the posts for a missed day (YYYY-MM-DD).

## Book promo (`auto_poster.py`)

- `lines.txt` — the quote lines, one per post, Book One only and spoiler-free. A leading tag picks the card
  design (`[card]`, `[poster]`, `[record]`, `[ration]`, `[pitch]`); `*asterisks*` mark the accent word.
- `strategy.json` — tuning knobs: `format_weights` (how often each card design is used),
  `favourite_lines` and `favourite_share` (best performers repeated on that share of quote posts).
  Rewritten by `tools/analyze.py`.
- `backgrounds/`, `images/`, `fonts/` — artwork, covers, animated Delta clips and type used by the cards and Reels.
- Dispatches: the `dispatch` run reads the website's RSS feed (thedrownedconcordat.com/dispatches/feed.xml) and
  shares the newest Dispatch not yet listed in `log/dispatches_posted.txt` (posts older than 10 days are skipped).
  Merging a weekly Dispatch PR on the website repo is the only approval: it goes out on Instagram at the next check.
- `log/posts.csv` — one row per post (time, slot, kind, format, line, caption start). Kept in the repo:
  the rotation and the weekly review read it.
- `FREE_DAYS` in `auto_poster.py` — dates of Kindle free promotions (US Pacific time). Captions get a
  countdown line before, "FREE today" on the days, and a review nudge after.

**Weekly review:** run the Make scenario *Instagram stats pull (on demand)* (≈8 Make credits a run), then
`python tools/analyze.py stats/raw/<date>.txt`. It scores posts by engagement rate (saves and shares weighted
highest), updates `strategy.json` and writes `stats/report-<date>.md`.

## Hamish author Shorts (`author/`)

- `episodes.json` — the series. Each episode: Hamish's standard intro on camera, a Delta clip under the
  voiceover, Hamish closes. `post_on` pins an episode to a date (e.g. free-weekend specials).
- `make_episode.py` — `voice` (Kokoro "bm_fable" voice + effects), `compose` (captions, framing, AI label),
  `post` (takes the next ready episode from the queue). Lip-sync is Wav2Lip, run in the render workflow.
- `rendered/` — the queue of finished episodes; `posted.txt` — what has gone out.
- `tools/narrate.py` + `narrate.yml` — one-off narration in Hamish's voice for other videos.
- `voice-samples.yml`, `voice-audition.yml`, `wav2lip-sample.yml` — test tools for voices and lip-sync;
  results go to `author-media-*` branches.

## KingMonkai Cycling (`zwift/`)

- `make_and_post.py` + `zwift_short.py` — joins a ride day's Zwift clips into a vertical Short with a hook
  from `hooks.txt` and a rotating track from the Mac's Music folder.
- `slideshow.py` + `slideshows.json` — photo slideshow Shorts, one per trip; `outros/` holds end clips.
- Posting works by force-pushing a single commit to the `zwift-media` branch, whose workflow sends it to
  Make. `posted.txt` / `slideshows_posted.txt` record what has gone out.

## Make credits

Normal running uses about 16 credits a day (quote card 2, Reel 5, Zwift Short 3, author Short 5, slideshow 3).
Checking run history in Make costs nothing; only scenario runs use credits.

## Known housekeeping

The repo is ~690 MB, mostly the long explainer videos in `images/` and the rendered episodes. History grows
by roughly 60–80 MB a month from committed media. Planned fix (after the November promotion): publish media
from a separate, squashed `media` branch served by GitHub Pages, so `main` stops accumulating video history.
