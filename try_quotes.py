"""Throwaway Phase 3 check for the Quotes scraper. Not part of the final pipeline.

Run with:  python try_quotes.py

Shows three things:
  1. a full run returns 100 quotes over 10 pages
  2. quotes with zero tags are kept, with an empty list rather than None
  3. a broken URL is logged and returns cleanly instead of crashing
"""

import logging
import sys
import time

from scrapers.quotes_scraper import QuotesScraper

# A check script IS the entry point, so configuring logging here is correct.
# In the real pipeline main.py does this (Phase 6); library modules never do.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)


def show_record(index: int, record: dict) -> None:
    """Print one raw record with every field on its own line."""
    print(f"\n  --- record {index} ---")
    for key, value in record.items():
        shown = value
        if isinstance(value, str) and len(value) > 70:
            shown = value[:70] + "..."
        print(f"  {key:12} {shown!r}")


def check_full_run() -> None:
    """Scrape every page and report what came back."""
    print("\n" + "=" * 72)
    print("1. FULL RUN (all pages, no page limit)")
    print("=" * 72)

    scraper = QuotesScraper()
    started = time.perf_counter()
    records = scraper.scrape()
    elapsed = time.perf_counter() - started

    print(f"\n  records returned : {len(records)}  (expected 100)")
    print(f"  pages scraped    : {scraper.stats['pages_scraped']}  (expected 10)")

    missing = {
        field: sum(1 for r in records if not r[field])
        for field in ("text", "author", "author_url", "page_url")
    }
    print(f"  missing fields   : {missing}  (all should be 0)")

    relative = [r["author_url"] for r in records if not (r["author_url"] or "").startswith("http")]
    print(f"  non-absolute author_url : {len(relative)}  (expected 0)")

    # Curly quotes must survive untouched - stripping them is Phase 4's job
    curly = sum(1 for r in records if r["text"] and r["text"].startswith("“"))
    print(f"  texts still curly-quoted: {curly}/{len(records)}")

    for position, record in enumerate(records[:3], start=1):
        show_record(position, record)

    print(f"\n  stats            : {scraper.stats}")
    print(f"  requests made    : {scraper.scraper.requests_made}")
    print(f"  requests failed  : {scraper.scraper.requests_failed}")
    print(f"  elapsed          : {elapsed:.1f}s")

    print("\n  --- quotes with zero tags ---")
    no_tags = [r for r in records if not r["tags"]]
    if not no_tags:
        print("  none found")
    for record in no_tags:
        print(f"  {record['author']:16} tags={record['tags']!r}  {record['page_url']}")
        print(f"    {record['text'][:72]}")

    scraper.scraper.close()


def check_broken_url() -> None:
    """Point the scraper at URLs that cannot work and prove it does not crash."""
    print("\n" + "=" * 72)
    print("2. BROKEN URL RUN (errors must be logged, not raised)")
    print("=" * 72)

    print("\n  2a. real 404 (not retried - 404 is not in RETRY_STATUS_CODES)")
    scraper = QuotesScraper(base_url="https://quotes.toscrape.com/no-such-path-here/")
    records = scraper.scrape()
    print(f"      returned {len(records)} record(s) instead of raising")
    print(f"      stats: {scraper.stats}  <- pages_failed=1")
    scraper.scraper.close()

    print("\n  2b. page that EXISTS but holds no quotes: /page/99999/ returns 200, not 404")
    print("      so the fetch succeeds and the selector alarm is what tells us")
    scraper = QuotesScraper(base_url="https://quotes.toscrape.com/page/99999/")
    records = scraper.scrape()
    print(f"      returned {len(records)} record(s) instead of raising")
    print(f"      stats: {scraper.stats}  <- pages_scraped=1, pages_failed=0")
    scraper.scraper.close()

    print("\n  2c. unresolvable host (retried 3x with 0s/2s/4s backoff, then gives up)")
    started = time.perf_counter()
    scraper = QuotesScraper(base_url="https://this-host-does-not-exist.invalid/")
    records = scraper.scrape()
    print(f"      returned {len(records)} record(s) instead of raising")
    print(f"      stats: {scraper.stats}")
    print(f"      took {time.perf_counter() - started:.1f}s (retry backoff is visible here)")
    scraper.scraper.close()

    print("\n  nothing crashed - every failure above was logged and handled")


def main() -> None:
    check_full_run()
    check_broken_url()
    print("\ntry_quotes finished\n")


if __name__ == "__main__":
    main()
