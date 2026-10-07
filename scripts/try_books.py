"""Manual check of the Books scraper against the live site.

Run with:  python scripts/try_books.py

Shows three things:
  1. a 2-page run returns 40 raw books with full titles
  2. a broken URL is logged and returns cleanly instead of crashing
  3. how long a full run would take
"""

# Running this as "python scripts/<name>.py" puts scripts/ on the import path,
# not the project root, so "import config" would fail. Add the project root.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


import logging
import sys
import time

import config
from scrapers.base_scraper import BaseScraper
from scrapers.books_scraper import BooksScraper

# A check script IS the entry point, so configuring logging here is correct.
# In the real pipeline main.py does this (Phase 6); library modules never do.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)

BOOKS_PER_PAGE = 20
TOTAL_PAGES = 50


def show_record(index: int, record: dict) -> None:
    """Print one raw record with every field on its own line."""
    print(f"\n  --- record {index} ---")
    for key, value in record.items():
        shown = value
        if isinstance(value, str) and len(value) > 70:
            shown = value[:70] + "..."
        print(f"  {key:18} {shown!r}")


def check_two_pages() -> float:
    """Scrape 2 listing pages with detail pages and report what came back."""
    print("\n" + "=" * 72)
    print("1. TWO-PAGE RUN (with detail pages)")
    print("=" * 72)

    scraper = BooksScraper()
    started = time.perf_counter()
    records = scraper.scrape(max_pages=2)
    elapsed = time.perf_counter() - started

    print(f"\n  records returned : {len(records)}  (expected 40)")
    truncated = [r["title"] for r in records if r["title"] and "..." in r["title"]]
    print(f"  truncated titles : {len(truncated)}  (expected 0)")
    missing_title = [r for r in records if not r["title"]]
    print(f"  missing titles   : {len(missing_title)}  (expected 0)")
    no_description   = [r for r in records if r["description"] is None]
    print(f"  no description   : {len(no_description)}")

    for position, record in enumerate(records[:3], start=1):
        show_record(position, record)

    print(f"\n  stats            : {scraper.stats}")
    print(f"  requests made    : {scraper.scraper.requests_made}")
    print(f"  requests failed  : {scraper.scraper.requests_failed}")
    print(f"  elapsed          : {elapsed:.1f}s")

    scraper.scraper.close()
    return elapsed


def check_broken_url() -> None:
    """Point the scraper at URLs that cannot work and prove it does not crash."""
    print("\n" + "=" * 72)
    print("2. BROKEN URL RUN (errors must be logged, not raised)")
    print("=" * 72)

    print("\n  2a. 404 on the first listing page (not retried - 404 is not in RETRY_STATUS_CODES)")
    scraper = BooksScraper(base_url="https://books.toscrape.com/no-such-page-exists.html")
    records = scraper.scrape()
    print(f"      returned {len(records)} record(s) instead of raising")
    print(f"      stats: {scraper.stats}")
    scraper.scraper.close()

    print("\n  2b. unresolvable host (retried 3x with 0s/2s/4s backoff, then gives up)")
    started = time.perf_counter()
    scraper = BooksScraper(base_url="https://this-host-does-not-exist.invalid/")
    records = scraper.scrape()
    print(f"      returned {len(records)} record(s) instead of raising")
    print(f"      stats: {scraper.stats}")
    print(f"      took {time.perf_counter() - started:.1f}s (retry backoff is visible here)")
    scraper.scraper.close()

    print("\n  2c. a single broken DETAIL page keeps the book, with empty fields")
    base = BaseScraper()
    books = BooksScraper(scraper=base)
    record = {
        "source": "Books to Scrape",
        "title": "Pretend Book",
        "detail_url": "https://books.toscrape.com/catalogue/no-such-book/index.html",
        "category": None,
        "description": None,
        "availability_text": None,
    }
    books._add_detail_fields(record)
    print(f"      record survived : {record['title']!r}")
    print(f"      category        : {record['category']!r}")
    print(f"      description     : {record['description']!r}")
    print(f"      availability    : {record['availability_text']!r}")
    print(f"      stats           : {books.stats}")
    base.close()

    print("\n  nothing crashed - every failure above was logged and handled")


def estimate_full_run(two_page_seconds: float) -> None:
    """Report how long a full run takes, measured rather than guessed."""
    print("\n" + "=" * 72)
    print("3. FULL RUN ESTIMATE")
    print("=" * 72)

    listing_requests = TOTAL_PAGES
    detail_requests = TOTAL_PAGES * BOOKS_PER_PAGE
    total_requests = listing_requests + detail_requests

    # The 2-page run made 2 listing + 40 detail = 42 requests
    measured_per_request = two_page_seconds / 42
    projected = total_requests * measured_per_request

    print(f"\n  listing pages          : {listing_requests}")
    print(f"  detail pages           : {detail_requests}")
    print(f"  total requests         : {total_requests}")
    print(f"  delay per request      : {config.REQUEST_DELAY}s (config.REQUEST_DELAY)")
    print(f"  floor from delay alone  : {total_requests * config.REQUEST_DELAY / 60:.1f} min")
    print(f"  measured per request   : {measured_per_request:.2f}s (from the 2-page run)")
    print(f"  projected full run     : {projected / 60:.1f} min")
    print(f"  with --skip-details    : ~{listing_requests * measured_per_request / 60:.1f} min")

    print("\n  To confirm ~1000 books over 50 pages, run this once:")
    print("    python -c \"import logging,sys; logging.basicConfig(level=logging.INFO,stream=sys.stdout);"
          " from scrapers.books_scraper import BooksScraper;"
          " s=BooksScraper(); r=s.scrape(); print(len(r), s.stats)\"")
    print("\n  Expect: 1000 records, pages_scraped=50, pages_failed=0.")
    print("  (From Phase 6 onwards this is just: python main.py --source books)")


def main() -> None:
    elapsed = check_two_pages()
    check_broken_url()
    estimate_full_run(elapsed)
    print("\ntry_books finished\n")


if __name__ == "__main__":
    main()
