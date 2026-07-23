import datetime
import json
import math
import re
import time
import urllib.error
import urllib.request

API_VIDEOS = "https://app.ytjobs.co/api/talents/48926/videos"
API_TALENT = "https://app.ytjobs.co/api/talents/48926?showAll=true"
LIMIT = 15
MAX_ATTEMPTS = 4
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://ytjobs.co/talent/vitrine/48926",
    "Origin": "https://ytjobs.co",
}


def api_get(url):
    """Fetch JSON with bounded retries for transient YTJobs failures."""
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError,
                TimeoutError, json.JSONDecodeError) as exc:
            status = getattr(exc, "code", None)
            transient = status is None or status == 429 or status >= 500
            if not transient or attempt == MAX_ATTEMPTS:
                raise
            wait = 2 ** attempt
            print(f"  YTJobs request failed ({exc}); retrying in {wait}s "
                  f"[{attempt}/{MAX_ATTEMPTS}]", flush=True)
            time.sleep(wait)


def extract_yt_id(url_or_thumb):
    """Extract YouTube video ID from a URL or thumbnail."""
    if not url_or_thumb:
        return None
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url_or_thumb)
    if m:
        return m.group(1)
    m = re.search(r"/vi/([a-zA-Z0-9_-]{11})", url_or_thumb)
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url_or_thumb)
    if m:
        return m.group(1)
    return None


def channel_key(value):
    return str(value) if value is not None else None


def load_existing_videos():
    """Return yesterday's videos for channel-name fallback."""
    try:
        with open("portfolio_videos.json", encoding="utf-8-sig") as f:
            return json.load(f).get("all_videos", [])
    except (OSError, json.JSONDecodeError):
        return []


def add_existing_channel_fallbacks(channel_map, raw_videos, existing_videos):
    """Recover channel metadata when the optional talent endpoint is down."""
    existing_by_ytid = {
        video.get("youtube_id"): video
        for video in existing_videos
        if video.get("youtube_id")
    }
    for raw in raw_videos:
        key = channel_key(raw.get("channelId"))
        if key is None or key in channel_map:
            continue
        yt_id = extract_yt_id(raw.get("url")) or extract_yt_id(raw.get("thumbnail"))
        previous = existing_by_ytid.get(yt_id)
        if not previous or previous.get("channel_name") in {None, "", "Unknown"}:
            continue
        channel_map[key] = {
            "name": previous["channel_name"],
            "subscribers": previous.get("channel_subscribers", ""),
            "yt_link": previous.get("channel_yt_link", ""),
            "status": "verified" if previous.get("channel_verified") else "",
            "avatar": "",
        }
    return channel_map


def fetch_channel_map():
    """Fetch optional channel metadata, returning an empty map on failure."""
    print("Fetching talent profile for channel mapping...")
    channel_map = {}
    try:
        talent = api_get(API_TALENT)
        channels_info = talent.get("youtubeVideos", {}).get("channels", [])
        for ch in channels_info:
            channel_map[channel_key(ch["id"])] = {
                "name": ch["name"],
                "subscribers": ch.get("abvSubscribers", ""),
                "yt_link": ch.get("company", {}).get("ytLink", "") if ch.get("company") else "",
                "status": ch.get("status", ""),
                "avatar": ch.get("avatar", ""),
            }
    except Exception as exc:
        print(f"  Warning: channel mapping unavailable ({exc}); "
              "using yesterday's metadata.", flush=True)
    return channel_map


