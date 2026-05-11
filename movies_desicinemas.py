import json
import time
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://desicinemas.to"
BOLLYWOOD_URL = "https://desicinemas.to/category/bollywood-movies/"

OUTPUT_ROOT = Path("strimio-data")
SLEEP = 1.0
MAX_MOVIES = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)"
}

session = requests.Session()
session.headers.update(HEADERS)

# ============================================================
# HELPERS
# ============================================================

def fetch(url: str) -> BeautifulSoup:
    time.sleep(SLEEP)
    res = session.get(url, timeout=30)
    res.raise_for_status()
    return BeautifulSoup(res.text, "lxml")

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def slug_from_url(url: str) -> str:
    return urlparse(url).path.strip("/").split("/")[-1]

# ============================================================
# SCRAPER
# ============================================================

def scrape_movies():
    print("=== Scraping Bollywood movies (page 1, 5 movies) ===")

    # --------------------------------------------------------
    # 1. Write movie categories (channels)
    # --------------------------------------------------------

    write_json(
        OUTPUT_ROOT / "site" / "movies" / "channels.json",
        [
            {
                "id": "bollywood",
                "name": "Bollywood"
            }
        ]
    )

    # --------------------------------------------------------
    # 2. Fetch Bollywood listing page (page 1 only)
    # --------------------------------------------------------

    soup = fetch(BOLLYWOOD_URL)

    movie_cards = soup.select(".TPost.B a")  # movie cards
    movies = []

    for a in movie_cards:
        href = a.get("href")
        title_el = a.select_one(".Title")

        if not href or not title_el:
            continue

        title = title_el.get_text(strip=True)

        # Extract year if present in sibling elements
        year_match = re.search(r"(19|20)\d{2}", a.parent.get_text())
        year = int(year_match.group(0)) if year_match else None

        if year is None:
            continue

        movies.append({
            "title": title,
            "url": href,
            "year": year
        })

        if len(movies) >= MAX_MOVIES:
            break

    # --------------------------------------------------------
    # 3. Visit each movie page
    # --------------------------------------------------------

    output_movies = []

    for m in movies:
        movie_url = m["url"]
        movie_soup = fetch(movie_url)

        # Poster (OG image is best)
        og = movie_soup.find("meta", property="og:image")
        poster = og["content"] if og else None

        movie_id = f"{slug_from_url(movie_url)}-{m['year']}"

        output_movies.append({
            "id": movie_id,
            "name": m["title"],
            "year": m["year"],
            "language": "bollywood",
            "image": poster
        })

        # ----------------------------------------------------
        # 4. Extract links
        # ----------------------------------------------------

        links = []
        link_boxes = movie_soup.select(".OptionBx")

        for idx, box in enumerate(link_boxes, start=1):
            btn = box.select_one("a.Button")
            label = box.select_one(".Optntl")

            if not btn:
                continue

            links.append({
                "id": f"link-{idx:02d}",
                "name": label.get_text(strip=True) if label else f"Link {idx}",
                "url": btn["href"],
                "source": "desicinemas"
            })

        if links:
            write_json(
                OUTPUT_ROOT / "movie" / movie_id / "links.json",
                links
            )

    # --------------------------------------------------------
    # 5. Write movies.json
    # --------------------------------------------------------

    write_json(
        OUTPUT_ROOT / "movies" / "bollywood" / "movies.json",
        output_movies
    )

    print("=== Done: Bollywood movies scraped ===")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    scrape_movies()
