"""Split portfolio_videos.json into long-form vs Shorts.

YouTube's /watch page canonical is not sufficient on its own: newly published
Shorts sometimes temporarily canonicalise to /watch. Combine it with the
Shorts-only ``oar2.jpg`` portrait thumbnail. A video is long-form only when a
normal watch canonical and an absent Shorts thumbnail agree. If YouTube cannot
confirm both signals temporarily, show the video provisionally under Shorts
and retry it on the next refresh. Then write:
  - portfolio_longform.json / portfolio_shorts.json  (fetched by portfolio.html)
  - portfolio_data.js  (same data as window globals, so the page still works
    when opened via file:// where fetch() is blocked)

Re-run after refreshing portfolio_videos.json with scrape_portfolio.py.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.join(os.path.dirname(__file__), "..")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "shorts_cache.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    # Skips the consent.youtube.com interstitial
    "Cookie": "SOCS=CAI; CONSENT=YES+cb.20220301-11-p0.en+FX+700",
}
CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)"')
LENGTH = re.compile(r'"lengthSeconds":"(\d+)"')
CONFIRMED_KINDS = {"short", "long"}
SHORT_KINDS = {"short", "provisional_short"}
TRUSTED_SOURCES = {
    "canonical",
    "shorts_thumbnail",
    "canonical+shorts_thumbnail_absent",
}

# Successful lookups are cached so reruns only fetch new videos —
# YouTube rate-limits aggressive full sweeps with 429s.
try:
    CACHE = json.load(open(CACHE_PATH, encoding="utf-8-sig"))
except (FileNotFoundError, json.JSONDecodeError):
    CACHE = {}

# Purge poisoned or malformed entries. Older versions cached failed lookups as
# long-form with no duration, which made a transient request failure permanent.
def trusted_cache_entry(entry):
    """Accept legacy entries with a duration and new entries with proof."""
    return (
        entry.get("kind") in CONFIRMED_KINDS
        and (
            isinstance(entry.get("duration"), int)
            or entry.get("source") in TRUSTED_SOURCES
        )
    )


_poisoned = [
    vid for vid, entry in CACHE.items()
    if not trusted_cache_entry(entry)
]
for vid in _poisoned:
    del CACHE[vid]
if _poisoned:
    print(f"Purged {len(_poisoned)} poisoned cache entries: {', '.join(_poisoned)}")


def fetch_watch_page(vid):
    """GET the watch page, retrying with backoff on 429."""
    req = urllib.request.Request(
        f"https://www.youtube.com/watch?v={vid}", headers=HEADERS
    )
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                wait = 20 * attempt
                print(f"  ~ {vid}: 429, retrying in {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            raise


def fetch_shorts_thumbnail_state(vid):
    """Return True for a Shorts-only portrait thumbnail, False for 404.

    YouTube serves ``oar2.jpg`` for Shorts but returns 404 for standard
    videos. Other failures are inconclusive and must not promote a video to
    long-form.
    """
    req = urllib.request.Request(
        f"https://i.ytimg.com/vi/{vid}/oar2.jpg",
        headers=HEADERS,
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        print(f"  ? {vid}: Shorts thumbnail returned HTTP {e.code}")
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ? {vid}: Shorts thumbnail check failed: {e}")
        return None


def classify(video):
    """Return a classification and duration in seconds, when available.

    Confirmed canonical results are cached. A video with a usable ID but an
    inconclusive lookup is returned as provisional_short, displayed under
    Shorts, and retried next run because provisional results are never cached.
    Only a video without a usable ID remains unknown and omitted.
    """
    vid = video.get("youtube_id")
    if not vid:
        return "unknown", None
    cached = CACHE.get(vid)
    if cached and trusted_cache_entry(cached):
        return cached["kind"], cached["duration"]
    time.sleep(0.8)  # stay under YouTube's rate limit

    html = None
    try:
        html = fetch_watch_page(vid)
    except Exception as e:
        print(f"  ? {vid}: watch-page check failed: {e}")

    dm = LENGTH.search(html) if html else None
    duration = int(dm.group(1)) if dm else None
    m = CANONICAL.search(html) if html else None
    canonical = m.group(1) if m else None
    thumbnail_state = fetch_shorts_thumbnail_state(vid)

    # A Shorts canonical or Shorts-only portrait thumbnail is affirmative
    # evidence. The thumbnail check deliberately overrides a normal watch
    # canonical because YouTube now emits that incomplete combination for
    # some newly published Shorts.
    if canonical and "/shorts/" in canonical:
        kind, source = "short", "canonical"
    elif thumbnail_state is True:
        kind, source = "short", "shorts_thumbnail"
    elif canonical and thumbnail_state is False:
        kind, source = "long", "canonical+shorts_thumbnail_absent"
    else:
        print(f"  ? {vid}: incomplete YouTube signals -> provisional Short")
        return "provisional_short", duration

    CACHE[vid] = {"kind": kind, "duration": duration, "source": source}
    return kind, duration


def page_entry(v, duration, kind):
    """Schema consumed by portfolio.html. Shorts get their portrait
    thumbnail (oar2.jpg) and a /shorts/ URL."""
    vid = v.get("youtube_id")
    if kind in SHORT_KINDS and vid:
        url = f"https://www.youtube.com/shorts/{vid}"
        thumb = f"https://i.ytimg.com/vi/{vid}/oar2.jpg"
    else:
        url = v.get("youtube_url")
        thumb = v.get("thumbnail", "")
    return {
        "id": str(v.get("ytjobs_id") or ""),
        "title": v.get("title", ""),
        "youtube_id": vid,
        "youtube_url": url,
        "thumbnail": thumb,
        "views_formatted": v.get("views_formatted"),
        "channel_title": v.get("channel_name"),
        "channel_id": None,
        "duration": duration,
    }


def main():
    src = json.load(
        open(os.path.join(BASE, "portfolio_videos.json"), encoding="utf-8")
    )
    videos = src["all_videos"]
    # YTJobs lists newest first; its ids ascend over time
    videos.sort(key=lambda v: int(v.get("ytjobs_id") or 0), reverse=True)

    cached = sum(1 for v in videos if v.get("youtube_id") in CACHE)
    print(f"Classifying {len(videos)} videos via YouTube signals ({cached} cached)...")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(classify, videos))

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(CACHE, f)
    confirmed = sum(1 for v in videos if v.get("youtube_id") in CACHE)
    print(f"  cache now holds {confirmed}/{len(videos)} confirmed classifications")

    longform = [page_entry(v, d, k) for v, (k, d) in zip(videos, results) if k == "long"]
    shorts = [page_entry(v, d, k) for v, (k, d) in zip(videos, results) if k in SHORT_KINDS]
    provisional = [v for v, (k, _) in zip(videos, results) if k == "provisional_short"]
    unknown = [v for v, (k, _) in zip(videos, results) if k == "unknown"]
    print(
        f"  long-form: {len(longform)}  shorts: {len(shorts)} "
        f"(provisional: {len(provisional)})  omitted: {len(unknown)}"
    )
    for v in provisional:
        print(f"    provisional Short, retry next run: {v.get('title', '')[:60]}")
    for v in unknown:
        print(f"    omitted (missing YouTube ID): {v.get('title', '')[:60]}")
    for s in shorts[:20]:
        print(f"    short: {s['title'][:60]}")

    lf_doc = {"total": len(longform), "videos": longform}
    sh_doc = {"total": len(shorts), "videos": shorts}

    with open(os.path.join(BASE, "portfolio_longform.json"), "w", encoding="utf-8") as f:
        json.dump(lf_doc, f, indent=1, ensure_ascii=False)
    with open(os.path.join(BASE, "portfolio_shorts.json"), "w", encoding="utf-8") as f:
        json.dump(sh_doc, f, indent=1, ensure_ascii=False)

    js = (
        "// Generated by scripts/split_portfolio.py — fallback data for file:// "
        "where fetch() is unavailable\n"
        f"window.PORTFOLIO_LONGFORM = {json.dumps(lf_doc, ensure_ascii=False)};\n"
        f"window.PORTFOLIO_SHORTS = {json.dumps(sh_doc, ensure_ascii=False)};\n"
    )
    with open(os.path.join(BASE, "portfolio_data.js"), "w", encoding="utf-8") as f:
        f.write(js)

    print("Wrote portfolio_longform.json, portfolio_shorts.json, portfolio_data.js")


if __name__ == "__main__":
    main()
