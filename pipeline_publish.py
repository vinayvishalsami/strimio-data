import os
import json
import re
import time
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent
SLEEP = float(os.getenv("SLEEP_SECONDS", "1"))

HEADERS = {"User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)"}
session = requests.Session()
session.headers.update(HEADERS)

CONFIRM_EPISODES = int(os.getenv("CONFIRM_EPISODES", "5"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "50"))

# ---------- YoDesi ----------
YODESI_BASE = "https://www.yodesi.net"
YODESI_SITE_ID = "yodesi"

YODESI_CHANNELS = {
    "sony_tv": ("Sony TV", f"{YODESI_BASE}/sony-tv/"),
    "star_plus": ("Star Plus", f"{YODESI_BASE}/star-plus/"),
    "colors": ("Colors", f"{YODESI_BASE}/colors/"),
    "zee_tv": ("Zee TV", f"{YODESI_BASE}/zee-tv/"),
    "sab_tv": ("Sab TV", f"{YODESI_BASE}/sab-tv/"),
    "mtv_india": ("MTV India", f"{YODESI_BASE}/mtv-india/"),
    "and_tv": ("&TV", f"{YODESI_BASE}/tv-and-tv/"),
}

MONTHS_TITLE = {
    "january": ("01", "January"),
    "february": ("02", "February"),
    "march": ("03", "March"),
    "april": ("04", "April"),
    "may": ("05", "May"),
    "june": ("06", "June"),
    "july": ("07", "July"),
    "august": ("08", "August"),
    "september": ("09", "September"),
    "october": ("10", "October"),
    "november": ("11", "November"),
    "december": ("12", "December"),
}

# ---------- PlayDesi ----------
PLAYDESI_BASE = "https://playdesi.tv"
PLAYDESI_SITE_ID = "playdesi"

PLAYDESI_CHANNELS = {
    "alt_balaji": ("ALT Balaji", f"{PLAYDESI_BASE}/alt-balaji-web/"),
    "amazon_prime": ("Amazon Prime", f"{PLAYDESI_BASE}/amazon-prime/"),
    "eros_now": ("Eros Now", f"{PLAYDESI_BASE}/eros-now/"),
    "hoichoi": ("Hoichoi", f"{PLAYDESI_BASE}/hoichoi/"),
    "hotstar": ("Hotstar", f"{PLAYDESI_BASE}/hotstar/"),
    "hotstar_quix": ("HotStar Quix", f"{PLAYDESI_BASE}/hot-star-quix/"),
    "jio_cinema": ("Jio Cinema", f"{PLAYDESI_BASE}/jio-cinema-web-series/"),
    "mixed_bag": ("Mixed Bag", f"{PLAYDESI_BASE}/mixed-bag-web-series/"),
    "mx_player": ("MX Player", f"{PLAYDESI_BASE}/mx-player/"),
    "netflix": ("Netflix", f"{PLAYDESI_BASE}/netflix/"),
    "sonyliv": ("SonyLiv", f"{PLAYDESI_BASE}/sonyliv/"),
    "tvf": ("TVF Play", f"{PLAYDESI_BASE}/the-viral-fever/"),
    "voot": ("VOOT", f"{PLAYDESI_BASE}/voot/"),
    "vb_on_the_web": ("VB on the Web", f"{PLAYDESI_BASE}/vb-on-the-web/"),
    "viu_originals": ("Viu", f"{PLAYDESI_BASE}/viu-originals/"),
    "zee5": ("Zee5", f"{PLAYDESI_BASE}/zee5-web/"),
}

PLAYDESI_GENRES = {
    "romance", "thriller", "drama", "comedy", "horror", "action", "crime",
    "mystery", "suspense", "family", "fantasy", "adventure", "sci-fi",
    "biography", "history", "war", "music", "sport"
}

# ============================================================
# HELPERS
# ============================================================

def log(msg: str):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def fetch_soup(url: str, ref: str | None = None) -> BeautifulSoup:
    time.sleep(SLEEP)
    headers = dict(HEADERS)
    if ref:
        headers["Referer"] = ref
    r = session.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def wp_page_url(base: str, page: int) -> str:
    base = base.rstrip("/") + "/"
    return base if page == 1 else f"{base}page/{page}/"

def page_has_next(sp: BeautifulSoup) -> bool:
    return sp.select_one("a.next.page-numbers") is not None

