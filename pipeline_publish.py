import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

PLAYDESI_BASE = "https://playdesi.tv"
CHANNEL_URL = f"{PLAYDESI_BASE}/viu-originals/"
CHANNEL_ID = "viu_originals"

# ✅ TARGET ONLY THIS SERIES (CHANGE LATER)
TARGET_SERIES_NAME = "Spotlight"
TARGET_SEASON = 1

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

def soup(url, ref=None):
    time.sleep(SLEEP)
    headers = HEADERS.copy()
    if ref:
        headers["Referer"] = ref
    r = session.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ============================================================
# GROUNDBANKS VALIDATION (SERIES‑LEVEL ONLY)
# ============================================================

def groundbanks_is_valid(url, expected_show):
    try:
        sp = soup(url, ref=PLAYDESI_BASE)
    except Exception:
        return False

    og = sp.select_one("meta[property='og:title']")
    if not og:
        return False

    title = og.get("content", "").lower()
    return expected_show.lower() in title

# ============================================================
# SCRAPER — SINGLE SERIES ONLY
# ============================================================

def scrape_single_series():
    log("Scraping PlayDesi – VIU Originals (SINGLE SERIES MODE)")

    index = soup(CHANNEL_URL)

    target_series = None

    # --------------------------------------------------------
    # FIND ONLY THE TARGET SERIES
    # --------------------------------------------------------

    for a in index.select("a[href*='/watch-online/']"):
        title = a.get_text(strip=True)
        url = a["href"]

        season_match = re.search(r"(.+?)\s+season\s+(\d+)", title, re.I)

        if season_match:
            show = season_match.group(1).strip()
            season = int(season_match.group(2))
        else:
            show = title
            season = 1

        if show.lower() == TARGET_SERIES_NAME.lower() and season == TARGET_SEASON:
            target_series = {
                "id": f"{slugify(show)}__season_{season}",
                "name": f"{show} – Season {season}",
                "show": show,
                "url": url,
            }
            break

    if not target_series:
        log("❌ Target series not found – check name/season")
        return

    # --------------------------------------------------------
    # WRITE SERIES INDEX (ONLY ONE)
    # --------------------------------------------------------

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{"id": target_series["id"], "name": target_series["name"]}],
    )

    # --------------------------------------------------------
    # SCRAPE EPISODES
    # --------------------------------------------------------

    log(f"Scraping episodes: {target_series['name']}")

    page = soup(target_series["url"], ref=CHANNEL_URL)

    episode_urls = []
    for a in page.select("a[href*='/watch-online/']"):
        href = a["href"]
        if href.startswith(PLAYDESI_BASE) and href != target_series["url"]:
            episode_urls.append(href)

    episode_urls = list(dict.fromkeys(episode_urls))

    episodes = []

    for ep_url in episode_urls:
        ep = soup(ep_url, ref=target_series["url"])
        h1 = ep.select_one("h1")
        if not h1:
            continue

        m = re.search(r"episode\s*(\d+)|part\s*(\d+)|\b(\d+)\b", h1.get_text(), re.I)
        if not m:
            continue

        ep_no = next(int(g) for g in m.groups() if g)
        eid = f"{target_series['id']}_ep{ep_no:02d}"

        links = []
        for i, a in enumerate(ep.select(".entry-content a[href*='groundbanks.net']")):
            gb_url = a["href"]
            if groundbanks_is_valid(gb_url, target_series["show"]):
                links.append({
                    "id": f"server{i+1}",
                    "name": a.get_text(strip=True) or f"Server {i+1}",
                    "url": gb_url
                })

        if not links:
            continue

        write_json(REPO_ROOT / "episode" / eid / "links.json", links)
        episodes.append({"id": eid, "name": f"Episode {ep_no}"})

    write_json(
        REPO_ROOT / "series" / target_series["id"] / "episodes.json",
        episodes,
    )

    log("✅ Single series scrape complete")

# ============================================================
# RUN
# ============================================================

scrape_single_series()
