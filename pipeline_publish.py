# YO DESI + PLAYDESI SCRAPER + AUTO PUBLISH
# FINAL STABLE VERSION
# YoDesi ✅ locked
# PlayDesi Netflix ✅ Phase-1

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
PLAYDESI_BASE = "https://playdesi.tv/"

SITE_ID = "yodesi"
SITE_NAME = "YoDesi"

PLAYDESI_SITE_ID = "playdesi"

CHANNELS = {
    "sony_tv": ("Sony TV", f"{BASE_URL}/sony-tv/"),
    "star_plus": ("Star Plus", f"{BASE_URL}/star-plus/"),
    "colors": ("Colors", f"{BASE_URL}/colors/"),
    "zee_tv": ("Zee TV", f"{BASE_URL}/zee-tv/"),
    "sab_tv": ("Sab TV", f"{BASE_URL}/sab-tv/"),
    "mtv_india": ("MTV India", f"{BASE_URL}/mtv-india/"),
    "and_tv": ("&TV", f"{BASE_URL}/tv-and-tv/"),
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

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th') }"

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def git(*args):
    subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True)

def load_existing_series_data(series_id):
    path = REPO_ROOT / "series" / series_id / "episodes.json"
    if not path.exists():
        return [], set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, {e["id"] for e in data}

def infer_id_from_slug(series_id, slug):
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?-([a-z]+)-(\d{4})", slug.lower())
    if m and m.group(2) in MONTHS:
        return f"{series_id}_{m.group(3)}_{MONTHS[m.group(2)]}_{int(m.group(1)):02d}"
    return None

# ---------------- YODESI ----------------

write_json(REPO_ROOT / "sites.json", [{"id": SITE_ID, "name": SITE_NAME}])
channels_payload = [{"id": cid, "name": name} for cid, (name, _) in CHANNELS.items()]

for channel_id, (channel_name, channel_url) in CHANNELS.items():
    log(f"Scraping YoDesi channel: {channel_name}")
    s = soup(channel_url)

    series = []
    for a in s.select("#tab-0-title-1 p.small-title a"):
        slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
        series.append({
            "id": slug_to_id(slug),
            "name": a.get_text(strip=True),
            "url": a["href"]
        })

    write_json(REPO_ROOT / "channel" / channel_id / "series.json",
               [{"id": x["id"], "name": x["name"]} for x in series])

    for show in series:
        existing_eps, existing_ids = load_existing_series_data(show["id"])
        page, found_new, confirmed_seen = 1, False, 0
        new_urls = []

        while True:
            url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
            try:
                sp = soup(url)
            except HTTPError:
                break

            links = sp.select("article.latestPost h2.title.front-view-title > a")
            if not links:
                break

            for a in links:
                ep_url = a["href"]
                slug = ep_url.rstrip("/").split("/")[-1]
                inferred = infer_id_from_slug(show["id"], slug)

                if inferred and inferred in existing_ids:
                    if found_new:
                        confirmed_seen += 1
                else:
                    found_new = True
                    confirmed_seen = 0
                    new_urls.append(ep_url)

                if found_new and confirmed_seen >= CONFIRM_EPISODES:
                    break
            else:
                page += 1
                continue
            break

        new_eps = []
        for ep_url in new_urls:
            sp = soup(ep_url)
            h1 = sp.select_one("h1.title.entry-title")
            if not h1:
                continue

            m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?\s+([a-z]+)\s+(\d{4})",
                          h1.get_text(strip=True).lower())
            if not m:
                continue

            day, month, year = int(m.group(1)), MONTHS[m.group(2)], m.group(3)
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

            write_json(REPO_ROOT / "episode" / eid / "links.json", links)
            new_eps.append({"id": eid, "name": f"{show['name']} {ordinal(day)} {m.group(2).title()} {year}"})

        merged = new_eps + existing_eps
        seen, final = set(), []
        for e in merged:
            if e["id"] not in seen:
                final.append(e)
                seen.add(e["id"])

        write_json(REPO_ROOT / "series" / show["id"] / "episodes.json", final)

# ---------------- PLAYDESI NETFLIX (PHASE 1) ----------------

def scrape_playdesi_netflix():
    log("Scraping PlayDesi – Netflix")

    CHANNEL_ID = "netflix"
    CHANNEL_URL = f"{PLAYDESI_BASE}/netflix/"

    write_json(REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json",
               [{"id": CHANNEL_ID, "name": "Netflix"}])

    s = soup(CHANNEL_URL)
    shows = s.select("article h2 a")

    series_list = []

    for a in shows:
        show_url = a["href"]
        show_name = a.get_text(strip=True)
        sp = soup(show_url)

        for season in sp.select("a[href*='season']"):
            m = re.search(r"season\s*(\d+)", season.get_text(strip=True).lower())
            if not m:
                continue
            s_num = int(m.group(1))
            sid = f"{slug_to_id(show_name)}__season_{s_num}"
            series_list.append({
                "id": sid,
                "name": f"{show_name} – Season {s_num}",
                "url": season["href"]
            })

    series_list.sort(key=lambda x: x["id"])
    write_json(REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
               [{"id": s["id"], "name": s["name"]} for s in series_list])

    for series in series_list:
        existing_eps, existing_ids = load_existing_series_data(series["id"])
        sp = soup(series["url"])

        new_eps, found_new, confirmed_seen = [], False, 0

        for i, a in enumerate(sp.select("article h2 a"), start=1):
            eid = f"{series['id']}_ep{i:02d}"
            if eid in existing_ids:
                if found_new:
                    confirmed_seen += 1
            else:
                found_new = True
                confirmed_seen = 0
                ep_page = soup(a["href"])
                links = [
                    {"id": f"server{j+1}", "name": l.get_text(strip=True) or "Server", "url": l["href"]}
                    for j, l in enumerate(ep_page.select(".thecontent a[href^='http']"))
                ]
                write_json(REPO_ROOT / "episode" / eid / "links.json", links)
                new_eps.append({"id": eid, "name": f"Episode {i}"})

            if found_new and confirmed_seen >= CONFIRM_EPISODES:
                break

        merged = new_eps + existing_eps
        seen, final = set(), []
        for e in merged:
            if e["id"] not in seen:
                final.append(e)
                seen.add(e["id"])

        write_json(REPO_ROOT / "series" / series["id"] / "episodes.json", final)

scrape_playdesi_netflix()

# ---------------- CHANNEL LIST ----------------

write_json(REPO_ROOT / "site" / SITE_ID / "channels.json", channels_payload)

# ---------------- PUBLISH ----------------

git("add", ".")
status = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                        capture_output=True, text=True)

if status.stdout.strip():
    git("commit", "-m", f"Auto update {datetime.utcnow().isoformat()}")
    git("push", "origin", "main")
    log("Publish complete")
else:
    log("No changes to publish")
