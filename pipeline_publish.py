# FULL SCRAPER + GENERATOR + AUTO-PUBLISH SCRIPT
# YO DESI → MULTI CHANNEL WITH PROGRESS LOGS
# SCHEMA FROZEN

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

BASE_URL = "https://www.yodesi.net"

SITE_ID, SITE_NAME = "yodesi", "YoDesi"

CHANNELS = {
    "sony_tv": ("Sony TV", f"{BASE_URL}/sony-tv/"),
    "star_plus": ("Star Plus", f"{BASE_URL}/star-plus/"),
    "colors": ("Colors", f"{BASE_URL}/colors/"),
    "zee_tv": ("Zee TV", f"{BASE_URL}/zee-tv/"),
    "sab_tv": ("Sab TV", f"{BASE_URL}/sab-tv/"),
    "mtv_india": ("MTV India", f"{BASE_URL}/mtv-india/"),
}

REPO_ROOT = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "Strimio-Indexer/1.0"}

MONTHS = {
    "january": "01","february": "02","march": "03","april": "04",
    "may": "05","june": "06","july": "07","august": "08",
    "september": "09","october": "10","november": "11","december": "12"
}

session = requests.Session()
session.headers.update(HEADERS)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

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

# ---------- SITE ----------
log("Writing site metadata")
write_json(REPO_ROOT / "sites.json", [{"id": SITE_ID, "name": SITE_NAME}])

channels_payload = [{"id": cid, "name": c[0]} for cid, c in CHANNELS.items()]

# ---------- SCRAPE ----------
for CHANNEL_ID, (CHANNEL_NAME, CHANNEL_URL) in CHANNELS.items():
    log(f"Scraping channel: {CHANNEL_NAME}")

    s = soup(CHANNEL_URL)
    series = []

    for a in s.select("#tab-0-title-1 p.small-title a"):
        slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
        series.append({
            "id": slug_to_id(slug),
            "name": a.get_text(strip=True),
            "url": a["href"]
        })

    log(f"  Found {len(series)} series")

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{"id": s["id"], "name": s["name"]} for s in series]
    )

    for show in series:
        log(f"    Scraping episodes: {show['name']}")
        page = 1
        episode_urls = []

        while True:
            try:
                url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                sp = soup(url)
            except HTTPError as e:
                if e.response.status_code == 404:
                    break
                raise

            found = False
            for a in sp.select("article.latestPost h2.title.front-view-title > a"):
                episode_urls.append(a["href"])
                found = True

            if not found:
                break
            page += 1

        episodes = []
        for ep_url in dict.fromkeys(episode_urls):
            sp = soup(ep_url)
            h1 = sp.select_one("h1.title.entry-title")
            if not h1:
                continue

            m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", h1.text.lower())
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

        log(f"      Found {len(episodes)} episodes")

        write_json(
            REPO_ROOT / "series" / show["id"] / "episodes.json",
            [{"id": e["id"], "name": e["name"]} for e in episodes]
        )

        for e in episodes:
            write_json(
                REPO_ROOT / "episode" / e["id"] / "links.json",
                e["links"]
            )

# ---------- FORCE CHANNELS ----------
log("Writing channels.json")
write_json(REPO_ROOT / "site" / SITE_ID / "channels.json", channels_payload)

# ---------- PUBLISH ----------
log("Publishing to GitHub")
git("add", ".")
status = subprocess.run(
    ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
    capture_output=True, text=True
)

if status.stdout.strip():
    git("commit", "-m", f"Auto update {datetime.now()}")
    git("push", "origin", "main")
    log("Publish complete")
else:
    log("No changes to publish")
