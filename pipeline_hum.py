import os
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent
SLEEP = float(os.getenv("SLEEP_SECONDS", "1"))

HEADERS = {"User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)"}
session = requests.Session()
session.headers.update(HEADERS)

HUM_BASE = "https://hum.tv"
SITE_ID = "humtv"
SITE_NAME = "HUM TV"

# TEST MODE — ONLY ONE SERIES
TEST_SERIES_SLUG = "ilzam-e-ishq"

# ============================================================
# HELPERS
# ============================================================

def log(msg: str):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def fetch_soup(url: str):
    time.sleep(SLEEP)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def upsert_site(site_id: str, name: str):
    sites_path = REPO_ROOT / "sites.json"
    if sites_path.exists():
        sites = json.loads(sites_path.read_text(encoding="utf-8"))
    else:
        sites = []

    if not any(s["id"] == site_id for s in sites):
        sites.append({"id": site_id, "name": name})
        write_json(sites_path, sites)

# ============================================================
# HUM SCRAPER
# ============================================================

def scrape_hum():
    log("=== HUM TV scraping ===")

    upsert_site(SITE_ID, SITE_NAME)

    # Single logical channel
    channel_id = "hum_latest"
    write_json(
        REPO_ROOT / "site" / SITE_ID / "channels.json",
        [{"id": channel_id, "name": "Latest Dramas"}]
    )

    series_url = f"{HUM_BASE}/dramas/{TEST_SERIES_SLUG}/"
    series_id = TEST_SERIES_SLUG
    episodes = []

    log(f"Scraping series: {series_id}")

    page = 1
    while True:
        url = series_url if page == 1 else f"{series_url}page/{page}/"
        try:
            soup = fetch_soup(url)
        except Exception:
            break

        episode_links = soup.select("a[href*='episode']")
        if not episode_links:
            break

        for a in episode_links:
            href = a.get("href")
            title = a.get_text(strip=True)

            if not href or "episode" not in href:
                continue

            ep_slug = urlparse(href).path.strip("/").replace("/", "_")
            ep_id = ep_slug

            episodes.append({
                "id": ep_id,
                "name": title,
                "url": href
            })

        page += 1

    # HUM lists latest first — reverse so FIRST episode is at top
    episodes.reverse()

    if not episodes:
        log("No episodes found — skipping series entirely")
        return

    # Write series list
    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        [{"id": series_id, "name": "Ilzam‑e‑Ishq"}]
    )

    # Write episodes.json
    write_json(
        REPO_ROOT / "series" / series_id / "episodes.json",
        [{"id": ep["id"], "name": ep["name"]} for ep in episodes]
    )

    # Write links
    for ep in episodes:
        write_json(
            REPO_ROOT / "episode" / ep["id"] / "links.json",
            [{
                "id": "watch",
                "name": "Watch on HUM TV",
                "url": ep["url"],
                "source": "humtv"
            }]
        )

    log("=== HUM TV scraping done ===")

# ============================================================
# GIT PUBLISH
# ============================================================

def git_publish():
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "add", "."], check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True
    )
    if not status.stdout.strip():
        log("No changes to commit")
        return

    subprocess.run(["git", "commit", "-m", "Scheduled scrape: HUM TV"], check=True)
    subprocess.run(["git", "push"], check=True)
    log("✅ HUM TV data committed")

# ============================================================
# MAIN
# ============================================================

def main():
    scrape_hum()
    git_publish()

if __name__ == "__main__":
    main()