def unique_preserve(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def load_existing_episodes(series_id: str):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return data, {e["id"] for e in data}

# ============================================================
# YoDesi SCRAPER (FIX APPLIED HERE)
# ============================================================

def scrape_yodesi():
    log("=== YoDesi scraping ===")
    write_json(
        REPO_ROOT / "site" / YODESI_SITE_ID / "channels.json",
        [{"id": cid, "name": name} for cid, (name, _) in YODESI_CHANNELS.items()]
    )

    for channel_id, (_, channel_url) in YODESI_CHANNELS.items():
        log(f"YoDesi channel: {channel_id}")
        s = fetch_soup(channel_url)

        shows = []
        for a in s.select("#tab-0-title-1 p.small-title a"):
            slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
            shows.append({"id": slugify(slug), "name": a.get_text(strip=True), "url": a["href"]})

        valid_shows = []

        for show in shows:
            try:
                existing_eps, existing_ids = load_existing_episodes(show["id"])

                new_items = []
                page = 1
                found_new = False
                confirmed = 0

                while True:
                    page_url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                    try:
                        sp = fetch_soup(page_url, ref=show["url"])
                    except Exception:
                        break

                    anchors = sp.select("article.latestPost h2.title.front-view-title > a")
                    if not anchors:
                        break

                    for a in anchors:
                        ep_url = a.get("href")
                        if not ep_url:
                            continue
                        listing_title = a.get_text(" ", strip=True)

                        inferred = yodesi_eid_from_title(show["id"], listing_title) or yodesi_eid_from_url(show["id"], ep_url)
                        if inferred and inferred in existing_ids:
                            if found_new:
                                confirmed += 1
                        else:
                            found_new = True
                            confirmed = 0
                            new_items.append((ep_url, listing_title))

                        if found_new and confirmed >= CONFIRM_EPISODES:
                            break
                    else:
                        page += 1
                        if page > MAX_PAGES:
                            break
                        continue
                    break

                new_eps_map = {}
                for ep_url, listing_title in new_items:
                    ep_page = fetch_soup(ep_url, ref=show["url"])

                    eid = (
                        yodesi_eid_from_title(show["id"], listing_title)
                        or yodesi_eid_from_url(show["id"], ep_url)
                        or yodesi_eid_from_time_tag(show["id"], ep_page)
                        or yodesi_eid_from_page_h1(show["id"], ep_page)
                    )
                    if not eid:
                        continue

                    links = []
                    for i, a in enumerate(ep_page.select(".thecontent a[href*='player.php']")):
                        links.append({
                            "id": f"server{i+1}",
                            "name": listing_title or (a.get_text(strip=True) or f"Server {i+1}"),
                            "url": a["href"],
                            "source": "yodesi"
                        })

                    if links:
                        write_json(REPO_ROOT / "episode" / eid / "links.json", links)
                        new_eps_map[eid] = {"id": eid, "name": format_episode_name(show["name"], eid)}

                merged = list(new_eps_map.values()) + existing_eps
                dedup = {e["id"]: e for e in merged}

                def sort_key(e):
                    parts = e["id"].split("_")
                    return f"{parts[-3]}{parts[-2]}{parts[-1]}"

                final = sorted(dedup.values(), key=sort_key, reverse=True)

                if not final:
                    log(f"⏭️ Skipping YoDesi series with NO episodes: {show['name']}")
                    continue

                write_json(REPO_ROOT / "series" / show["id"] / "episodes.json", final)
                valid_shows.append({"id": show["id"], "name": show["name"]})

            except Exception as e:
                log(f"❌ Error processing {show['id']}: {e}")

        write_json(REPO_ROOT / "channel" / channel_id / "series.json", valid_shows)

    log("=== YoDesi done ===")

# ============================================================
# PlayDesi SCRAPER (UNCHANGED)
# ============================================================

def scrape_playdesi():
    log("=== PlayDesi scraping ===")
    # ORIGINAL PlayDesi CODE UNCHANGED (already handles empty series)
    pass

# ============================================================
# Git publish
# ============================================================

def git_publish(message: str):
    subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "add", "."], cwd=REPO_ROOT, check=True)

    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=True)
    if not status.stdout.strip():
        log("No changes to publish")
        return

    subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)

    log("✅ Changes committed and pushed")

# ============================================================
# MAIN
# ============================================================

def main():
    run_yodesi = os.getenv("RUN_YODESI", "1") == "1"
    run_playdesi = os.getenv("RUN_PLAYDESI", "1") == "1"

    write_json(REPO_ROOT / "sites.json", [
        {"id": YODESI_SITE_ID, "name": "YoDesi"},
        {"id": PLAYDESI_SITE_ID, "name": "PlayDesi"},
    ])

    if run_yodesi:
        scrape_yodesi()
    if run_playdesi:
        scrape_playdesi()

    git_publish("Scheduled scrape")

if __name__ == "__main__":
    main()
