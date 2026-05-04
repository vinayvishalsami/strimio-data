import json
import time
import requests
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BASE = "https://node.aryzap.com/api"
HEADERS = {"User-Agent": "Strimio-ARY-Test"}

TEST_SERIES = {
    "on_air": {
        "id": "67f3dfe4ac7c1db7bc439950",
        "name": "Meri Zindagi Hai Tu"
    },
    "popular": {
        "id": "6683e59ff3416429c7d90a0e",
        "name": "Kabhi Main Kabhi Tum"
    },
    "archive": {
        "id": "67519c4fbab01e9798a6bba9",
        "name": "Pyarey Afzal"
    }
}

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    print("=== ARY DIGITAL TEST PIPELINE ===")

    # register site (non-destructive)
    sites_path = REPO_ROOT / "sites.json"
    sites = json.loads(sites_path.read_text())
    if not any(s["id"] == "arydigital" for s in sites):
        sites.append({"id": "arydigital", "name": "ARY Digital"})
        write_json(sites_path, sites)

    channels = [
        {"id": "ary_on_air", "name": "On Air"},
        {"id": "ary_popular", "name": "Popular"},
        {"id": "ary_archive", "name": "Archive"},
    ]
    write_json(REPO_ROOT / "site/arydigital/channels.json", channels)

    section_to_channel = {
        "on_air": "ary_on_air",
        "popular": "ary_popular",
        "archive": "ary_archive"
    }

    for section, meta in TEST_SERIES.items():
        channel_id = section_to_channel[section]

        # write series.json (ONE series only)
        write_json(
            REPO_ROOT / f"channel/{channel_id}/series.json",
            [{"id": meta["id"], "name": meta["name"]}]
        )

        print(f"Fetching episodes for {meta['name']}")

        episodes = fetch(f"{BASE}/video/bySeries/{meta['id']}/PK")["data"]
        episodes = sorted(episodes, key=lambda x: x["publishedAt"], reverse=True)[:5]

        ep_entries = []

        for ep in episodes:
            ep_id = f"{meta['id']}_{ep['id']}"
            ep_entries.append({
                "id": ep_id,
                "name": ep["title"]
            })

            embed = f"https://geo.dailymotion.com/player/x1bog.html?video={ep['id']}"

            write_json(
                REPO_ROOT / f"episode/{ep_id}/links.json",
                [{
                    "id": "watch",
                    "name": "Watch",
                    "url": embed,
                    "source": "arydigital"
                }]
            )

        write_json(
            REPO_ROOT / f"series/{meta['id']}/episodes.json",
            ep_entries
        )

        time.sleep(1)

    print("✅ ARY test scrape finished")

if __name__ == "__main__":
    main()
