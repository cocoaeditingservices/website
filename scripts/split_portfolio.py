"""Split portfolio_videos.json into long-form vs Shorts.

The /watch?v=<id> page carries an authoritative canonical link: real Shorts
canonicalise to /shorts/<id>, long-form videos to /watch?v=<id>. (The
/shorts/<id> URL itself returns a JS shell with no canonical at all, so it
can't be used.) Classify every portfolio video that way, then write:
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

# Successful lookups are cached so reruns only fetch new videos —
# YouTube rate-limits aggressive full sweeps with 429s.
try:
    CACHE = json.load(open(CACHE_PATH, encoding="utf-8-sig"))
except (FileNotFoundError, json.JSONDecodeError):
    CACHE = {}

# Purge poisoned entries: a real classification always has a duration, so a
# cached entry with duration None is a failed lookup that an older classifier
# wrongly persisted (it would otherwise stay misclassified forever, since
# cached videos are never re-fetched). Drop them so they get re-classified.
_poisoned = [vid for vid, e in CACHE.items() if e.get("duration") is None]
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


def classify(video):
    """Return ('short'|'long', duration_seconds|None); 'long' on any failure.

    Only confirmed results are cached, so failed lookups get retried on
    the next run.
    """
    vid = video.get("youtube_id")
    if not vid:
        return "long", None
    cached = CACHE.get(vid)
    if cached and cached.get("duration") is not None:
        return cached["kind"], cached["duration"]
    time.sleep(0.8)  # stay under YouTube's rate limit
    try:
        html = fetch_watch_page(vid)
        dm = LENGTH.search(html)
        duration = int(dm.group(1)) if dm else None
        m = CANONICAL.search(html)
        if m:
            kind = "short" if "/shorts/" in m.group(1) else "long"
            CACHE[vid] = {"kind": kind, "duration": duration}
            return kind, duration
        print(f"  ? {vid}: no canonical found -> defaulting to long-form (uncached)")
        return "long", duration
    except Exception as e:
        print(f"  ! {vid}: {e} -> defaulting to long-form (uncached)")
        return "long", None


def page_entry(v, duration, kind):
    """Schema consumed by portfolio.html. Shorts get their portrait
    thumbnail (oar2.jpg) and a /shorts/ URL."""
    vid = v.get("youtube_id")
    if kind == "short" and vid:
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
    print(f"Classifying {len(videos)} videos via canonical link ({cached} cached)...")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(classify, videos))

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(CACHE, f)
    confirmed = sum(1 for v in videos if v.get("youtube_id") in CACHE)
    print(f"  cache now holds {confirmed}/{len(videos)} confirmed classifications")

    longform = [page_entry(v, d, k) for v, (k, d) in zip(videos, results) if k == "long"]
    shorts = [page_entry(v, d, k) for v, (k, d) in zip(videos, results) if k == "short"]
    print(f"  long-form: {len(longform)}  shorts: {len(shorts)}")
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
