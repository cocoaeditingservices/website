import json
import re
import urllib.request
import math

API_VIDEOS = "https://app.ytjobs.co/api/talents/48926/videos"
API_TALENT = "https://app.ytjobs.co/api/talents/48926?showAll=true"
LIMIT = 15
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://ytjobs.co/talent/vitrine/48926",
    "Origin": "https://ytjobs.co",
}


def api_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def main():
    print("Fetching talent profile for channel mapping...")
    talent = api_get(API_TALENT)

    channel_map = {}
    channels_info = talent.get("youtubeVideos", {}).get("channels", [])
    for ch in channels_info:
        channel_map[int(ch["id"])] = {
            "name": ch["name"],
            "subscribers": ch.get("abvSubscribers", ""),
            "yt_link": ch.get("company", {}).get("ytLink", "") if ch.get("company") else "",
            "status": ch.get("status", ""),
            "avatar": ch.get("avatar", ""),
        }

    print(f"Found {len(channel_map)} channels:")
    for cid, info in sorted(channel_map.items(), key=lambda x: x[1]["name"]):
        status_tag = " [VERIFIED]" if info["status"] == "verified" else ""
        print(f"  {info['name']} ({info['subscribers']} subs){status_tag}")

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

    videos = []
    for v in raw_videos:
        yt_id = extract_yt_id(v.get("url")) or extract_yt_id(v.get("thumbnail"))
        ch_id = v.get("channelId")
        ch_info = channel_map.get(ch_id, {})

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
            "total_videos": len(videos),
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


main()
