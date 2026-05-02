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
SLEEP = 1

HEADERS = {
    "User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)",
}

session = requests.Session()
session.headers.update(HEADERS)

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

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}

# ---------- PlayDesi ----------
PLAYDESI_BASE = "https://playdesi.tv"
PLAYDESI_SITE_ID = "playdesi"

# Only web-series channels (exclude Movies + Dubbed buckets; you can add later)
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
    "gujarati": ("Gujarati Web Series", f"{PLAYDESI_BASE}/gujarati-web-series/"),
    "standup": ("Stand-Up Comedy", f"{PLAYDESI_BASE}/stand-up-comedy/"),
}

# If you want to temporarily test only one PlayDesi channel, set this:
# e.g. PLAYDESI_CHANNEL_ALLOWLIST = {"viu_originals"}
PLAYDESI_CHANNEL_ALLOWLIST = None

# If you want to temporarily test only one series page per channel (faster):
PLAYDESI_LIMIT_SERIES_PER_CHANNEL = 1  # e.g. 1

CONFIRM_EPISODES = 5

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
    r = session.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th') }"

def load_existing_episodes(series_id: str):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return data, {e["id"] for e in data}

def git_commit_push(message: str):
    subprocess.run(["git", "add", "."], cwd=REPO_ROOT, check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True
    )

    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
        log("✅ Changes committed and pushed")
    else:
        log("No changes to publish")

# ============================================================
# YoDesi SCRAPER (unchanged behavior + adds source field)
# ============================================================

def infer_yodesi_episode_id(series_id: str, slug: str):
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?-([a-z]+)-(\d{4})", slug)
    if m and m.group(2) in MONTHS:
        return f"{series_id}_{m.group(3)}_{MONTHS[m.group(2)]}_{int(m.group(1)):02d}"
    return None

def scrape_yodesi():
    log("=== YoDesi scraping شروع ===")

    # Register YoDesi channels
    write_json(REPO_ROOT / "site" / YODESI_SITE_ID / "channels.json",
               [{"id": cid, "name": name} for cid, (name, _) in YODESI_CHANNELS.items()])

    for channel_id, (_, channel_url) in YODESI_CHANNELS.items():
        log(f"YoDesi channel: {channel_id}")
        s = fetch_soup(channel_url)

        shows = []
        for a in s.select("#tab-0-title-1 p.small-title a"):
            slug = urlparse(a["href"]).path.rstrip("/").split("/")[-1]
            shows.append({
                "id": slugify(slug),
                "name": a.get_text(strip=True),
                "url": a["href"]
            })

        write_json(REPO_ROOT / "channel" / channel_id / "series.json",
                   [{"id": x["id"], "name": x["name"]} for x in shows])

        # Episodes per show (incremental)
        for show in shows:
            existing_eps, existing_ids = load_existing_episodes(show["id"])

            new_urls = []
            page = 1
            found_new = False
            confirmed = 0

            while True:
                page_url = show["url"] if page == 1 else f"{show['url']}page/{page}/"
                try:
                    sp = fetch_soup(page_url, ref=show["url"])
                except Exception:
                    break

                links = sp.select("article.latestPost h2.title.front-view-title > a")
                if not links:
                    break

                for a in links:
                    slug = a["href"].split("/")[-2]
                    inferred = infer_yodesi_episode_id(show["id"], slug)

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
                ep_page = fetch_soup(ep_url, ref=show["url"])
                text = ep_page.get_text(" ").lower()
                m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?\s+([a-z]+)\s+(\d{4})", text)
                if not m:
                    continue

                day = int(m.group(1))
                month_name = m.group(2)
                year = m.group(3)
                if month_name not in MONTHS:
                    continue

                eid = f"{show['id']}_{year}_{MONTHS[month_name]}_{day:02d}"

                # YoDesi links stay direct (player.php); include source field for routing
                links = []
                for i, a in enumerate(ep_page.select(".thecontent a[href*='player.php']")):
                    links.append({
                        "id": f"server{i+1}",
                        "name": a.get_text(strip=True) or f"Server {i+1}",
                        "url": a["href"],
                        "source": "yodesi"
                    })

                if not links:
                    continue

                write_json(REPO_ROOT / "episode" / eid / "links.json", links)

                new_eps.append({
                    "id": eid,
                    "name": f"{show['name']} {ordinal(day)} {month_name.title()} {year}"
                })

            merged = new_eps + existing_eps
            seen = set()
            final = []
            for e in merged:
                if e["id"] not in seen:
                    final.append(e)
                    seen.add(e["id"])

            write_json(REPO_ROOT / "series" / show["id"] / "episodes.json", final)

    log("=== YoDesi scraping complete ===")

# ============================================================
# PlayDesi SCRAPER (web series only; store episode page URL only)
# ============================================================

def playdesi_series_page_has_episodes(series_url: str) -> bool:
    """
    Web-series validation:
    Only accept series pages that list episode posts (article -> entry-title -> link),
    and those links look like episodic pages containing '-episode-' in URL.
    """
    try:
        sp = fetch_soup(series_url, ref=PLAYDESI_BASE)
    except Exception:
        return False

    eps = []
    for a in sp.select("article h2.entry-title a"):
        href = a.get("href", "")
        if "-episode-" in href:
            eps.append(href)
    return len(eps) > 0

