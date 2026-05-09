import os
import json
import time
import subprocess
import re
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

# TEST MODE — ONE SERIES ONLY
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
# HUM SCRAPER (FIXED)
# ============================================================

EP_URL_RE = re.compile(r"(?:-|/)episode-(\d+)|last-episode-(\d+)", re.I)

def scrape_hum():
    log("=== HUM TV scraping ===")

    upsert_site(SITE_ID, SITE_NAME)

    channel_id = "hum_latest"
    write_json(
        REPO_ROOT / "site" / SITE_ID / "channels.json",
        [{"id": channel_id, "name": "Latest Dramas"}]
    )

    base_series_url = f"{HUM_BASE}/dramas/{TEST_SERIES_SLUG}/"
    series_url = base_series_url + "#episodes"

    series_id = TEST_SERIES_SLUG
    episodes = []

    log(f"Scraping series: {series_id}")

    page = 1
    seen_urls = set()

    while True:
        paged_url = (
            base_series_url
            if page == 1
            else f"{base_series_url}page/{page}/"
        )

        try:
            soup = fetch_soup(paged_url)
        except Exception:
            break

        anchors = soup.find_all("a", href=True)
        found_any = False

        for a in anchors:
            href = a["href"]

            if not href.startswith(HUM_BASE):
                continue

            if not EP_URL_RE.search(href):
                continue

            title = a.get_text(strip=True)
            if not title or "episode" not in title.lower():
                continue

            if href in seen_urls:
                continue

            seen_urls.add(href)
            found_any = True

            ep_slug = urlparse(href).path.strip("/").replace("/", "_")

            episodes.append({
                "id": ep_slug,
                "name": title,
                "url": href
            })

        if not found_any:
            break

        page += 1

    # HUM lists latest first → reverse
    episodes.reverse()

    if not episodes:
        log("No valid episodes found — skipping series")
        return

    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        [{
            "id": series_id,
            "name": "Ilzam‑e‑Ishq",
            "url": series_url
        }]
    )

    write_json(
        REPO_ROOT / "series" / series_id / "episodes.json",
        [{"id": ep["id"], "name": ep["name"]} for ep in episodes]
    )

    for ep in episodes:
        write_json(
            REPO_ROOT / "episode" / ep["id"] / "links.json",
            [{
                "id": "watch",
                "name": "Watch on HUM TV",
                "url": ep["url"],
                "source": SITE_ID
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
