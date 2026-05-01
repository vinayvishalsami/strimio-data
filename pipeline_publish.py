# STRIMIO DATA SCRAPER
# YoDesi (LOCKED)
# PlayDesi Netflix (PHASE‑1 COMPLETE)

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

# ============================================================
# CONFIG
# ============================================================

YODESI_BASE = "https://www.yodesi.net"
PLAYDESI_BASE = "https://playdesi.tv"

SITE_ID = "yodesi"
PLAYDESI_SITE_ID = "playdesi"

CHANNELS = {
    "sony_tv": ("Sony TV", f"{YODESI_BASE}/sony-tv/"),
    "star_plus": ("Star Plus", f"{YODESI_BASE}/star-plus/"),
    "colors": ("Colors", f"{YODESI_BASE}/colors/"),
    "zee_tv": ("Zee TV", f"{YODESI_BASE}/zee-tv/"),
    "sab_tv": ("Sab TV", f"{YODESI_BASE}/sab-tv/"),
    "mtv_india": ("MTV India", f"{YODESI_BASE}/mtv-india/"),
    "and_tv": ("&TV", f"{YODESI_BASE}/tv-and-tv/"),
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

def slug_to_id(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def git(*args):
    subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True)

def load_existing_series(series_id):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text())
    return data, {e["id"] for e in data}

def infer_yodesi_id(series_id, slug):
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?-([a-z]+)-(\d{4})", slug)
    if m and m.group(2) in MONTHS:
        return f"{series_id}_{m.group(3)}_{MONTHS[m.group(2)]}_{int(m.group(1)):02d}"
    return None

def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th') }"

# ============================================================
# YODESI SCRAPER (UNCHANGED)
# ============================================================

write_json(REPO_ROOT / "sites.json", [{"id": SITE_ID, "name": "YoDesi"}])
yodesi_channels_payload = [{"id": cid, "name": n} for cid, (n, _) in CHANNELS.items()]

for channel_id, (_, channel_url) in CHANNELS.items():
    log(f"Scraping YoDesi channel: {channel_id}")
    s = soup(channel_url)

    shows = []
    for a in s.select("#tab-0-title-1 p.small-title a"):
        slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
        shows.append({
            "id": slug_to_id(slug),
            "name": a.get_text(strip=True),
            "url": a["href"]
        })

    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        [{"id": x["id"], "name": x["name"]} for x in shows]
    )

    for show in shows:
        existing_eps, existing_ids = load_existing_series(show["id"])
        new_urls = []
        page, found_new, confirmed = 1, False, 0

        while True:
            try:
                page_url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                sp = soup(page_url)
            except HTTPError:
                break

            links = sp.select("article.latestPost h2.title.front-view-title > a")
            if not links:
                break

            for a in links:
                slug = a["href"].split("/")[-2]
                inferred = infer_yodesi_id(show["id"], slug)

                if inferred and inferred in existing_ids:
                    if found_new:
                        confirmed += 1
                else:
                    found_new = True
                    confirmed = 0
                    new_urls.append(a["href"])

                if found_new and confirmed >= CONFIRM_EPISODES:
                    break
            else:
                page += 1
                continue
            break

        new_eps = []
        for ep_url in new_urls:
            sp = soup(ep_url)
            m = re.search(
                r"(\d{1,2})(?:st|nd|rd|th|h)?\s+([a-z]+)\s+(\d{4})",
                sp.get_text(" ").lower()
            )
            if not m:
                continue

            day, month, year = int(m.group(1)), MONTHS[m.group(2)], m.group(3)
            eid = f"{show['id']}_{year}_{month}_{day:02d}"

            links = [
                {"id": f"server{i+1}", "name": a.get_text(strip=True) or "Server", "url": a["href"]}
                for i, a in enumerate(sp.select(".thecontent a[href*='player.php']"))
            ]

            write_json(REPO_ROOT / "episode" / eid / "links.json", links)
            new_eps.append({
                "id": eid,
                "name": f"{show['name']} {ordinal(day)} {m.group(2).title()} {year}"
            })

        merged = new_eps + existing_eps
        seen, final = set(), []
        for e in merged:
            if e["id"] not in seen:
                final.append(e)
                seen.add(e["id"])

        write_json(REPO_ROOT / "series" / show["id"] / "episodes.json", final)

# ============================================================
# PLAYDESI – NETFLIX
# ============================================================

def scrape_playdesi_netflix():
    log("Scraping PlayDesi – Netflix")

    CHANNEL_ID = "netflix"
    CHANNEL_URL = f"{PLAYDESI_BASE}/netflix/"

    write_json(
        REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json",
        [{"id": CHANNEL_ID, "name": "Netflix"}]
    )

    s = soup(CHANNEL_URL)
    series_list = []

    for a in s.select("a[href*='/watch-online/netflix/']"):
        name = a.get_text(strip=True)
        if "Season" not in name:
            continue

        m = re.search(r"(.+?)\s+Season\s+(\d+)", name)
        if not m:
            continue

        show = m.group(1)
        season = int(m.group(2))
        sid = f"{slug_to_id(show)}__season_{season}"

        series_list.append({
            "id": sid,
            "name": f"{show} – Season {season}",
            "url": a["href"]
        })

    series_list.sort(key=lambda x: x["id"])

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{"id": s["id"], "name": s["name"]} for s in series_list]
    )

    for series in series_list:
        log(f"Scraping episodes: {series['name']}")
        existing, existing_ids = load_existing_series(series["id"])
        sp = soup(series["url"])

        new_eps, found_new, confirmed = [], False, 0

        episode_links = []
        for a in sp.select("a[href*='episode']"):
            if a["href"].startswith(PLAYDESI_BASE):
                episode_links.append(a["href"])

        episode_links = list(dict.fromkeys(episode_links))

        for ep_url in episode_links:
            ep = soup(ep_url)
            h1 = ep.select_one("h1")
            if not h1:
                continue

            m = re.search(r"Episode\s+(\d+)", h1.get_text())
            if not m:
                continue

            num = int(m.group(1))
            eid = f"{series['id']}_ep{num:02d}"

            if eid in existing_ids:
                if found_new:
                    confirmed += 1
                continue

            found_new = True
            confirmed = 0

            links = [
                {
                    "id": f"server{i+1}",
                    "name": a.get_text(strip=True) or f"Server {i+1}",
                    "url": a["href"]
                }
                for i, a in enumerate(
                    ep.select(".entry-content a[href*='groundbanks.net/post.php']")
                )
            ]

            write_json(REPO_ROOT / "episode" / eid / "links.json", links)
            new_eps.append({"id": eid, "name": f"Episode {num}"})

            if confirmed >= CONFIRM_EPISODES:
                break

        merged = new_eps + existing
        seen, final = set(), []
        for e in merged:
            if e["id"] not in seen:
                final.append(e)
                seen.add(e["id"])

        write_json(REPO_ROOT / "series" / series["id"] / "episodes.json", final)

# ============================================================
# RUN + SAFE PUBLISH
# ============================================================

scrape_playdesi_netflix()

write_json(REPO_ROOT / "site" / SITE_ID / "channels.json", yodesi_channels_payload)

git("add", ".")
status = subprocess.run(
    ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
    capture_output=True,
    text=True
)

if status.stdout.strip():
    git("commit", "-m", "Auto update YoDesi + PlayDesi Netflix")
    git("push", "origin", "main")
    log("Publish complete")
else:
    log("No changes to publish")
