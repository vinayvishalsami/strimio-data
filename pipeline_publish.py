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
    "standup": ("Stand-Up Comedy", f"{PLAYDESI_BASE}/stand-up-comedy/"),
}

CONFIRM_EPISODES = 5  # incremental stop threshold

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
# YoDesi: Robust episode ID extraction (FIX FOR MISSING DATE GAPS)
# ============================================================

def infer_yodesi_episode_id(series_id: str, slug: str):
    """
    Tries to infer ID from YoDesi slug like: 19th-april-2026-...
    """
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?-([a-z]+)-(\d{4})", slug)
    if m and m.group(2) in MONTHS:
        return f"{series_id}_{m.group(3)}_{MONTHS[m.group(2)]}_{int(m.group(1)):02d}"
    return None

def yodesi_eid_from_url(series_id: str, ep_url: str):
    """
    Prefer extracting the date from the URL slug (most reliable).
    """
    try:
        slug = ep_url.rstrip("/").split("/")[-2]
    except Exception:
        return None
    return infer_yodesi_episode_id(series_id, slug)

def yodesi_eid_from_time_tag(series_id: str, sp: BeautifulSoup):
    """
    Fallback: use <time datetime="YYYY-MM-DD..."> if present.
    """
    t = sp.select_one("time[datetime]")
    if not t:
        return None
    dt = t.get("datetime", "")
    if len(dt) < 10:
        return None
    date_part = dt[:10]  # YYYY-MM-DD
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
        return None
    y, m, d = date_part.split("-")
    return f"{series_id}_{y}_{m}_{d}"

def yodesi_eid_from_text(series_id: str, sp: BeautifulSoup):
    """
    Last resort: regex on page text.
    """
    text = sp.get_text(" ").lower()
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?\s+([a-z]+)\s+(\d{4})", text)
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2)
    year = m.group(3)
    if month_name not in MONTHS:
        return None
    return f"{series_id}_{year}_{MONTHS[month_name]}_{day:02d}"

# ============================================================
# YoDesi SCRAPER (with robust ID; adds source=yodesi)
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
            shows.append({
                "id": slugify(slug),
                "name": a.get_text(strip=True),
                "url": a["href"]
            })

        write_json(
            REPO_ROOT / "channel" / channel_id / "series.json",
            [{"id": x["id"], "name": x["name"]} for x in shows]
        )

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
                    href = a["href"]
                    slug = href.rstrip("/").split("/")[-2]
                    inferred = infer_yodesi_episode_id(show["id"], slug)

                    if inferred and inferred in existing_ids:
                        if found_new:
                            confirmed += 1
                    else:
                        found_new = True
                        confirmed = 0
                        new_urls.append(href)

                    if found_new and confirmed >= CONFIRM_EPISODES:
                        break
                else:
                    page += 1
                    continue
                break

            new_eps = []
            for ep_url in new_urls:
                sp = fetch_soup(ep_url, ref=show["url"])

                # ✅ Robust ID: URL slug -> <time> -> text
                eid = (
                    yodesi_eid_from_url(show["id"], ep_url)
                    or yodesi_eid_from_time_tag(show["id"], sp)
                    or yodesi_eid_from_text(show["id"], sp)
                )

                if not eid:
                    continue

                # YoDesi links (player.php). Add source=yodesi.
                links = []
                for i, a in enumerate(sp.select(".thecontent a[href*='player.php']")):
                    links.append({
                        "id": f"server{i+1}",
                        "name": a.get_text(strip=True) or f"Server {i+1}",
                        "url": a["href"],
                        "source": "yodesi"
                    })

                if not links:
                    continue

                write_json(REPO_ROOT / "episode" / eid / "links.json", links)

                # Pretty name from eid date (seriesid_YYYY_MM_DD)
                parts = eid.split("_")
                year, month, day = parts[-3], parts[-2], parts[-1]
                new_eps.append({
                    "id": eid,
                    "name": f"{show['name']} {int(day)}-{month}-{year}"
                })

            merged = new_eps + existing_eps
            seen = set()
            final = []
            for e in merged:
                if e["id"] not in seen:
                    final.append(e)
                    seen.add(e["id"])

            write_json(REPO_ROOT / "series" / show["id"] / "episodes.json", final)

    log("=== YoDesi done ===")

# ============================================================
# PlayDesi SCRAPER (alphabetical-safe series discovery; web series only)
# Stores ONLY episode page URL (no GroundBanks), source=playdesi
# ============================================================

def collect_all_series_pages_from_channel(channel_url: str) -> list[tuple[str, str]]:
    """
    Collect series pages across channel listing + pagination (/page/2/ ...).
    No cap: alphabetical lists must be scanned fully.
    """
    results = []
    seen = set()

    page = 1
    while True:
        url = channel_url if page == 1 else f"{channel_url.rstrip('/')}/page/{page}/"
        try:
            sp = fetch_soup(url, ref=PLAYDESI_BASE)
        except Exception:
            break

        found_any = False
        for a in sp.select("a[href*='/watch-online/']"):
            href = a.get("href")
            if not href or not href.startswith(PLAYDESI_BASE):
                continue
            title = a.get_text(strip=True) or href
            if href not in seen:
                seen.add(href)
                results.append((title, href))
            found_any = True

        if not found_any:
            break

        page += 1
        if page > 50:
            break

    return results

