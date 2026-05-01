# YO DESI SCRAPER + AUTO PUBLISH
# INCREMENTAL (5-EPISODE CONFIRMATION ENABLED)
# SAFE FOR ALL CHANNELS INCLUDING &TV

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
    "tv_and_tv": ("&TV", f"{BASE_URL}/tv-and-tv/"),
}

REPO_ROOT = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "Strimio-Indexer/1.0"}
CONFIRM_EPISODES = 5

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
        return {e["id"] for e in json.loads(path.read_text())}
    except Exception:
        return set()

# ---------------- SITE ----------------

write_json(
    REPO_ROOT / "sites.json",
    [{"id": SITE_ID, "name": SITE_NAME}]
)

channels_payload = [{"id": cid, "name": name} for cid, (name, _) in CHANNELS.items()]

# ---------------- SCRAPE ----------------

for channel_id, (channel_name, channel_url) in CHANNELS.items():
    log(f"Channel: {channel_name}")

    try:
        s = soup(channel_url)
    except HTTPError:
        log(f"Skipping {channel_name} (failed to load)")
        continue

    series = []

    for a in s.select("#tab-0-title-1 p.small-title a"):
        slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
        series.append({
            "id": slug_to_id(slug),
            "name": a.get_text(strip=True),
            "url": a["href"]
        })

    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        [{"id": x["id"], "name": x["name"]} for x in series]
    )

    for show in series:
        existing_ids = load_existing_episode_ids(show["id"])
        page = 1
        episode_urls = []
        seen = 0

        while True:
            try:
                url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                sp = soup(url)
            except HTTPError:
                break

            links = sp.select("article.latestPost h2.title.front-view-title > a")
            if not links:
                break

            for a in links:
                href = a["href"]
                episode_urls.append(href)

                slug = href.rstrip("/").split("/")[-1]
                if f"{show['id']}_{slug}" in existing_ids:
                    seen += 1
                else:
                    seen = 0

                if seen >= CONFIRM_EPISODES:
                    page = None
                    break

            if page is None:
                break

            page += 1

        episodes = []

        for ep_url in dict.fromkeys(episode_urls):
            sp = soup(ep_url)
            h1 = sp.select_one("h1.title.entry-title")
            if not h1:
                continue

            txt = h1.get_text(strip=True).lower()
            m = re.search(r"(\\d{1,2})(?:st|nd|rd|th)?\\s+([a-z]+)\\s+(\\d{4})", txt)
            if not m or m.group(2) not in MONTHS:
                continue

            day, month, year = int(m.group(1)), MONTHS[m.group(2)], m.group(3)
            eid = f"{show['id']}_{year}_{month}_{day:02d}"

            links = [
                {
                    "id": f"server{i+1}",
                    "name": a.get_text(strip=True) or "Server",
                    "url": a["href"]
                }
                for i, a in enumerate(sp.select(".thecontent a[href*='player.php?id=']"))
            ]

            episodes.append({
                "id": eid,
                "name": f"{show['name']} {day}-{month}-{year}",
                "links": links
            })

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
