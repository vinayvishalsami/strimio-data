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

SERIES_URL = "https://playdesi.tv/watch-online/viu/spotlight-season-1/"
SERIES_NAME = "Spotlight"
SEASON = 1
CHANNEL_ID = "viu_originals"

PLAYDESI_BASE = "https://playdesi.tv"

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
# SCRAPE SPOTLIGHT SEASON 1 (CORRECT METHOD)
# ============================================================

def scrape_spotlight():
    log("Scraping Spotlight Season 1")

    series_id = f"{slugify(SERIES_NAME)}__season_{SEASON}"

    page = soup(SERIES_URL)

    # --------------------------------------------------------
    # STEP 1: Extract episode page links from ARTICLES
    # --------------------------------------------------------

    episode_links = []
    for a in page.select("article h2.entry-title a"):
        href = a.get("href")
        if href and href.startswith(PLAYDESI_BASE):
            episode_links.append(href)

    episode_links = list(dict.fromkeys(episode_links))

    if not episode_links:
        log("❌ No episode pages found")
        return

    log(f"Found {len(episode_links)} episode pages")

    episodes = []

    # --------------------------------------------------------
    # STEP 2: Visit each episode page
    # --------------------------------------------------------

    for ep_url in episode_links:
        ep = soup(ep_url)

        h1 = ep.select_one("h1")
        if not h1:
            continue

        m = re.search(r"episode\s+(\d+)", h1.get_text(), re.I)
        if not m:
            continue

        ep_no = int(m.group(1))
        ep_id = f"{series_id}_ep{ep_no:02d}"

        links = []
        for i, a in enumerate(ep.select(".entry-content a[href*='groundbanks.net']")):
            links.append({
                "id": f"server{i+1}",
                "name": a.get_text(strip=True) or f"Server {i+1}",
                "url": a["href"]
            })

        if not links:
            continue

        write_json(
            REPO_ROOT / "episode" / ep_id / "links.json",
            links
        )

        episodes.append({
            "id": ep_id,
            "name": f"Episode {ep_no}"
        })

    # --------------------------------------------------------
    # STEP 3: Write episodes + series index
    # --------------------------------------------------------

    write_json(
        REPO_ROOT / "series" / series_id / "episodes.json",
        sorted(episodes, key=lambda x: x["id"])
    )

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{
            "id": series_id,
            "name": f"{SERIES_NAME} – Season {SEASON}"
        }]
    )

    log("✅ Spotlight Season 1 scrape complete")

# ============================================================
# RUN
# ============================================================

scrape_spotlight()
