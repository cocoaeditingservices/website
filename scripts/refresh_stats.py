"""Refresh website data from the YTJobs portfolio profile.

YTJobs server-renders the profile data into the page HTML as JSON, so a plain
HTTP request is enough — no browser needed. Run daily via a scheduled task.

Writes two files the website reads on page load:
    assets/stats.json     -> "Audience Reached" + "Videos Delivered" numbers
    assets/projects.json  -> the 6 most recent portfolio videos (Featured Projects)

If this script fails, the old JSON (or the hardcoded HTML fallback) stays put.
"""
import datetime
import json
import os
import re
import sys
import urllib.request

PROFILE_URL = "https://ytjobs.co/talent/profile/48926"
BASE = os.path.join(os.path.dirname(__file__), "..")
STATS_OUT = os.path.join(BASE, "assets", "stats.json")
PROJECTS_OUT = os.path.join(BASE, "assets", "projects.json")
PROJECT_COUNT = 6

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_html():
    req = urllib.request.Request(PROFILE_URL, headers={"User-Agent": UA})
    try:
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        raise SystemExit(1)


def match_array(s, open_idx):
    """Return the JSON array substring starting at s[open_idx] == '['."""
    depth, i, instr, esc = 0, open_idx, False, False
    while i < len(s):
        c = s[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return s[open_idx:i + 1]
        i += 1
    return None


def write_stats(html, today):
    m = re.search(r'"youtubeVideos":\{"statistics":\{"views":(\d+),"counts":(\d+)', html)
    if not m:
        print("Stats not found — YTJobs layout may have changed.", file=sys.stderr)
        raise SystemExit(1)
    views, videos = int(m.group(1)), int(m.group(2))
    data = {
        "audience_reached": f"{views // 1_000_000}M+",
        "videos_delivered": f"{videos}+",
        "views_raw": views,
        "videos_raw": videos,
        "updated": today,
        "source": PROFILE_URL,
    }
    with open(STATS_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"stats.json   -> {data['audience_reached']} audience, "
          f"{data['videos_delivered']} videos")


def write_projects(html, today):
    anchor = html.find('"youtubeVideos":')
    key = html.find('"videos":[', anchor)
    if anchor == -1 or key == -1:
        print("Portfolio videos not found — skipping projects.json", file=sys.stderr)
        return
    arr = match_array(html, key + len('"videos":'))
    if not arr:
        print("Could not parse videos array — skipping projects.json", file=sys.stderr)
        return
    videos = json.loads(arr)

    out = []
    for v in videos[:PROJECT_COUNT]:
        url = v.get("url", "")
        ytid = ""
        mm = re.search(r"[?&]v=([\w-]+)", url)
        if mm:
            ytid = mm.group(1)
        out.append({
            "title": v.get("title", "").strip(),
            "url": url,
            "views": v.get("abvViews", ""),
            "thumbnail": (f"https://i.ytimg.com/vi/{ytid}/hqdefault.jpg"
                          if ytid else v.get("thumbnail", "")),
        })

    data = {"updated": today, "source": PROFILE_URL, "videos": out}
    with open(PROJECTS_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"projects.json -> {len(out)} most-recent videos")


def main():
    html = fetch_html()
    today = datetime.date.today().isoformat()
    write_stats(html, today)
    write_projects(html, today)


if __name__ == "__main__":
    main()
