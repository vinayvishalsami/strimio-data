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


def upsert_site(site_id: str, site_name: str):
    sites_path = REPO_ROOT / "sites.json"

    if sites_path.exists():
        sites = json.loads(sites_path.read_text(encoding="utf-8"))
    else:
        sites = []

    if not any(s["id"] == site_id for s in sites):
        sites.append({"id": site_id, "name": site_name})
        write_json(sites_path, sites)

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
# YoDesi (title-first date IDs + consistent naming)
# ============================================================

def parse_date_from_text(text: str):
    if not text:
        return None
    t = text.lower()
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th|h)?\s+([a-z]+)\s+(\d{4})\b", t)
    if not m:
        return None
    day = int(m.group(1))
    month = m.group(2)
    year = m.group(3)
    if month not in MONTHS_TITLE:
        return None
    mm, month_title = MONTHS_TITLE[month]
    return (year, mm, f"{day:02d}", month_title)

def yodesi_eid_from_title(series_id: str, title_text: str):
    parsed = parse_date_from_text(title_text)
    if not parsed:
        return None
    year, mm, dd, _ = parsed
    return f"{series_id}_{year}_{mm}_{dd}"

def yodesi_eid_from_url(series_id: str, ep_url: str):
    try:
        slug = ep_url.rstrip("/").split("/")[-2]
    except Exception:
        return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?-([a-z]+)-(\d{4})", slug)
    if not m:
        return None
    day = int(m.group(1))
    month = m.group(2)
    year = m.group(3)
    if month not in MONTHS_TITLE:
        return None
    mm, _ = MONTHS_TITLE[month]
    return f"{series_id}_{year}_{mm}_{day:02d}"

