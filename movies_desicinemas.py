import json
import time
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://desicinemas.to"
BOLLYWOOD_URL = "https://desicinemas.to/category/bollywood-movies/"

OUTPUT_ROOT = Path(".")
SLEEP = 1.0
MAX_MOVIES = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (StrimioIndexer/1.0)"
}

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url: str) -> BeautifulSoup:
    time.sleep(SLEEP)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def slug_from_url(url: str) -> str:
    return urlparse(url).path.strip("/").split("/")[-1]


def scrape_movies():
    write_json(
        OUTPUT_ROOT / "site" / "movies" / "channels.json",
        [{"id": "bollywood", "name": "Bollywood"}]
    )

    soup = fetch(BOLLYWOOD_URL)

    articles = soup.select("article")

movies = []

for art in articles:
    a = art.select_one("a[href]")
    title_el = art.select_one(".Title")

    if not a or not title_el:
        continue

    text_block = art.get_text(" ", strip=True)
    year_match = re.search(r"(19|20)\d{2}", text_block)

    if not year_match:
        continue

    movies.append({
        "url": a["href"],
        "title": title_el.get_text(strip=True),
        "year": int(year_match.group(0))
    })

    if len(movies) >= MAX_MOVIES:
        break

    output_movies = []

    for m in movies:
        movie_page = fetch(m["url"])
        og = movie_page.find("meta", property="og:image")

        movie_id = f"{slug_from_url(m['url'])}-{m['year']}"

        output_movies.append({
            "id": movie_id,
            "name": m["title"],
            "year": m["year"],
            "language": "bollywood",
            "image": og["content"] if og else None
        })

        links = []
        for i, box in enumerate(movie_page.select(".OptionBx"), start=1):
            btn = box.select_one("a.Button")
            if not btn:
                continue

            links.append({
                "id": f"link-{i:02d}",
                "name": f"Link {i}",
                "url": btn["href"],
                "source": "desicinemas"
            })

        if links:
            write_json(
                OUTPUT_ROOT / "movie" / movie_id / "links.json",
                links
            )

    write_json(
        OUTPUT_ROOT / "movies" / "bollywood" / "movies.json",
        output_movies
    )


if __name__ == "__main__":
    scrape_movies()
