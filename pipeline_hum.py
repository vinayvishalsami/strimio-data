import os
import json
import time
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin

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

HUM_BASE = "https://hum.tv"
SITE_ID = "humtv"
SITE_NAME = "HUM TV"

# ============================================================
# HELPERS
# ============================================================

def log(msg: str):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")

def fetch_soup(url: str):
    time.sleep(SLEEP)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def upsert_site(site_id: str, name: str):
    sites_path = REPO_ROOT / "sites.json"
    sites = json.loads(sites_path.read_text(encoding="utf-8")) if sites_path.exists() else []
    if not any(s["id"] == site_id for s in sites):
        sites.append({"id": site_id, "name": name})
        write_json(sites_path, sites)

def extract_series_image(series_url: str) -> str | None:
    try:
        soup = fetch_soup(series_url)

        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return urljoin(HUM_BASE, og["content"])

        img = soup.find("img")
        if img and img.get("src"):
            return urljoin(HUM_BASE, img["src"])

    except Exception as e:
        log(f"Poster extraction failed for {series_url}: {e}")

    return None

# ============================================================
# HUM SCRAPER
# ============================================================

EP_URL_RE = re.compile(r"(?:-|/)episode-(\d+)|last-episode-(\d+)", re.I)

def scrape_hum():
    log("=== HUM TV scraping ===")

    upsert_site(SITE_ID, SITE_NAME)

    channel_id = "hum_latest"
    write_json(
        REPO_ROOT / "site" / SITE_ID / "channels.json",
        [{"id": channel_id, "name": "Latest Dramas"}]
    )

    series_list = []
    page = 1
    seen_series = set()

    while True:
        url = f"{HUM_BASE}/latest-dramas/" if page == 1 else f"{HUM_BASE}/latest-dramas/page/{page}/"
        log(f"Discovering series page {page}")

        try:
            soup = fetch_soup(url)
        except Exception:
            break

        anchors = soup.select("a[href^='https://hum.tv/dramas/']")
        found_any = False

        for a in anchors:
            href = a.get("href")
            name = a.get_text(strip=True)

            if not href or not name:
                continue

            slug = urlparse(href).path.strip("/").split("/")[-1]
            if slug in seen_series:
                continue

            seen_series.add(slug)
            found_any = True
            series_list.append({"id": slug, "name": name, "url": href})

        if not found_any:
            break

        page += 1

    valid_series = []

    for series in series_list:
        series_id = series["id"]
        series_name = series["name"]
        base_series_url = series["url"].rstrip("/") + "/"

        log(f"Scraping series: {series_name}")

        poster_image = extract_series_image(base_series_url)

        episodes = []
        page = 1
        seen_eps = set()

        while True:
            paged_url = base_series_url if page == 1 else f"{base_series_url}page/{page}/"

            try:
                soup = fetch_soup(paged_url)
            except Exception:
                break

            found_any = False
            for a in soup.find_all("a", href=True):
                href = a["href"]
                title = a.get_text(strip=True)

                if not href.startswith(HUM_BASE):
                    continue
                if not EP_URL_RE.search(href):
                    continue
                if not title or "episode" not in title.lower():
                    continue
                if href in seen_eps:
                    continue

                seen_eps.add(href)
                found_any = True
                ep_id = urlparse(href).path.strip("/").replace("/", "_")
                episodes.append({"id": ep_id, "name": title, "url": href})

            if not found_any:
                break

            page += 1

        episodes.reverse()
        if not episodes:
            continue

        series_obj = {
            "id": series_id,
            "name": series_name,
            "url": base_series_url + "#episodes"
        }

        if poster_image:
            series_obj["image"] = poster_image

        valid_series.append(series_obj)

        write_json(
            REPO_ROOT / "series" / series_id / "episodes.json",
            [{"id": ep["id"], "name": ep["name"]} for ep in episodes]
        )

        for ep in episodes:
            write_json(
                REPO_ROOT / "episode" / ep["id"] / "links.json",
                [{
                    "id": "watch",
                    "name": "Watch on HUM TV",
                    "url": ep["url"],
                    "source": SITE_ID
                }]
            )

    write_json(
        REPO_ROOT / "channel" / channel_id / "series.json",
        valid_series
    )

    log("=== HUM TV scraping done ===")

# ============================================================
# MAIN
# ============================================================

def main():
    scrape_hum()

if __name__ == "__main__":
    main()
