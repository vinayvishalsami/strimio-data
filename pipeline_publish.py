import json
import re
import time
import subprocess
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

REPO_ROOT = Path(__file__).resolve().parent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)",
    "Referer": PLAYDESI_BASE,
}

CONFIRM_EPISODES = 5
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

def load_existing(series_id):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text())
    return data, {e["id"] for e in data}

# ============================================================
# GROUNDBANKS VALIDATION (CRITICAL)
# ============================================================

def groundbanks_is_valid(url, expected_show, episode_no):
    """
    Ensures GroundBanks page belongs to correct show & episode.
    """
    try:
        sp = soup(url, ref=PLAYDESI_BASE)
    except Exception:
        return False

    og = sp.select_one("meta[property='og:title']")
    if not og:
        return False

    title = og.get("content", "").lower()
    show = expected_show.lower()

    if show not in title:
    return False

# VIU Originals GroundBanks pages often do NOT include episode numbers
# Only enforce correct series match, not episode match
return True

# ============================================================
# SCRAPER — VIU ORIGINALS (WEB SERIES ONLY)
# ============================================================

def scrape_viu_originals():
    log("Scraping PlayDesi – VIU Originals")

    index = soup(CHANNEL_URL)

    series_entries = []

    for a in index.select("a[href*='/watch-online/']"):
        title = a.get_text(strip=True)
        url = a["href"]

        season_match = re.search(r"(.+?)\s+season\s+(\d+)", title, re.I)

        if season_match:
            show = season_match.group(1).strip()
            season = int(season_match.group(2))
        else:
            # single season
            show = title
            season = 1

        sid = f"{slugify(show)}__season_{season}"

        series_entries.append({
            "id": sid,
            "name": f"{show} – Season {season}",
            "show": show,
            "url": url
        })

    write_json(
        REPO_ROOT / "channel" / CHANNEL_ID / "series.json",
        [{"id": s["id"], "name": s["name"]} for s in series_entries]
    )

    # ========================================================
    # EPISODES
    # ========================================================

    for series in series_entries:
        log(f"Scraping episodes: {series['name']}")

        existing, existing_ids = load_existing(series["id"])
        page = soup(series["url"], ref=CHANNEL_URL)

        ep_links = []
        for a in page.select("a[href*='episode']"):
            if a["href"].startswith(PLAYDESI_BASE):
                ep_links.append(a["href"])

        ep_links = list(dict.fromkeys(ep_links))

        new_eps = []
        confirmed = 0

        for ep_url in ep_links:
            ep = soup(ep_url, ref=series["url"])
            h1 = ep.select_one("h1")

            if not h1:
                continue

            m = re.search(r"episode\s+(\d+)", h1.get_text(), re.I)
            if not m:
                continue

            ep_no = int(m.group(1))
            eid = f"{series['id']}_ep{ep_no:02d}"

            if eid in existing_ids:
                confirmed += 1
                if confirmed >= CONFIRM_EPISODES:
                    break
                continue

            valid_links = []

            for i, a in enumerate(ep.select(".entry-content a[href*='groundbanks.net']")):
                gb_url = a["href"]

                if groundbanks_is_valid(
                    gb_url,
                    series["show"],
                    ep_no
                ):
                    valid_links.append({
                        "id": f"server{i+1}",
                        "name": a.get_text(strip=True) or f"Server {i+1}",
                        "url": gb_url
                    })

            if not valid_links:
                continue  # safer to drop than show wrong video

            write_json(
                REPO_ROOT / "episode" / eid / "links.json",
                valid_links
            )

            new_eps.append({
                "id": eid,
                "name": f"Episode {ep_no}"
            })

        merged = new_eps + existing
        seen, final = set(), []

        for e in merged:
            if e["id"] not in seen:
                final.append(e)
                seen.add(e["id"])

        write_json(
            REPO_ROOT / "series" / series["id"] / "episodes.json",
            final
        )

# ============================================================
# RUN + SAFE COMMIT
# ============================================================

scrape_viu_originals()

write_json(
    REPO_ROOT / "sites.json",
    [
        {"id": "yodesi", "name": "YoDesi"},
        {"id": "playdesi", "name": "PlayDesi"},
    ]
)

subprocess.run(["git", "add", "."], cwd=REPO_ROOT)

status = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=REPO_ROOT,
    capture_output=True,
    text=True
)

if status.stdout.strip():
    subprocess.run(
        ["git", "commit", "-m", "Fix VIU Originals scraping & episode validation"],
        cwd=REPO_ROOT
    )
    subprocess.run(["git", "push"], cwd=REPO_ROOT)
    log("Publish complete")
else:
    log("No changes to publish")