def yodesi_eid_from_time_tag(series_id: str, sp: BeautifulSoup):
    t = sp.select_one("time[datetime]")
    if not t:
        return None
    dt = (t.get("datetime") or "").strip()
    if len(dt) < 10:
        return None
    date_part = dt[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
        return None
    y, m, d = date_part.split("-")
    return f"{series_id}_{y}_{m}_{d}"

def yodesi_eid_from_page_h1(series_id: str, sp: BeautifulSoup):
    h1 = sp.select_one("h1")
    if not h1:
        return None
    return yodesi_eid_from_title(series_id, h1.get_text(" ", strip=True))

def format_episode_name(show_name: str, eid: str):
    parts = eid.split("_")
    if len(parts) < 4:
        return show_name
    year, mm, dd = parts[-3], parts[-2], parts[-1]
    month_title = None
    for _, (mm2, title) in MONTHS_TITLE.items():
        if mm2 == mm:
            month_title = title
            break
    if not month_title:
        month_title = mm
    return f"{show_name} {int(dd)} {month_title} {year}"

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

        write_json(REPO_ROOT / "channel" / channel_id / "series.json",
                   [{"id": x["id"], "name": x["name"]} for x in shows])

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

                    # --------------------------------------------------
                    # 2. Protect links.json writes
                    # --------------------------------------------------
                    links_path = REPO_ROOT / "episode" / eid / "links.json"
                    if links and len(links) > 0:
                        write_json(links_path, links)
                    else:
                        log(f"⚠️ Skipping links for {eid} — no servers found")

                    if links and len(links) > 0:
                        if eid not in new_eps_map:
                            new_eps_map[eid] = {"id": eid, "name": format_episode_name(show["name"], eid)}

                merged = list(new_eps_map.values()) + existing_eps
                dedup = {e["id"]: {"id": e["id"], "name": format_episode_name(show["name"], e["id"])} for e in merged}

                def sort_key(e):
                    parts = e["id"].split("_")
                    y, m, d = parts[-3], parts[-2], parts[-1]
                    return f"{y}{m}{d}"

                final = sorted(dedup.values(), key=sort_key, reverse=True)

                # --------------------------------------------------
                # 1. Prevent empty overwrites (YoDesi episodes.json)
                # --------------------------------------------------
                ep_path = REPO_ROOT / "series" / show["id"] / "episodes.json"
                if final and len(final) > 0:
                    write_json(ep_path, final)
                else:
                    log(f"⚠️ Skipping write for {ep_path} — no valid data")

            except Exception as e:
                log(f"❌ Error processing {show['id']}: {e}")

    log("=== YoDesi done ===")

# ============================================================
# PlayDesi (all channels + pagination + robust episodes + genre fix)
# ============================================================

def normalize_playdesi_title(raw: str) -> str:
    if not raw:
        return ""
    s = " ".join(raw.split())
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    parts = s.split()
    if parts and parts[-1].lower() in PLAYDESI_GENRES:
        s = " ".join(parts[:-1])
    return s.strip()

def parse_playdesi_episode_number_from_url(url: str):
    m = re.search(r"-episode-(\d+)(?:-|/)", url, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"episode-(\d+)(?:-|/)", url, re.I)
    if m:
        return int(m.group(1))
    return None

def collect_series_pages_from_channel(channel_url: str):
    results = []
    seen = set()
    prev_count = 0

    for page in range(1, MAX_PAGES + 1):
        url = wp_page_url(channel_url, page)
        try:
            sp = fetch_soup(url, ref=PLAYDESI_BASE)
        except Exception:
            break

        for a in sp.select("a[href*='/watch-online/']"):
            href = a.get("href")
            if not href or not href.startswith(PLAYDESI_BASE):
                continue
            if "-episode-" in href:
                continue

            raw_title = a.get_text(" ", strip=True) or href
            title = normalize_playdesi_title(raw_title)

            if href not in seen:
                seen.add(href)
                results.append((title, href))

        if len(results) == prev_count and not page_has_next(sp):
            break
        prev_count = len(results)
        if not page_has_next(sp):
            break

    return results

def series_page_has_episodes(series_url: str) -> bool:
    for page in (1, 2):
        try:
            sp = fetch_soup(wp_page_url(series_url, page), ref=PLAYDESI_BASE)
        except Exception:
            return False

        for a in sp.select("article .entry-title a"):
            href = a.get("href", "")
            if "-episode-" in href:
                return True

        if not page_has_next(sp):
            break
    return False

def scrape_playdesi():
    log("=== PlayDesi scraping ===")
    write_json(
        REPO_ROOT / "site" / PLAYDESI_SITE_ID / "channels.json",
        [{"id": cid, "name": name} for cid, (name, _) in PLAYDESI_CHANNELS.items()]
    )

    for channel_id, (channel_name, channel_url) in PLAYDESI_CHANNELS.items():
        log(f"PlayDesi channel: {channel_name}")

        candidates = collect_series_pages_from_channel(channel_url)

        series_entries = []
        seen_series = set()

        for title, series_url in candidates:
            title = normalize_playdesi_title(title)
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
            series_entries.append({"id": series_id, "name": f"{show} – Season {season}", "url": series_url})

        write_json(
            REPO_ROOT / "channel" / channel_id / "series.json",
            [{"id": s["id"], "name": s["name"]} for s in sorted(series_entries, key=lambda x: x["id"])]
        )

        for series in series_entries:
            try:
                log(f"PlayDesi series episodes: {series['name']}")

                existing_eps, existing_ids = load_existing_episodes(series["id"])
                found_new = False
                confirmed = 0
                new_eps = []

                for page in range(1, MAX_PAGES + 1):
                    list_url = wp_page_url(series["url"], page)
                    try:
                        sp = fetch_soup(list_url, ref=channel_url)
                    except Exception:
                        break

                    ep_pages = []
                    for a in sp.select("article .entry-title a"):
                        href = a.get("href")
                        if href and href.startswith(PLAYDESI_BASE) and "-episode-" in href:
                            ep_pages.append(href)

                    ep_pages = unique_preserve(ep_pages)
                    if not ep_pages:
                        break

                    for ep_url in ep_pages:
                        ep_no = parse_playdesi_episode_number_from_url(ep_url)
                        if ep_no is None:
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

                        links = [{
                            "id": "watch",
                            "name": "Watch on PlayDesi",
                            "url": ep_url,
                            "source": "playdesi"
                        }]

                        # --------------------------------------------------
                        # 2. Protect links.json writes (PlayDesi)
                        # --------------------------------------------------
                        links_path = REPO_ROOT / "episode" / ep_id / "links.json"
                        if links and len(links) > 0:
                            write_json(links_path, links)
                        else:
                            log(f"⚠️ Skipping links for {ep_id} — no servers found")

                        if links and len(links) > 0:
                            new_eps.append({"id": ep_id, "name": f"Episode {ep_no}"})

                        if found_new and confirmed >= CONFIRM_EPISODES:
                            break

                    if found_new and confirmed >= CONFIRM_EPISODES:
                        break

                    if not page_has_next(sp):
                        break

                merged = new_eps + existing_eps
                dedup = {}
                for e in merged:
                    dedup[e["id"]] = e

                def ep_sort_key(e):
                    m = re.search(r"_ep(\d+)$", e["id"])
                    return int(m.group(1)) if m else 999999

                final_eps = sorted(dedup.values(), key=ep_sort_key)

                # --------------------------------------------------
                # 1. Prevent empty overwrites (PlayDesi episodes.json)
                # --------------------------------------------------
                ep_path = REPO_ROOT / "series" / series["id"] / "episodes.json"
                if final_eps and len(final_eps) > 0:
                    write_json(ep_path, final_eps)
                else:
                    log(f"⚠️ Skipping write for {ep_path} — no valid data")

            except Exception as e:
                log(f"❌ Error processing {series['id']}: {e}")

    log("=== PlayDesi done ===")

# ============================================================
# Git publish (unchanged)
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

    try:
        subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
    except subprocess.CalledProcessError:
        log("⚠️ Push failed, retrying after rebase…")
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)

    log("✅ Changes committed and pushed")

