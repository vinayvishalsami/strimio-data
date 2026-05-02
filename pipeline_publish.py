import json
import time
import re
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

PLAYDESI_BASE = "https://playdesi.tv"
SERIES_URL = "https://playdesi.tv/watch-online/viu/spotlight-season-1/"
SERIES_NAME = "Spotlight"
SEASON = 1
CHANNEL_ID = "viu_originals"

REPO_ROOT = Path(__file__).resolve().parent

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": PLAYDESI_BASE,
}

SLEEP = 1

session = requests.Session()
session.headers.update(HEADERS)

# ============================================================
# HELPERS
# ============================================================

def log(msg):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def soup(url):
    time.sleep(SLEEP)
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ============================================================
# SCRAPE SPOTLIGHT SEASON 1 (PLAYDESI-CORRECT)
# ============================================================

def scrape_spotlight():
    log("Scraping Spotlight Season 1 (PlayDesi episode links only)")

    series_id = f"{slugify(SERIES_NAME)}__season_{SEASON}"
    page = soup(SERIES_URL)

    # --------------------------------------------------------
    # STEP 1: FIND EPISODE PAGES
    # --------------------------------------------------------

    episode_pages = []
    for a in page.select("article h2.entry-title a"):
        href = a.get("href")
        if href and href.startswith(PLAYDESI_BASE):
            episode_pages.append(href)

    episode_pages = list(dict.fromkeys(episode_pages))
    log(f"Found {len(episode_pages)} episode pages")

    episodes = []

    # --------------------------------------------------------
    # STEP 2: PROCESS EACH EPISODE PAGE
    # --------------------------------------------------------

    for ep_url in episode_pages:
        ep_page = soup(ep_url)

        h1 = ep_page.select_one("h1")
        if not h1:
            continue

        match = re.search(r"episode\s+(\d+)", h1.get_text(), re.I)
        if not match:
            continue

        ep_no = int(match.group(1))
        ep_id = f"{series_id}_ep{ep_no:02d}"

        # ✅ ONLY STORE PLAYDESI EPISODE URL
        links = [
            {
                "id": "watch",
                "name": "Watch on PlayDesi",
                "url": ep_url,
                "source": "playdesi"
            }
        ]

        write_json(
            REPO_ROOT / "episode" / ep_id / "links.json",
            links
        )

        episodes.append({
            "id": ep_id,
            "name": f"Episode {ep_no}"
        })

    # --------------------------------------------------------
    # STEP 3: WRITE SERIES + CHANNEL INDEX
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

    log("✅ Spotlight Season 1 scrape completed (PlayDesi-safe)")

# ============================================================
# RUN SCRAPER
# ============================================================

scrape_spotlight()

# ============================================================
# COMMIT & PUSH
# ============================================================

subprocess.run(["git", "add", "."], cwd=REPO_ROOT)

status = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=REPO_ROOT,
    capture_output=True,
    text=True
)

if status.stdout.strip():
    subprocess.run(
        ["git", "commit", "-m", "PlayDesi: store episode URLs only (no GroundBanks)"],
        cwd=REPO_ROOT
    )
    subprocess.run(["git", "push"], cwd=REPO_ROOT)
    log("✅ Changes committed and pushed")
else:
    log("No changes to publish")
