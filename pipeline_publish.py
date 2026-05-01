# YO DESI SCRAPER + AUTO PUBLISH
# OPTIMIZED INCREMENTAL VERSION
# FIXED: Early exit condition and redundant HTTP requests

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

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def git(*args):
    subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True)

def load_existing_series_data(series_id):
    """Loads existing episodes and returns (list_of_dicts, set_of_ids)"""
    path = REPO_ROOT / "series" / series_id / "episodes.json"
    if not path.exists():
        return [], set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, {e["id"] for e in data}
    except Exception:
        return [], set()

def infer_id_from_slug(series_id, slug):
    """Extracts date from slug to match the eid format: series_YYYY_MM_DD"""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?-([a-z]+)-(\d{4})", slug.lower())
    if m and m.group(2) in MONTHS:
        day = int(m.group(1))
        month = MONTHS[m.group(2)]
        year = m.group(3)
        return f"{series_id}_{year}_{month}_{day:02d}"
    return f"{series_id}_{slug}"

# ---------------- SITE ----------------

log("Writing site metadata")
write_json(REPO_ROOT / "sites.json", [{"id": SITE_ID, "name": SITE_NAME}])
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

    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        [{"id": x["id"], "name": x["name"]} for x in series]
    )

    for show in series:
        log(f"Scraping episodes: {show['name']}")
        existing_episodes, existing_ids = load_existing_series_data(show["id"])

        page = 1
        new_urls = []
        confirmed_seen = 0
        should_continue = True

        # Phase 1: Collect only NEW URLs
        while should_continue:
            try:
                url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                sp = soup(url)
            except HTTPError as e:
                if e.response.status_code == 404: break
                raise

            links = sp.select("article.latestPost h2.title.front-view-title > a")
            if not links: break

            for a in links:
                ep_url = a["href"]
                slug = ep_url.rstrip("/").split("/")[-1]
                inferred_id = infer_id_from_slug(show["id"], slug)

                if inferred_id in existing_ids:
                    confirmed_seen += 1
                else:
                    confirmed_seen = 0
                    if ep_url not in new_urls:
                        new_urls.append(ep_url)

                if confirmed_seen >= CONFIRM_EPISODES:
                    should_continue = False
                    break

            if not should_continue: break
            page += 1

        if not new_urls:
            log(f"No new episodes for {show['name']}")
            continue

        # Phase 2: Scrape only the new URLs
        new_episodes = []
        for ep_url in new_urls:
            log(f"Fetching new episode: {ep_url}")
            sp = soup(ep_url)
            h1 = sp.select_one("h1.title.entry-title")
            if not h1: continue

            title_text = h1.get_text(strip=True).lower()
            m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})", title_text)
            if not m or m.group(2) not in MONTHS: continue

            day = int(m.group(1))
            month = MONTHS[m.group(2)]
            year = m.group(3)
            eid = f"{show['id']}_{year}_{month}_{day:02d}"

            links = [
                {"id": f"server{i+1}", "name": a.get_text(strip=True) or "Server", "url": a["href"]}
                for i, a in enumerate(sp.select(".thecontent a[href*='player.php?id=']"))
            ]

            new_episodes.append({
                "id": eid,
                "name": f"{show['name']} {day}-{month}-{year}",
                "links": links
            })

            # Write individual links file for new episode
            write_json(REPO_ROOT / "episode" / eid / "links.json", links)

        # Merge and save
        all_episodes = new_episodes + existing_episodes
        # Remove duplicates if any (by ID)
        seen_ids = set()
        final_list = []
        for e in all_episodes:
            if e["id"] not in seen_ids:
                final_list.append(e)
                seen_ids.add(e["id"])

        write_json(
            REPO_ROOT / "series" / show["id"] / "episodes.json",
            [{"id": e["id"], "name": e["name"]} for e in final_list]
        )
        log(f"Added {len(new_episodes)} new episodes to {show['name']}")

# ---------------- CHANNEL LIST ----------------

write_json(REPO_ROOT / "site" / SITE_ID / "channels.json", channels_payload)

