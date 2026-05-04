import json
import time
import requests
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

HEADERS = {"User-Agent": "Strimio-ARY-Test"}
DM_API = "https://api.dailymotion.com"

# EXACT playlists taken from your HTML (__NEXT_DATA__)
TEST_SERIES = {
    "on_air": {
        "id": "67f3dfe4ac7c1db7bc439950",
        "name": "Meri Zindagi Hai Tu",
        "playlist": "xaj6x2",
        "channel": "ary_on_air"
    },
    "popular": {
        "id": "6683e59ff3416429c7d90a0e",
        "name": "Kabhi Main Kabhi Tum",
        "playlist": "x8hbo0",
        "channel": "ary_popular"
    },
    "archive": {
        "id": "67519c4fbab01e9798a6bba9",
        "name": "Pyarey Afzal",
        "playlist": "x3lolv",
        "channel": "ary_archive"
    }
}

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def fetch_dm_episodes(playlist_id, limit=5):
    url = f"{DM_API}/playlist/{playlist_id}/videos"
    params = {
        "fields": "id,title",
        "limit": limit
    }
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()["list"]

def main():
    print("=== ARY DIGITAL TEST PIPELINE ===")

    # Ensure site exists (non-destructive)
    sites_path = REPO_ROOT / "sites.json"
    sites = json.loads(sites_path.read_text())
    if not any(s["id"] == "arydigital" for s in sites):
        sites.append({"id": "arydigital", "name": "ARY Digital"})
        write_json(sites_path, sites)

    # Channels
    write_json(
        REPO_ROOT / "site/arydigital/channels.json",
        [
            {"id": "ary_on_air", "name": "On Air"},
            {"id": "ary_popular", "name": "Popular"},
            {"id": "ary_archive", "name": "Archive"}
        ]
    )

    for section, meta in TEST_SERIES.items():
        print(f"Fetching episodes for {meta['name']}")

        # Write ONE series only (test)
        write_json(
            REPO_ROOT / f"channel/{meta['channel']}/series.json",
            [{"id": meta["id"], "name": meta["name"]}]
        )

        episodes = fetch_dm_episodes(meta["playlist"], limit=5)

        episode_index = []
        for ep in episodes:
            ep_id = f"{meta['id']}_{ep['id']}"

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
            REPO_ROOT / f"series/{meta['id']}/episodes.json",
            episode_index
        )

        time.sleep(1)

    print("✅ ARY test scrape finished successfully")

if __name__ == "__main__":
    main()
