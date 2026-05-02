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

# Incremental stop threshold:
# After we start finding "new" episodes on paginated episode lists,
# stop when we hit this many already-known episodes in a row.
CONFIRM_EPISODES = 5

# Safety max pages for any paginated listing
MAX_PAGES = 50

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

def load_existing_episodes(series_id: str):
    p = REPO_ROOT / "series" / series_id / "episodes.json"
    if not p.exists():
        return [], set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return data, {e["id"] for e in data}

def wp_page_url(base: str, page: int) -> str:
    base = base.rstrip("/") + "/"
    return base if page == 1 else f"{base}page/{page}/"

def page_has_next(sp: BeautifulSoup) -> bool:
    # WordPress pagination commonly uses: a.next.page-numbers
    return sp.select_one("a.next.page-numbers") is not None

def unique_preserve(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

# ============================================================
# YoDesi: Robust episode ID extraction (fixes date gaps)
# ============================================================

def infer_yodesi_episode_id(series_id: str, slug: str):
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|h)?-([a-z]+)-(\d{4})", slug)
    if m and m.group(2) in MONTHS:
        return f"{series_id}_{m.group(3)}_{MONTHS[m.group(2)]}_{int(m.group(1)):02d}"
    return None

def yodesi_eid_from_url(series_id: str, ep_url: str):
    try:
        slug = ep_url.rstrip("/").split("/")[-2]
    except Exception:
        return None
    return infer_yodesi_episode_id(series_id, slug)

def yodesi_eid_from_time_tag(series_id: str, sp: BeautifulSoup):
    t = sp.select_one("time[datetime]")
    if not t:
        return None
    dt = t.get("datetime", "")
    if len(dt) < 10:
        return None
    date_part = dt[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
        return None
    y, m, d = date_part.split("-")
    return f"{series_id}_{y}_{m}_{d}"

def yodesi_eid_from_text(series_id: str, sp: BeautifulSoup):
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
# YoDesi SCRAPER (source=yodesi)
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
                    if page > MAX_PAGES:
                        break
                    continue
                break

            new_eps = []
            for ep_url in new_urls:
                sp = fetch_soup(ep_url, ref=show["url"])

                eid = (
                    yodesi_eid_from_url(show["id"], ep_url)
                    or yodesi_eid_from_time_tag(show["id"], sp)
                    or yodesi_eid_from_text(show["id"], sp)
                )
                if not eid:
                    continue

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

                parts = eid.split("_")
                year, month, day = parts[-3], parts[-2], parts[-1]
                new_eps.append({"id": eid, "name": f"{show['name']} {int(day)}-{month}-{year}"})

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
# PlayDesi SCRAPER (supports pagination for channel series list AND series episode lists)
# ============================================================

def collect_series_pages_from_channel(channel_url: str) -> list[tuple[str, str]]:
    """
    Collect series pages from a channel.
    Some channel pages may paginate (/page/2/...), so we support it.
    We scan all pages to avoid missing alphabetically inserted series.
    """
    results = []
    seen = set()

    prev_count = 0
    for page in range(1, MAX_PAGES + 1):
        url = wp_page_url(channel_url, page)
        try:
            sp = fetch_soup(url, ref=PLAYDESI_BASE)
        except Exception:
            break

        # Collect /watch-online/ links that are NOT episode pages
        for a in sp.select("a[href*='/watch-online/']"):
            href = a.get("href")
            if not href or not href.startswith(PLAYDESI_BASE):
                continue
            if "-episode-" in href:
                continue  # exclude episode posts
            title = a.get_text(strip=True) or href
            if href not in seen:
                seen.add(href)
                results.append((title, href))

        # stop conditions
        if len(results) == prev_count:
            # no new series discovered on this page
            if not page_has_next(sp):
                break
        prev_count = len(results)

        if not page_has_next(sp):
            break

    return results

def series_page_has_episodes(series_url: str) -> bool:
    """
    Web-series filter:
    series page must contain at least one '-episode-' post (on any paginated page).
    We'll check first 2 pages for speed.
    """
    for page in range(1, 3):
        url = wp_page_url(series_url, page)
        try:
            sp = fetch_soup(url, ref=PLAYDESI_BASE)
        except Exception:
            return False

        for a in sp.select("article h2.entry-title a"):
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

        # Episode scraping per series (paginated)
        for series in series_entries:
            log(f"PlayDesi series episodes: {series['name']}")

            existing_eps, existing_ids = load_existing_episodes(series["id"])

            found_new = False
            confirmed = 0
            new_eps = []

            # Walk episode listing pages newest -> older
            for page in range(1, MAX_PAGES + 1):
                list_url = wp_page_url(series["url"], page)
                try:
                    sp = fetch_soup(list_url, ref=channel_url)
                except Exception:
                    break

                ep_pages = []
                for a in sp.select("article h2.entry-title a"):
                    href = a.get("href")
                    if href and href.startswith(PLAYDESI_BASE) and "-episode-" in href:
                        ep_pages.append(href)

                ep_pages = unique_preserve(ep_pages)
                if not ep_pages:
                    break

                for ep_url in ep_pages:
                    # episode number from URL first (fast)
                    mm = re.search(r"-episode-(\d+)-", ep_url, re.I)
                    if not mm:
                        # fallback: title-based
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

                    # ✅ Store ONLY PlayDesi episode page URL (no GroundBanks)
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

                if not page_has_next(sp):
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

            write_json(
                REPO_ROOT / "series" / series["id"] / "episodes.json",
                sorted(final, key=ep_sort_key)
            )

    log("=== PlayDesi done ===")

# ============================================================
# Git publish (robust push with rebase + retry)
# ============================================================

def git_publish(message: str):
    try:
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

        try:
            subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
        except subprocess.CalledProcessError:
            log("⚠️ First push failed, retrying after rebase...")
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=REPO_ROOT, check=True)
            subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)

        log("✅ Changes committed and pushed")

    except subprocess.CalledProcessError:
        log("❌ git push failed. Common causes:")
        log("1) Actions token lacks write permissions (Repo Settings → Actions → Workflow permissions → Read & write)")
        log("2) Branch protection blocks pushes to main")
        log("3) Another workflow pushed simultaneously (should be resolved by rebase unless branch is protected)")
        raise

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

    git_publish("Update YoDesi + PlayDesi (pagination-aware channels+episodes; PlayDesi episode URLs only)")

if __name__ == "__main__":
    main()
