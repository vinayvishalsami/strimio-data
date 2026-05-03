import json
import re
import time
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG (VIU ONLY)
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent
SLEEP = 1

PLAYDESI_BASE = "https://playdesi.tv"
CHANNEL_ID = "viu_originals"
CHANNEL_NAME = "Viu"
CHANNEL_URL = f"{PLAYDESI_BASE}/viu-originals/"

CONFIRM_EPISODES = 5
MAX_PAGES = 30  # reduce while debugging

HEADERS = {"User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)"}
session = requests.Session()
session.headers.update(HEADERS)

# Optional: known genre words that sometimes get glued to titles
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
    r = session.get(url, headers=headers, timeout=45)
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

def normalize_playdesi_title(raw: str) -> str:
    if not raw:
        return ""
    # preserve spaces, split CamelCase joins (BekaabooThriller -> Bekaaboo Thriller)
    s = " ".join(raw.split())
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    # remove trailing genre token
    parts = s.split()
    if parts and parts[-1].lower() in PLAYDESI_GENRES:
        s = " ".join(parts[:-1])
    return s.strip()

def parse_episode_number(ep_url: str, h1_text: str | None = None) -> int | None:
    # Handles:
    #  ...-episode-10-watch-online/
    #  ...-episode-10-...
    #  ...episode-10...
    m = re.search(r"-episode-(\d+)(?:-|/)", ep_url, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"episode-(\d+)(?:-|/)", ep_url, re.I)
    if m:
        return int(m.group(1))
    if h1_text:
        m = re.search(r"episode\s+(\d+)", h1_text, re.I)
        if m:
            return int(m.group(1))
    return None

def load_existing_episodes(series_id: str):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return data, {e["id"] for e in data}

# ============================================================
# PLAYDESI VIU SCRAPER
# ============================================================

def collect_series_from_viu_channel():
    """
    Pull ALL series pages from the Viu channel (pagination-aware).
    """
    results = []
    seen = set()
    prev_count = 0

    for page in range(1, MAX_PAGES + 1):
        url = wp_page_url(CHANNEL_URL, page)
        try:
            sp = fetch_soup(url, ref=PLAYDESI_BASE)
        except Exception:
            break

        anchors = sp.select("a[href*='/watch-online/']")
        for a in anchors:
            href = a.get("href")
            if not href or not href.startswith(PLAYDESI_BASE):
                continue
            if "-episode-" in href:
                continue  # exclude episode posts

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

def series_has_episodes(series_url: str) -> bool:
    """
    Web-series filter: check first two pages for any episode post.
    """
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

def extract_episode_links(series_url: str):
    """
    Extract episode post URLs from a series page (pagination-aware).
    Uses robust selector and a fallback.
    """
    links = []
    for page in range(1, MAX_PAGES + 1):
        list_url = wp_page_url(series_url, page)
        try:
            sp = fetch_soup(list_url, ref=series_url)
        except Exception:
            break

        # Primary selector (works for h2/h3 entry-title)
        page_links = []
        for a in sp.select("article .entry-title a"):
            href = a.get("href")
            if href and href.startswith(PLAYDESI_BASE) and "-episode-" in href:
                page_links.append(href)

        # Fallback selector (if theme differs)
        if not page_links:
            for a in sp.select("a[href*='episode']"):
                href = a.get("href")
                if href and href.startswith(PLAYDESI_BASE) and "episode" in href.lower():
                    page_links.append(href)

        page_links = unique_preserve(page_links)
        log(f"    episode list page {page}: {len(page_links)} links")

        if not page_links:
            break

        links.extend(page_links)

        if not page_has_next(sp):
            break

    return unique_preserve(links)

def scrape_viu_only():
    log("=== PlayDesi VIU ONLY scrape ===")

    # Only show the VIU channel in app
    write_json(REPO_ROOT / "site" / "playdesi" / "channels.json", [
        {"id": CHANNEL_ID, "name": CHANNEL_NAME}
    ])

    series_candidates = collect_series_from_viu_channel()
    log(f"Found {len(series_candidates)} candidate series pages in VIU")

    series_entries = []
    seen_ids = set()

    for title, series_url in series_candidates:
        title = normalize_playdesi_title(title)

        m = re.search(r"(.+?)\s+season\s+(\d+)", title, re.I)
        if m:
            show = m.group(1).strip()
            season = int(m.group(2))
        else:
            show = title.strip()
            season = 1

        series_id = f"{slugify(show)}__season_{season}"
        if series_id in seen_ids:
            continue

        if not series_has_episodes(series_url):
            continue

        seen_ids.add(series_id)
        series_entries.append({
            "id": series_id,
            "name": f"{show} – Season {season}",
            "url": series_url
        })

    write_json(REPO_ROOT / "channel" / CHANNEL_ID / "series.json", [
        {"id": s["id"], "name": s["name"]} for s in sorted(series_entries, key=lambda x: x["id"])
    ])

    log(f"VIU series accepted (web-series only): {len(series_entries)}")

    # Episodes per series
    for series in series_entries:
        log(f"PlayDesi series episodes: {series['name']}")

        existing_eps, existing_ids = load_existing_episodes(series["id"])
        ep_links = extract_episode_links(series["url"])

        # Write debug dump so you can inspect what it found
        write_json(REPO_ROOT / "debug" / "playdesi_viu" / f"{series['id']}_episode_links.json", ep_links)

        new_eps = []
        found_new = False
        confirmed = 0

        for ep_url in ep_links:
            ep_no = parse_episode_number(ep_url)
            if ep_no is None:
                # fallback: open page and parse H1
                ep_page = fetch_soup(ep_url, ref=series["url"])
                h1 = ep_page.select_one("h1")
                ep_no = parse_episode_number(ep_url, h1.get_text(" ", strip=True) if h1 else None)

            if ep_no is None:
                continue

            ep_id = f"{series['id']}_ep{ep_no:02d}"

            if ep_id in existing_ids:
                if found_new:
                    confirmed += 1
                if found_new and confirmed >= CONFIRM_EPISODES:
                    break
                continue

            found_new = True
            confirmed = 0

            # ✅ PlayDesi-safe: store only the episode URL
            write_json(REPO_ROOT / "episode" / ep_id / "links.json", [{
                "id": "watch",
                "name": "Watch on PlayDesi",
                "url": ep_url,
                "source": "playdesi"
            }])

            new_eps.append({"id": ep_id, "name": f"Episode {ep_no}"})

        merged = new_eps + existing_eps
        dedup = {}
        for e in merged:
            dedup[e["id"]] = e

        def ep_sort_key(e):
            m = re.search(r"_ep(\d+)$", e["id"])
            return int(m.group(1)) if m else 999999

        write_json(REPO_ROOT / "series" / series["id"] / "episodes.json", sorted(dedup.values(), key=ep_sort_key))

    log("=== PlayDesi VIU ONLY done ===")

# ============================================================
# GIT PUBLISH
# ============================================================

def git_publish(message: str):
    subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=REPO_ROOT, check=True)

    subprocess.run(["git", "add", "."], cwd=REPO_ROOT, check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True
    )
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
    # Keep sites.json intact so app still shows both sites
    write_json(REPO_ROOT / "sites.json", [
        {"id": "yodesi", "name": "YoDesi"},
        {"id": "playdesi", "name": "PlayDesi"},
    ])

    scrape_viu_only()
    git_publish("Debug: PlayDesi VIU only episode extraction")

if __name__ == "__main__":
    main()
