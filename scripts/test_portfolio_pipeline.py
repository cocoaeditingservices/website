"""Regression tests for homepage ordering and Shorts classification."""
import json
import os
import unittest
import urllib.error
from unittest import mock

import scrape_portfolio
from scripts import refresh_stats, split_portfolio

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FeaturedProjectsTests(unittest.TestCase):
    def test_homepage_uses_newest_classified_longform_order(self):
        videos = [
            {
                "title": f"Work {number}",
                "youtube_id": f"video{number}",
                "youtube_url": f"https://youtube.com/watch?v=video{number}",
                "views_formatted": f"{number}K",
            }
            for number in range(8, 0, -1)
        ]

        projects = refresh_stats.featured_projects(videos)

        self.assertEqual([p["title"] for p in projects], [f"Work {n}" for n in range(8, 2, -1)])
        self.assertEqual(projects[0]["views"], "8K")

    def test_stats_come_from_portfolio_api_data(self):
        data = refresh_stats.stats_payload(
            {
                "updated": "2026-07-23",
                "total_views_raw": 58_365_592,
                "total_videos": 287,
            },
            {},
            "2026-07-23",
        )

        self.assertEqual(data["audience_reached"], "58M+")
        self.assertEqual(data["videos_delivered"], "287+")

    def test_stats_keep_previous_raw_values_for_older_portfolio_data(self):
        data = refresh_stats.stats_payload(
            {"total_videos": 287},
            {"views_raw": 58_365_349, "updated": "2026-07-22"},
            "2026-07-23",
        )

        self.assertEqual(data["views_raw"], 58_365_349)
        self.assertEqual(data["updated"], "2026-07-22")


class PortfolioScraperTests(unittest.TestCase):
    @mock.patch.object(scrape_portfolio, "api_get", side_effect=RuntimeError("HTTP 500"))
    def test_channel_endpoint_failure_uses_fallback(self, _api_get):
        self.assertEqual(scrape_portfolio.fetch_channel_map(), {})

    def test_existing_videos_restore_channel_metadata(self):
        channel_map = scrape_portfolio.add_existing_channel_fallbacks(
            {},
            [{"channelId": 42, "url": "https://youtube.com/watch?v=fB3K0D5G6mg"}],
            [{
                "youtube_id": "fB3K0D5G6mg",
                "channel_name": "Coding with Lewis",
                "channel_subscribers": "782K",
                "channel_verified": True,
            }],
        )

        self.assertEqual(channel_map["42"]["name"], "Coding with Lewis")

    @mock.patch.object(scrape_portfolio.time, "sleep", return_value=None)
    @mock.patch.object(scrape_portfolio.urllib.request, "urlopen")
    def test_transient_api_failure_is_retried(self, urlopen, sleep):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        urlopen.side_effect = [
            urllib.error.HTTPError("https://example.test", 500, "error", {}, None),
            response,
        ]

        self.assertEqual(scrape_portfolio.api_get("https://example.test"), {"ok": True})
        sleep.assert_called_once_with(2)


class ShortsClassificationTests(unittest.TestCase):
    def setUp(self):
        self.cache = mock.patch.dict(split_portfolio.CACHE, {}, clear=True)
        self.cache.start()

    def tearDown(self):
        self.cache.stop()

    @mock.patch.object(split_portfolio.time, "sleep", return_value=None)
    @mock.patch.object(split_portfolio, "fetch_watch_page", side_effect=RuntimeError("rate limited"))
    def test_lookup_failure_is_a_provisional_short(self, _fetch, _sleep):
        kind, duration = split_portfolio.classify({"youtube_id": "fB3K0D5G6mg"})

        self.assertEqual((kind, duration), ("provisional_short", None))
        self.assertNotIn("fB3K0D5G6mg", split_portfolio.CACHE)
        entry = split_portfolio.page_entry(
            {"youtube_id": "fB3K0D5G6mg"}, duration, kind
        )
        self.assertIn("/shorts/fB3K0D5G6mg", entry["youtube_url"])

    @mock.patch.object(split_portfolio.time, "sleep", return_value=None)
    @mock.patch.object(split_portfolio, "fetch_watch_page", side_effect=RuntimeError("rate limited"))
    def test_poisoned_cache_entry_is_not_trusted(self, _fetch, _sleep):
        split_portfolio.CACHE["fB3K0D5G6mg"] = {"kind": "long", "duration": None}

        kind, _ = split_portfolio.classify({"youtube_id": "fB3K0D5G6mg"})

        self.assertEqual(kind, "provisional_short")

    def test_missing_youtube_id_is_the_only_omitted_case(self):
        self.assertEqual(split_portfolio.classify({}), ("unknown", None))

    @mock.patch.object(split_portfolio.time, "sleep", return_value=None)
    @mock.patch.object(
        split_portfolio,
        "fetch_watch_page",
        return_value='<link rel="canonical" href="https://www.youtube.com/shorts/fB3K0D5G6mg"><script>"lengthSeconds":"78"</script>',
    )
    def test_robot_arm_is_confirmed_as_short(self, _fetch, _sleep):
        kind, duration = split_portfolio.classify({"youtube_id": "fB3K0D5G6mg"})

        self.assertEqual((kind, duration), ("short", 78))
        self.assertEqual(split_portfolio.CACHE["fB3K0D5G6mg"]["kind"], "short")


class GeneratedDataTests(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(BASE, name), encoding="utf-8-sig") as f:
            return json.load(f)

    def test_homepage_matches_first_six_longform_videos(self):
        longform = self.load("portfolio_longform.json")["videos"]
        projects = self.load(os.path.join("assets", "projects.json"))["videos"]

        self.assertEqual(
            [project["url"] for project in projects],
            [video["youtube_url"] for video in longform[:6]],
        )

    def test_longform_and_shorts_are_disjoint(self):
        longform = self.load("portfolio_longform.json")["videos"]
        shorts = self.load("portfolio_shorts.json")["videos"]

        long_ids = {video["youtube_id"] for video in longform}
        short_ids = {video["youtube_id"] for video in shorts}
        self.assertFalse(long_ids & short_ids)


if __name__ == "__main__":
    unittest.main()
