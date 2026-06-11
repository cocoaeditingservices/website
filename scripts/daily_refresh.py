"""Daily website data refresh — run by the CocoaWebsite_RefreshStats task.

Runs, in order:
  1. scripts/refresh_stats.py   -> assets/stats.json + assets/projects.json
  2. scrape_portfolio.py        -> portfolio_videos.json (YTJobs API)
  3. scripts/split_portfolio.py -> portfolio_longform.json,
                                   portfolio_shorts.json, portfolio_data.js

Steps are isolated: if one fails the rest still run, and the site keeps
yesterday's JSON for whatever failed. Step 3 only fetches videos missing
from scripts/shorts_cache.json, so a normal day touches a handful of URLs.
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = [
    os.path.join(BASE, "scripts", "refresh_stats.py"),
    os.path.join(BASE, "scrape_portfolio.py"),
    os.path.join(BASE, "scripts", "split_portfolio.py"),
]

# Child scripts print video titles containing emoji; force UTF-8 so they
# don't crash under the console's cp1252 encoding.
env = dict(os.environ, PYTHONIOENCODING="utf-8")

failed = []
for script in STEPS:
    name = os.path.basename(script)
    print(f"=== {name} ===", flush=True)
    result = subprocess.run([sys.executable, script], cwd=BASE, env=env)
    if result.returncode != 0:
        failed.append(name)
        print(f"  {name} failed with exit code {result.returncode}", flush=True)

if failed:
    print(f"FAILED steps: {', '.join(failed)}", flush=True)
    sys.exit(1)
print("All refresh steps completed.", flush=True)