def scrape_playdesi():
    log("=== PlayDesi scraping شروع ===")

    # Register PlayDesi channels (controls what appears in app)
    playdesi_channel_list = []
    for cid, (name, url) in PLAYDESI_CHANNELS.items():
        if PLAYDESI_CHANNEL_ALLOWLIST and cid not in PLAYDESI_CHANNEL_ALLOWLIST:
            continue
        playdesi_channel_list.append({"id": cid, "name": name})

    write_json(REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json", playdesi_channel_list)

    for channel_id, (channel_name, channel_url) in PLAYDESI_CHANNELS.items():
        if PLAYDESI_CHANNEL_ALLOWLIST and channel_id not in PLAYDESI_CHANNEL_ALLOWLIST:
            continue

        log(f"PlayDesi channel: {channel_name}")
        index = fetch_soup(channel_url, ref=PLAYDESI_BASE)

        # Candidate series pages from channel index
        candidates = []
        for a in index.select("a[href*='/watch-online/']"):
            href = a.get("href")
            if not href or not href.startswith(PLAYDESI_BASE):
                continue

            title = a.get_text(strip=True)
            if not title:
                continue

            # Deduplicate
            candidates.append((title, href))

        # Unique by URL
        seen_urls = set()
        unique = []
        for t, u in candidates:
            if u not in seen_urls:
                unique.append((t, u))
                seen_urls.add(u)

        series_entries = []
        for title, series_url in unique:
            # Optional: limit for speed
            if PLAYDESI_LIMIT_SERIES_PER_CHANNEL and len(series_entries) >= PLAYDESI_LIMIT_SERIES_PER_CHANNEL:
                break

            # Determine show + season from title (best-effort)
            m = re.search(r"(.+?)\s+season\s+(\d+)", title, re.I)
            if m:
                show = m.group(1).strip()
                season = int(m.group(2))
            else:
                show = title.strip()
                season = 1  # later validated by episodic check

            series_id = f"{slugify(show)}__season_{season}"

            # ✅ web-series only: series page must list episodic episode posts
            if not playdesi_series_page_has_episodes(series_url):
                continue

            series_entries.append({
                "id": series_id,
                "name": f"{show} – Season {season}",
                "show": show,
                "url": series_url
            })

        # Write channel series list
        write_json(
            REPO_ROOT / "channel" / channel_id / "series.json",
            [{"id": s["id"], "name": s["name"]} for s in sorted(series_entries, key=lambda x: x["id"])]
        )

        # Episodes for each series
        for series in series_entries:
            log(f"PlayDesi series episodes: {series['name']}")

            existing_eps, existing_ids = load_existing_episodes(series["id"])
            sp = fetch_soup(series["url"], ref=channel_url)

            ep_pages = []
            for a in sp.select("article h2.entry-title a"):
                href = a.get("href")
                if href and href.startswith(PLAYDESI_BASE) and "-episode-" in href:
                    ep_pages.append(href)

            # Deduplicate
            ep_pages = list(dict.fromkeys(ep_pages))

            new_eps = []
            for ep_url in ep_pages:
                ep_page = fetch_soup(ep_url, ref=series["url"])

                h1 = ep_page.select_one("h1")
                if not h1:
                    continue

                mm = re.search(r"episode\s+(\d+)", h1.get_text(), re.I)
                if not mm:
                    # Fallback: episode number from URL
                    mm = re.search(r"-episode-(\d+)-", ep_url, re.I)
                if not mm:
                    continue

                ep_no = int(mm.group(1))
                ep_id = f"{series['id']}_ep{ep_no:02d}"

                if ep_id in existing_ids:
                    continue

                # ✅ store ONLY PlayDesi episode page URL (no GroundBanks)
                links = [{
                    "id": "watch",
                    "name": "Watch on PlayDesi",
                    "url": ep_url,
                    "source": "playdesi"
                }]

                write_json(REPO_ROOT / "episode" / ep_id / "links.json", links)
                new_eps.append({"id": ep_id, "name": f"Episode {ep_no}"})

            merged = new_eps + existing_eps
            seen = set()
            final = []
            for e in merged:
                if e["id"] not in seen:
                    final.append(e)
                    seen.add(e["id"])

            # Sort by episode number if possible
            def ep_sort_key(e):
                m = re.search(r"_ep(\d+)$", e["id"])
                return int(m.group(1)) if m else 999999

            write_json(REPO_ROOT / "series" / series["id"] / "episodes.json",
                       sorted(final, key=ep_sort_key))

    log("=== PlayDesi scraping complete ===")

# ============================================================
# MAIN
# ============================================================

def main():
    # Register sites
    write_json(
        REPO_ROOT / "sites.json",
        [
            {"id": YODESI_SITE_ID, "name": "YoDesi"},
            {"id": PLAYDESI_SITE_ID, "name": "PlayDesi"},
        ]
    )

    scrape_yodesi()
    scrape_playdesi()

    git_commit_push("Update YoDesi + PlayDesi (web series only; PlayDesi episode URLs only)")

if __name__ == "__main__":
    main()
