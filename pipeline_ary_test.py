import json
import time
import requests
from pathlib import Path

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent

HEADERS = {
    "User-Agent": "Strimio-ARY"
}

ARY_API = "https://node.aryzap.com/api/series/byCatID/pg"
DM_API = "https://api.dailymotion.com"
COUNTRY = "PK"

ARY_IMAGE_BASE = "https://node.aryzap.com/public/"

SECTIONS = {
    "ary_on_air": "DIGITAL: On Air",
    "ary_popular": "DIGITAL: Popular",
    "ary_archive": "DIGITAL: Archive",
}

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def fetch_json(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_dm_episodes(playlist_id):
    all_episodes = []
    page = 1

    while True:
        url = f"{DM_API}/playlist/{playlist_id}/videos"
        params = {
            "fields": "id,title",
            "limit": 100,
            "page": page
        }

        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        items = data.get("list", [])
        if not items:
            break

        all_episodes.extend(items)

        if not data.get("has_more"):
            break

        page += 1
        time.sleep(0.2)

    return all_episodes

# --------------------------------------------------
# MAIN PIPELINE
# --------------------------------------------------

def main():
    print("=== ARY DIGITAL PIPELINE ===")

    # --------------------------------------------------
    # Ensure site exists
    # --------------------------------------------------
    sites_path = REPO_ROOT / "sites.json"
    sites = json.loads(sites_path.read_text())

    if not any(s["id"] == "arydigital" for s in sites):
        sites.append({"id": "arydigital", "name": "ARY Digital"})
        write_json(sites_path, sites)

    # --------------------------------------------------
    # Channels
    # --------------------------------------------------
    write_json(
        REPO_ROOT / "site/arydigital/channels.json",
        [
            {"id": cid, "name": cname.replace("DIGITAL: ", "")}
            for cid, cname in SECTIONS.items()
        ]
    )

    # --------------------------------------------------
    # SERIES PAGINATION
    # --------------------------------------------------
    for channel_id, category in SECTIONS.items():
        print(f"Fetching section: {category}")

        page = 1
        all_series = []

        while True:
            url = f"{ARY_API}/{category}/{COUNTRY}?page={page}"
            resp = fetch_json(url)

            if "data" in resp and "series" in resp["data"]:
                series_page = resp["data"]["series"]
            elif "series" in resp:
                series_page = resp["series"]
            else:
                break

            if not series_page:
                break

            all_series.extend(series_page)
            page += 1
            time.sleep(0.4)

        series_index = []

        for series in all_series:
            series_id = series.get("_id")
            series_name = series.get("title")
            playlist = series.get("seriesDM")

            if not series_id or not playlist:
                continue

            series_entry = {
                "id": series_id,
                "name": series_name
            }

            # --------------------------------------------------
            # ✅ ADD POSTER ONLY FOR ON-AIR
            # --------------------------------------------------
            if channel_id == "ary_on_air":
                poster_path = series.get("imagePoster")
                if poster_path:
                    series_entry["image"] = ARY_IMAGE_BASE + poster_path.lstrip("/")

            series_index.append(series_entry)

            # --------------------------------------------------
            # Episodes
            # --------------------------------------------------
            episodes = fetch_dm_episodes(playlist)
            episode_index = []

            for ep in episodes:
                ep_id = f"{series_id}_{ep['id']}"

                episode_index.append({
                    "id": ep_id,
                    "name": ep["title"]
                })

                embed_url = f"https://geo.dailymotion.com/player/x1bog.html?video={ep['id']}"

                write_json(
                    REPO_ROOT / f"episode/{ep_id}/links.json",
                    [{
                        "id": "watch",
                        "name": "Watch",
                        "url": embed_url,
                        "source": "arydigital"
                    }]
                )

            write_json(
                REPO_ROOT / f"series/{series_id}/episodes.json",
                episode_index
            )

            time.sleep(0.2)

        write_json(
            REPO_ROOT / f"channel/{channel_id}/series.json",
            series_index
        )

    print("✅ ARY pipeline finished successfully")

# --------------------------------------------------
# ENTRY
# --------------------------------------------------

if __name__ == "__main__":
    main()