def main():
    channel_map = fetch_channel_map()

    print("\nFetching all portfolio videos...")
    first_page = api_get(f"{API_VIDEOS}?limit={LIMIT}&search=&page=1")
    stats = first_page["youtubeVideos"]["statistics"]
    total = stats["counts"]
    total_pages = math.ceil(total / LIMIT)
    print(f"  {total} videos across {total_pages} pages")

    raw_videos = list(first_page["youtubeVideos"]["videos"])
    for page_num in range(2, total_pages + 1):
        data = api_get(f"{API_VIDEOS}?limit={LIMIT}&search=&page={page_num}")
        raw_videos.extend(data["youtubeVideos"]["videos"])
        if page_num % 5 == 0:
            print(f"  Fetched page {page_num}/{total_pages}...")

    print(f"  Total raw entries: {len(raw_videos)}")

    add_existing_channel_fallbacks(channel_map, raw_videos, load_existing_videos())
    print(f"Found metadata for {len(channel_map)} channels:")
    for _, info in sorted(channel_map.items(), key=lambda x: x[1]["name"]):
        status_tag = " [VERIFIED]" if info["status"] == "verified" else ""
        print(f"  {info['name']} ({info['subscribers']} subs){status_tag}")

    videos = []
    for v in raw_videos:
        yt_id = extract_yt_id(v.get("url")) or extract_yt_id(v.get("thumbnail"))
        ch_id = v.get("channelId")
        ch_info = channel_map.get(channel_key(ch_id), {})

        videos.append({
            "title": v.get("title", ""),
            "youtube_id": yt_id,
            "youtube_url": f"https://www.youtube.com/watch?v={yt_id}" if yt_id else None,
            "thumbnail": v.get("thumbnail", ""),
            "views": v.get("statistics", {}).get("views", 0),
            "views_formatted": v.get("abvViews", ""),
            "likes_formatted": v.get("abvLikes", ""),
            "channel_name": ch_info.get("name", "Unknown"),
            "channel_subscribers": ch_info.get("subscribers", ""),
            "channel_yt_link": ch_info.get("yt_link", ""),
            "channel_verified": ch_info.get("status") == "verified",
            "ytjobs_channel_id": ch_id,
            "ytjobs_id": v.get("id"),
        })

    # Sort by channel then views descending
    videos.sort(key=lambda x: (x["channel_name"], -x["views"]))

    # Channel breakdown
    by_channel = {}
    for v in videos:
        ch = v["channel_name"]
        if ch not in by_channel:
            by_channel[ch] = {"count": 0, "total_views": 0, "videos": []}
        by_channel[ch]["count"] += 1
        by_channel[ch]["total_views"] += v["views"]
        by_channel[ch]["videos"].append(v)

    output = {
        "portfolio_stats": {
            "updated": datetime.date.today().isoformat(),
            "total_videos": len(videos),
            "total_views_raw": stats.get("views"),
            "total_views": stats["abvViews"],
            "total_likes": stats["abvLikes"],
            "total_comments": stats["abvComments"],
        },
        "channels": {
            name: {
                "video_count": info["count"],
                "total_views": info["total_views"],
                "subscribers": channel_map.get(
                    next((cid for cid, ci in channel_map.items() if ci["name"] == name), None),
                    {}
                ).get("subscribers", ""),
                "verified": channel_map.get(
                    next((cid for cid, ci in channel_map.items() if ci["name"] == name), None),
                    {}
                ).get("status") == "verified",
            }
            for name, info in sorted(by_channel.items(), key=lambda x: -x[1]["total_views"])
        },
        "all_videos": videos,
    }

    with open("portfolio_videos.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Also save just the YouTube URLs for yt-dlp
    yt_urls = [v["youtube_url"] for v in videos if v["youtube_url"]]
    with open("youtube_urls.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(yt_urls))

    print(f"\n{'='*60}")
    print(f"PORTFOLIO SUMMARY")
    print(f"{'='*60}")
    print(f"Total videos: {len(videos)}")
    print(f"Total views:  {stats['abvViews']}")
    print(f"Total likes:  {stats['abvLikes']}")
    print(f"\nBreakdown by Channel:")
    for name, info in sorted(by_channel.items(), key=lambda x: -x[1]["total_views"]):
        ch_data = channel_map.get(
            next((cid for cid, ci in channel_map.items() if ci["name"] == name), None), {}
        )
        verified = " [VERIFIED]" if ch_data.get("status") == "verified" else ""
        subs = ch_data.get("subscribers", "?")
        print(f"  {name} ({subs} subs){verified}")
        print(f"    Videos: {info['count']} | Views: {info['total_views']:,}")

    print(f"\nSaved full data to portfolio_videos.json")
    print(f"Saved {len(yt_urls)} YouTube URLs to youtube_urls.txt")


if __name__ == "__main__":
    main()
