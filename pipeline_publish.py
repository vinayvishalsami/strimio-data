# YO DESI SCRAPER + AUTO PUBLISH
# INCREMENTAL VERSION (5-EPISODE CONFIRMATION)
# WORKS LOCALLY + GITHUB ACTIONS

import json
import re
import time
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.exceptions import HTTPError

# ---------------- CONFIG ----------------

BASE_URL = "https://www.yodesi.net"

SITE_ID = "yodesi"
SITE_NAME = "YoDesi"

CHANNELS = {
    "sony_tv": ("Sony TV", f"{BASE_URL}/sony-tv/"),
    "star_plus": ("Star Plus", f"{BASE_URL}/star-plus/"),
    "colors": ("Colors", f"{BASE_URL}/colors/"),
    "zee_tv": ("Zee TV", f"{BASE_URL}/zee-tv/"),
    "sab_tv": ("Sab TV", f"{BASE_URL}/sab-tv/"),
    "mtv_india": ("MTV India", f"{BASE_URL}/mtv-india/"),
}

# ✅ repo root (local + GitHub Actions safe)
REPO_ROOT = Path(__file__).resolve().parent

HEADERS = {"User-Agent": "Strimio-Indexer/1.0"}

CONFIRM_EPISODES = 5   # ✅ incremental confirmation count

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}

session = requests.Session()
session.headers.update(HEADERS)

# ---------------- HELPERS ----------------

def log(msg):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def soup(url):
    time.sleep(1)
    r = session.get(url)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def slug_to_id(slug):
    return slug.strip("/").replace("-", "_")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def git(*args):
    subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True)

def load_existing_episode_ids(series_id):
    path = REPO_ROOT / "series" / series_id / "episodes.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {e["id"] for e in data}
    except Exception:
        return set()

# ---------------- SITE ----------------

log("Writing site metadata")

write_json(
    REPO_ROOT / "sites.json",
    [{"id": SITE_ID, "name": SITE_NAME}]
)

channels_payload = [{"id": cid, "name": name} for cid, (name, _) in CHANNELS.items()]

# ---------------- SCRAPE ----------------

for channel_id, (channel_name, channel_url) in CHANNELS.items():
    log(f"Scraping channel: {channel_name}")

    s = soup(channel_url)
    series = []

    for a in s.select("#tab-0-title-1 p.small-title a"):
        slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
        series.append({
            "id": slug_to_id(slug),
            "name": a.get_text(strip=True),
            "url": a["href"]
        })

    log(f"Found {len(series)} series")

    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        [{"id": x["id"], "name": x["name"]} for x in series]
    )

    for show in series:
        log(f"Scraping episodes: {show['name']}")

        existing_ids = load_existing_episode_ids(show["id"])

        page = 1
        episode_urls = []
        confirmed_seen = 0
        should_continue = True

        while should_continue:
            try:
                url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                sp = soup(url)
            except HTTPError as e:
                if e.response.status_code == 404:
                    break
                raise

            links = sp.select("article.latestPost h2.title.front-view-title > a")
            if not links:
                break

            for a in links:
                ep_url = a["href"]
                episode_urls.append(ep_url)

                slug = ep_url.rstrip("/").split("/")[-1]
                inferred_id = f"{show['id']}_{slug}"

                if inferred_id in existing_ids:
                    confirmed_seen += 1
                else:
                    confirmed_seen = 0

                # ✅ 5-episode confirmation → stop series
                if confirmed_seen >= CONFIRM_EPISODES:
                    should_continue = False
                    break

            page += 1

        episodes = []

        for ep_url in dict.fromkeys(episode_urls):
            sp = soup(ep_url)
            h1 = sp.select_one("h1.title.entry-title")
            if not h1:
                continue

            title_text = h1.get_text(strip=True).lower()

            m = re.search(
                r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})",
                title_text
            )

            if not m or m.group(2) not in MONTHS:
                continue

            day = int(m.group(1))
            month = MONTHS[m.group(2)]
            year = m.group(3)

            eid = f"{show['id']}_{year}_{month}_{day:02d}"

            links = [
                {
                    "id": f"server{i+1}",
                    "name": a.get_text(strip=True) or "Server",
                    "url": a["href"]
                }
                for i, a in enumerate(
                    sp.select(".thecontent a[href*='player.php?id=']")
                )
            ]

            episodes.append({
                "id": eid,
                "name": f"{show['name']} {day}-{month}-{year}",
                "links": links
            })

        log(f"Found {len(episodes)} episodes")

        write_json(
            REPO_ROOT / "series" / show["id"] / "episodes.json",
            [{"id": e["id"], "name": e["name"]} for e in episodes]
        )

        for e in episodes:
            write_json(
                REPO_ROOT / "episode" / e["id"] / "links.json",
                e["links"]
            )

# ---------------- CHANNEL LIST ----------------

write_json(
    REPO_ROOT / "site" / SITE_ID / "channels.json",
    channels_payload
)

# ---------------- PUBLISH ----------------

log("Publishing to GitHub")

git("add", ".")

status = subprocess.run(
    ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
    capture_output=True,
    text=True
)

if status.stdout.strip():
    git("commit", "-m", f"Auto update {datetime.utcnow().isoformat()}")
    git("push", "origin", "main")
    log("Publish complete")
else:
    log("No changes to publish")
