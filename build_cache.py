"""Development helper: scrape both sources once and cache the RAW records.

Run with:  python build_cache.py

A full Books run is ~1,050 requests and takes 20-30 minutes. During Phase 5-7
development we need the same data over and over, so this saves it to
data/raw_cache.json once and later scripts load it instead of re-scraping.

NOT part of the pipeline. main.py always scrapes live; data/ is gitignored.
"""

import json
import logging
import sys
import time
from pathlib import Path

from processing.cleaning import utc_now_iso
from scrapers.base_scraper import BaseScraper
from scrapers.books_scraper import BooksScraper
from scrapers.quotes_scraper import QuotesScraper

CACHE_PATH = Path(__file__).resolve().parent / "data" / "raw_cache.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("build_cache")


def main() -> None:
    started = time.perf_counter()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # One shared session for both sources, so connections are reused throughout
    session = BaseScraper()

    books_scraper = BooksScraper(scraper=session)
    logger.info("Scraping Books in full (this is the slow part)...")
    books = books_scraper.scrape()

    quotes_scraper = QuotesScraper(scraper=session)
    logger.info("Scraping Quotes in full...")
    quotes = quotes_scraper.scrape()

    session.close()

    payload = {
        "built_at": utc_now_iso(),
        "source": "live scrape by build_cache.py",
        "stats": {
            "books": books_scraper.stats,
            "quotes": quotes_scraper.stats,
            "requests_made": session.requests_made,
            "requests_failed": session.requests_failed,
        },
        "books": books,
        "quotes": quotes,
    }

    with CACHE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    elapsed = time.perf_counter() - started
    logger.info(
        "Cached %s books and %s quotes to %s in %.1f min",
        len(books),
        len(quotes),
        CACHE_PATH,
        elapsed / 60,
    )


if __name__ == "__main__":
    main()
