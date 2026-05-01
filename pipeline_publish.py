import json
import re
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import subprocess

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

YODESI_BASE = "https://www.yodesi.net"
PLAYDESI_BASE = "https://playdesi.tv"

SITE_ID = "yodesi"
PLAYDESI_SITE_ID = "playdesi"

REPO_ROOT = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "Strimio-Indexer/1.0"}
CONFIRM_EPISODES = 5

session = requests.Session()
session.headers.update(HEADERS)

# ============================================================
# HELPERS
# ============================================================

def log(msg):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def soup(url):
    time.sleep(1)
    r = session.get(url)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def slug_to_id(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def git(*args):
    subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True)

def load_existing_series(series_id):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text())
    return data, {e["id"] for e in data}

# ============================================================
# PLAYDESI – NETFLIX
# ============================================================

def scrape_playdesi_netflix():
    log("Scraping PlayDesi – Netflix")

    CHANNEL_ID = "netflix"
    CHANNEL_URL = f"{PLAYDESI_BASE}/netflix/"

    # Register PlayDesi site
    write_json(
        REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json",
        [{"id": CHANNEL_ID, "name": "Netflix"}],
    )

    s = soup(CHANNEL_URL)
    series_list = []

    # Each link === one season
    for a in s.select("a[href*='/watch-online/netflix/']"):
        title = a.get_text(strip=True)
        if "Season" not in title:
            continue

        m = re.search(r"(.+?)\s+Season\s+(\d+)", title)
        if not m:
            continue

        show_name = m.group(1)
        season = int(m.group(2))
        series_id = f"{slug_to_id(show_name)}__season_{season}"

        series_list.append({
            "id": series_id,
            "name": f"{show_name} – Season {season}",
            "url": a["href"],
        })

    series_list.sort(key=lambda x: x["id"])

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{"id": s["id"], "name": s["name"]} for s in series_list],
    )

    # ========================================================
    # EPISODES
    # ========================================================

    for series in series_list:
        log(f"Scraping episodes: {series['name']}")

        existing, existing_ids = load_existing_series(series["id"])
        sp = soup(series["url"])

        new_eps = []
        found_new = False
        confirmed_seen = 0

        # Episode pages are linked internally
        episode_links = []
        for a in sp.select("a[href*='episode']"):
            href = a["href"]
            if href.startswith(PLAYDESI_BASE):
                episode_links.append(href)

        # Deduplicate while preserving order
        episode_links = list(dict.fromkeys(episode_links))

        for ep_url in episode_links:
            ep_page = soup(ep_url)

            # Parse episode number
            h1 = ep_page.select_one("h1")
            if not h1:
                continue

            m = re.search(r"Episode\s+(\d+)", h1.get_text())
            if not m:
                continue

            ep_num = int(m.group(1))
            eid = f"{series['id']}_ep{ep_num:02d}"

            if eid in existing_ids:
                if found_new:
                    confirmed_seen += 1
                continue

            found_new = True
            confirmed_seen = 0

            # ✅ FINAL STREAMING LINKS
            links = []
            for i, a in enumerate(
                ep_page.select(".entry-content a[href*='groundbanks.net/post.php']")
            ):
                links.append({
                    "id": f"server{i+1}",
                    "name": a.get_text(strip=True) or f"Server {i+1}",
                    "url": a["href"],
                })

            write_json(
                REPO_ROOT / "episode" / eid / "links.json",
                links,
            )

            new_eps.append({
                "id": eid,
                "name": f"Episode {ep_num}",
            })

            if confirmed_seen >= CONFIRM_EPISODES:
                break

        # Merge episodes
        merged = new_eps + existing
        seen = set()
        final_eps = []
        for e in merged:
            if e["id"] not in seen:
                final_eps.append(e)
                seen.add(e["id"])

        write_json(
            REPO_ROOT / "series" / series["id"] / "episodes.json",
            final_eps,
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    scrape_playdesi_netflix()

    git("add", ".")
    git("commit", "-m", "Update PlayDesi Netflix scraping")
    git("push", "origin", "main")

    log("Publish complete")
