"""Regression tests for homepage ordering and Shorts classification."""
import json
import os
import unittest
from unittest import mock

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

    @mock.patch.object(refresh_stats, "fetch_html", side_effect=SystemExit(1))
    @mock.patch.object(refresh_stats, "write_projects")
    def test_featured_projects_write_before_stats_fetch(self, write_projects, _fetch):
        with self.assertRaises(SystemExit):
            refresh_stats.main()

        write_projects.assert_called_once()


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