# ============================================================
# HUM TV (ISOLATED TEST SCRAPER - MUAMMA)
# ============================================================

def scrape_humtv():
    log("=== HUM TV scraping (Muamma only) ===")

    BASE = "https://hum.tv"
    SERIES_URL = "https://hum.tv/dramas/muamma/"
    SERIES_ID = "muamma"
    SERIES_NAME = "Muamma"

    SITE_ID = "hum_tv"
    CHANNEL_ID = "hum_tv"

    # ✅ write ONLY HUM TV files (isolated)
    write_json(REPO_ROOT / "site" / SITE_ID / "channels.json", [
        {"id": CHANNEL_ID, "name": "HUM TV"}
    ])

    write_json(REPO_ROOT / "channel" / CHANNEL_ID / "series.json", [
        {"id": SERIES_ID, "name": SERIES_NAME}
    ])

    existing_eps, existing_ids = load_existing_episodes(SERIES_ID)

    try:
        soup = fetch_soup(SERIES_URL, ref=BASE)
    except Exception as e:
        log(f"❌ Failed to load HUM TV series: {e}")
        return

    ep_links = []

    # ✅ Extract episode links
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if "muamma-episode-" in href:
            full_url = href if href.startswith("http") else BASE + href
            ep_links.append(full_url)

    ep_links = unique_preserve(ep_links)

    new_eps = []

    # ✅ Process each episode
    for url in ep_links:
        m = re.search(r"episode-(\\d+)", url)
        if not m:
            continue

        ep_num = int(m.group(1))
        ep_id = f"{SERIES_ID}_ep{ep_num:02d}"

        if ep_id in existing_ids:
            continue

        links = [{
            "id": "watch",
            "name": "Watch on HUM TV",
            "url": url,
            "source": "hum_tv"
        }]

        # ✅ safe write links
        if links:
            write_json(REPO_ROOT / "episode" / ep_id / "links.json", links)

        new_eps.append({
            "id": ep_id,
            "name": f"Episode {ep_num}"
        })

    # ✅ merge safely
    merged = new_eps + existing_eps

    dedup = {}
    for e in merged:
        dedup[e["id"]] = e

    def sort_key(e):
        m = re.search(r"_ep(\\d+)$", e["id"])
        return int(m.group(1)) if m else 0

    final = sorted(dedup.values(), key=sort_key, reverse=True)

    # ✅ safe write episodes
    if final:
        write_json(REPO_ROOT / "series" / SERIES_ID / "episodes.json", final)

    log("=== HUM TV done ===")

# ============================================================
# MAIN (flags)
# ============================================================

def main():
    run_yodesi = os.getenv("RUN_YODESI", "1") == "1"
    run_playdesi = os.getenv("RUN_PLAYDESI", "1") == "1"
    run_humtv = os.getenv("RUN_HUMTV", "0") == "1"

    # --------------------------------------------------
    # 4. Add run flag logging
    # --------------------------------------------------
    
    upsert_site(YODESI_SITE_ID, "YoDesi")
    upsert_site(PLAYDESI_SITE_ID, "PlayDesi")

    log(f"RUN_YODESI={run_yodesi}, RUN_PLAYDESI={run_playdesi}")

    if run_yodesi:
        scrape_yodesi()

    if run_playdesi:
        scrape_playdesi()
        
    if run_humtv:
    scrape_humtv()
    
    what = []
    if run_yodesi:
        what.append("YoDesi")
    if run_playdesi:
        what.append("PlayDesi")
    if run_humtv: 
        what.append("HUM TV")
        
    git_publish(f"Scheduled scrape: {', '.join(what)}")

if __name__ == "__main__":
    main()