# ================= PLAYDESI – NETFLIX =================
# ================= PLAYDESI – NETFLIX =================
# ================= PLAYDESI – NETFLIX =================
# ================= PLAYDESI – NETFLIX =================
# ================= PLAYDESI – NETFLIX =================

PLAYDESI_BASE = "https://www.playdesi.net"
PLAYDESI_SITE_ID = "playdesi"

def scrape_playdesi_netflix():
    log("Scraping PlayDesi – Netflix")

    CHANNEL_ID = "netflix"
    CHANNEL_NAME = "Netflix"
    CHANNEL_URL = f"{PLAYDESI_BASE}/netflix/"

    # ----- Write channel list (once per run) -----
    write_json(
        REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json",
        [{"id": CHANNEL_ID, "name": CHANNEL_NAME}],
    )

    # ----- Discover series (Netflix shows) -----
    s = soup(CHANNEL_URL)

    # ⚠️ SELECTOR WILL BE VERIFIED IN FIRST RUN
    show_links = s.select("article h2 a")

    series_entries = []

    for a in show_links:
        show_url = a["href"]
        show_name = a.get_text(strip=True)

        # Visit show page to find seasons
        sp = soup(show_url)

        season_links = sp.select("a[href*='season']")

        for season_a in season_links:
            season_url = season_a["href"]
            season_text = season_a.get_text(strip=True)

            # Extract season number
            m = re.search(r"season\s*(\d+)", season_text.lower())
            if not m:
                continue

            season_num = int(m.group(1))

            show_slug = slug_to_id(show_name.lower().replace(" ", "-"))
            series_id = f"{show_slug}__season_{season_num}"

            series_entries.append({
                "id": series_id,
                "name": f"{show_name} – Season {season_num}",
                "url": season_url,
            })

    # Alphabetical stability
    series_entries = sorted(series_entries, key=lambda x: x["id"])

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{"id": s["id"], "name": s["name"]} for s in series_entries],
    )

    # ----- Scrape episodes per season -----
    for series in series_entries:
        log(f"Scraping PlayDesi Netflix series: {series['name']}")

        existing_eps, existing_ids = load_existing_series_data(series["id"])

        new_eps = []
        confirmed_seen = 0
        found_new = False

        sp = soup(series["url"])

        # ⚠️ SELECTOR TO VERIFY
        episode_links = sp.select("article h2 a")

        for ep_num, a in enumerate(episode_links, start=1):
            eid = f"{series['id']}_ep{ep_num:02d}"

            if eid in existing_ids:
                if found_new:
                    confirmed_seen += 1
            else:
                found_new = True
                confirmed_seen = 0

                ep_url = a["href"]
                ep_page = soup(ep_url)

                stream_links = [
                    {
                        "id": f"server{i+1}",
                        "name": link.get_text(strip=True) or "Server",
                        "url": link["href"],
                    }
                    for i, link in enumerate(
                        ep_page.select(".thecontent a[href^='http']")
                    )
                ]

                new_eps.append({
                    "id": eid,
                    "name": f"Episode {ep_num}",
                    "links": stream_links,
                })

                write_json(
                    REPO_ROOT / "episode" / eid / "links.json",
                    stream_links,
                )

            # ✅ Incremental stop condition
            if found_new and confirmed_seen >= 5:
                break

        if new_eps:
            merged = new_eps + existing_eps
            seen = set()
            final = []
            for e in merged:
                if e["id"] not in seen:
                    final.append(e)
                    seen.add(e["id"])

            write_json(
                REPO_ROOT / "series" / series["id"] / "episodes.json",
                [{"id": e["id"], "name": e["name"]} for e in final],
            )

            log(f"Added {len(new_eps)} new episodes to {series['name']}")
        else:
            log(f"No new episodes for {series['name']}")


# ---------------- PUBLISH ----------------

log("Publishing to GitHub")
git("add", ".")
status = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True)

if status.stdout.strip():
    git("commit", "-m", f"Auto update {datetime.utcnow().isoformat()}")
    git("push", "origin", "main")
    log("Publish complete")
else:
    log("No changes to publish")

