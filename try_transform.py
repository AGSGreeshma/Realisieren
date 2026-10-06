"""Throwaway Phase 4 check: scrape a little, transform it, inspect the Records.

Run with:  python try_transform.py

Proves the cleaning layer works on live data rather than only on fixtures:
prices are floats, ratings are ints 1-5, quote text has lost its curly quotes,
tags look like "a;b", and no field carries the "Â" mojibake.
"""

import logging
import sys

from processing.cleaning import utc_now_iso
from processing.models import COLUMNS
from processing.transform import book_to_record, quote_to_record
from scrapers.books_scraper import BooksScraper
from scrapers.quotes_scraper import QuotesScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)


def show(record) -> None:
    """Print one Record field by field, in CSV column order."""
    data = record.as_dict()
    print()
    for column in COLUMNS:
        value = data[column]
        shown = value
        if isinstance(value, str) and len(value) > 64:
            shown = value[:64] + "..."
        print(f"    {column:14} {shown!r:<70} {type(value).__name__}")


def main() -> None:
    # One timestamp for the whole run, shared by every record
    scraped_at = utc_now_iso()
    print(f"scraped_at for this run: {scraped_at}\n")

    books_scraper = BooksScraper()
    raw_books = books_scraper.scrape(max_pages=1)
    books = [book_to_record(raw, scraped_at) for raw in raw_books]

    quotes_scraper = QuotesScraper()
    raw_quotes = quotes_scraper.scrape(max_pages=1)
    quotes = [quote_to_record(raw, scraped_at) for raw in raw_quotes]

    records = books + quotes

    print("\n" + "=" * 92)
    print(f"2 BOOKS as Records  (of {len(books)})")
    print("=" * 92)
    for record in books[:2]:
        show(record)

    print("\n" + "=" * 92)
    print(f"2 QUOTES as Records  (of {len(quotes)})")
    print("=" * 92)
    for record in quotes[:2]:
        show(record)

    print("\n" + "=" * 92)
    print("CHECKS")
    print("=" * 92)

    bad_price = [r for r in books if not isinstance(r.price, float)]
    print(f"  prices are floats          : {len(books) - len(bad_price)}/{len(books)}"
          f"   bad: {len(bad_price)}")

    bad_rating = [r for r in books if not (isinstance(r.rating, int) and 1 <= r.rating <= 5)]
    print(f"  ratings are ints 1-5       : {len(books) - len(bad_rating)}/{len(books)}"
          f"   bad: {len(bad_rating)}")

    curly = [r for r in quotes if r.name_or_title and ("“" in r.name_or_title or "”" in r.name_or_title)]
    print(f"  quote text has no curly quotes: {len(quotes) - len(curly)}/{len(quotes)}"
          f"   bad: {len(curly)}")

    tagged = [r for r in quotes if r.tags]
    looks_right = [r for r in tagged if ";" in r.tags or r.tags.isalnum() or "-" in r.tags]
    print(f"  tags look like 'a;b'       : {len(looks_right)}/{len(tagged)} of the tagged quotes")
    print(f"    examples                 : {[r.tags for r in tagged[:3]]}")
    print(f"    quotes with no tags      : {len(quotes) - len(tagged)} (tags=None)")

    # The mojibake that appears if response.encoding is left at ISO-8859-1
    mojibake = []
    for record in records:
        for column, value in record.as_dict().items():
            if isinstance(value, str) and "Â" in value:
                mojibake.append((column, value[:40]))
    print(f"  fields containing 'Â'      : {len(mojibake)}   {mojibake[:3]}")

    currency_mismatch = [
        r for r in records
        if (r.price is None) != (r.currency is None)
    ]
    print(f"  price/currency always paired: {len(records) - len(currency_mismatch)}/{len(records)}"
          f"   bad: {len(currency_mismatch)}")

    print(f"\n  total records transformed  : {len(records)}")
    print(f"  one shared scraped_at      : {len({r.scraped_at for r in records}) == 1}")

    books_scraper.scraper.close()
    quotes_scraper.scraper.close()
    print("\ntry_transform finished\n")


if __name__ == "__main__":
    main()
