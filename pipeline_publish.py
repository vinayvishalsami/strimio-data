import json
import time
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

PLAYDESI_BASE = "https://playdesi.tv"
SERIES_URL = "https://playdesi.tv/watch-online/spotlight-season-1/"
CHANNEL_ID = "viu_originals"
SERIES_NAME = "Spotlight"
SEASON = 1

REPO_ROOT = Path(__file__).resolve().parent
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": PLAYDESI_BASE,
}

session = requests.Session()
session.headers.update(HEADERS)

# ============================================================
# HELPERS
# ============================================================

def log(msg):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def soup(url):
    time.sleep(1)
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def slugify(t):
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ============================================================
# SCRAPE SPOTLIGHT (SINGLE PAGE MODEL)
# ============================================================

def scrape_spotlight():
    log("Scraping Spotlight – Season 1 (single-page model)")

    series_id = f"{slugify(SERIES_NAME)}__season_{SEASON}"

    page = soup(SERIES_URL)

    # --------------------------------------------------------
    # Extract ALL GroundBanks links on the page
    # --------------------------------------------------------

    gb_links = []
    for a in page.select("a[href*='groundbanks.net']"):
        gb_links.append({
            "name": a.get_text(strip=True) or "Server",
            "url": a["href"]
        })

    if not gb_links:
        log("❌ No GroundBanks links found")
        return

    # --------------------------------------------------------
    # Build episodes (1 GB link = 1 episode, for testing)
    # --------------------------------------------------------

    episodes = []

    for idx, link in enumerate(gb_links, start=1):
        ep_id = f"{series_id}_ep{idx:02d}"

        write_json(
            REPO_ROOT / "episode" / ep_id / "links.json",
            [{
                "id": "server1",
                "name": "Server 1",
                "url": link["url"]
            }]
        )

        episodes.append({
            "id": ep_id,
            "name": f"Episode {idx}"
        })

    write_json(
        REPO_ROOT / "series" / series_id / "episodes.json",
        episodes
    )

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{
            "id": series_id,
            "name": f"{SERIES_NAME} – Season {SEASON}"
        }]
    )

    log("✅ Spotlight episodes created")

# ============================================================
# RUN
# ============================================================

scrape_spotlight()