def series_page_has_episodes(series_url: str) -> bool:
    """
    Web-series filter: series page must list episode posts with '-episode-' in href.
    """
    try:
        sp = fetch_soup(series_url, ref=PLAYDESI_BASE)
    except Exception:
        return False

    for a in sp.select("article h2.entry-title a"):
        href = a.get("href", "")
        if "-episode-" in href:
            return True
    return False

def scrape_playdesi():
    log("=== PlayDesi scraping ===")

    write_json(
        REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json",
        [{"id": cid, "name": name} for cid, (name, _) in PLAYDESI_CHANNELS.items()]
    )

    for channel_id, (channel_name, channel_url) in PLAYDESI_CHANNELS.items():
        log(f"PlayDesi channel: {channel_name}")

        candidates = collect_all_series_pages_from_channel(channel_url)

        series_entries = []
        seen_series = set()

        for title, series_url in candidates:
            m = re.search(r"(.+?)\s+season\s+(\d+)", title, re.I)
            if m:
                show = m.group(1).strip()
                season = int(m.group(2))
            else:
                show = title.strip()
                season = 1

            series_id = f"{slugify(show)}__season_{season}"
            if series_id in seen_series:
                continue

            if not series_page_has_episodes(series_url):
                continue

            seen_series.add(series_id)
            series_entries.append({
                "id": series_id,
                "name": f"{show} – Season {season}",
                "url": series_url
            })

        write_json(
            REPO_ROOT / "channel" / channel_id / "series.json",
            [{"id": s["id"], "name": s["name"]} for s in sorted(series_entries, key=lambda x: x["id"])]
        )

        for series in series_entries:
            log(f"PlayDesi series episodes: {series['name']}")

            existing_eps, existing_ids = load_existing_episodes(series["id"])

            page = 1
            found_new = False
            confirmed = 0
            new_eps = []

            while True:
                list_url = series["url"] if page == 1 else f"{series['url'].rstrip('/')}/page/{page}/"
                try:
                    sp = fetch_soup(list_url, ref=channel_url)
                except Exception:
                    break

                ep_pages = []
                for a in sp.select("article h2.entry-title a"):
                    href = a.get("href")
                    if href and href.startswith(PLAYDESI_BASE) and "-episode-" in href:
                        ep_pages.append(href)

                if not ep_pages:
                    break

                ep_pages = list(dict.fromkeys(ep_pages))

                for ep_url in ep_pages:
                    mm = re.search(r"-episode-(\d+)-", ep_url, re.I)
                    if not mm:
                        # fallback to title
                        ep_page = fetch_soup(ep_url, ref=series["url"])
                        h1 = ep_page.select_one("h1")
                        if not h1:
                            continue
                        mm = re.search(r"episode\s+(\d+)", h1.get_text(), re.I)
                    if not mm:
                        continue

                    ep_no = int(mm.group(1))
                    ep_id = f"{series['id']}_ep{ep_no:02d}"

                    if ep_id in existing_ids:
                        if found_new:
                            confirmed += 1
                        continue

                    found_new = True
                    confirmed = 0

                    write_json(
                        REPO_ROOT / "episode" / ep_id / "links.json",
                        [{
                            "id": "watch",
                            "name": "Watch on PlayDesi",
                            "url": ep_url,
                            "source": "playdesi"
                        }]
                    )

                    new_eps.append({"id": ep_id, "name": f"Episode {ep_no}"})

                    if found_new and confirmed >= CONFIRM_EPISODES:
                        break

                if found_new and confirmed >= CONFIRM_EPISODES:
                    break

                page += 1
                if page > 50:
                    break

            merged = new_eps + existing_eps
            seen = set()
            final = []
            for e in merged:
                if e["id"] not in seen:
                    final.append(e)
                    seen.add(e["id"])

            def ep_sort_key(e):
                m = re.search(r"_ep(\d+)$", e["id"])
                return int(m.group(1)) if m else 999999

            write_json(REPO_ROOT / "series" / series["id"] / "episodes.json",
                       sorted(final, key=ep_sort_key))

    log("=== PlayDesi done ===")

# ============================================================
# MAIN
# ============================================================

def main():
    write_json(
        REPO_ROOT / "sites.json",
        [
            {"id": YODESI_SITE_ID, "name": "YoDesi"},
            {"id": PLAYDESI_SITE_ID, "name": "PlayDesi"},
        ]
    )

    scrape_yodesi()
    scrape_playdesi()

    git_commit_push("Update YoDesi (robust date IDs) + PlayDesi (alphabetical-safe series; web series only)")

if __name__ == "__main__":
    main()
