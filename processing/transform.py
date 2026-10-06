"""Turn one raw scraped dict into one Record.

This is the only place that knows how a source's raw field names map onto the
shared schema. It does no cleaning of its own - every value goes through a
function from cleaning.py - and it never invents a value: a field the source
cannot provide stays None.
"""

from __future__ import annotations

from typing import Any

from processing.cleaning import (
    clean_availability,
    clean_description,
    clean_price,
    clean_rating,
    clean_tags,
    clean_text,
    normalize_url,
    strip_quotes,
)
from processing.models import Record

# Written out exactly as plan.md Section 4 requires
BOOKS_SOURCE = "Books to Scrape"
QUOTES_SOURCE = "Quotes to Scrape"

CURRENCY_GBP = "GBP"


def book_to_record(raw: dict[str, Any], scraped_at: str) -> Record:
    """Map one raw book dict onto a Record.

    Args:
        raw: a dict from BooksScraper.scrape().
        scraped_at: one UTC ISO timestamp for the whole run.
    """
    price = clean_price(raw.get("price_text"))

    return Record(
        source=BOOKS_SOURCE,
        # The detail page is where the book's own data lives, so it is the
        # record's source_url (plan.md Section 4)
        source_url=normalize_url(raw.get("detail_url")),
        name_or_title=clean_text(raw.get("title")),
        category=clean_text(raw.get("category")),
        price=price,
        # Only claim a currency when there is actually a price to label
        currency=CURRENCY_GBP if price is not None else None,
        availability=clean_availability(raw.get("availability_text")),
        rating=clean_rating(raw.get("rating_classes")),
        description=clean_description(raw.get("description")),
        scraped_at=scraped_at,
        # author, author_url and tags do not exist for books -> left as None
    )


def quote_to_record(raw: dict[str, Any], scraped_at: str) -> Record:
    """Map one raw quote dict onto a Record.

    Args:
        raw: a dict from QuotesScraper.scrape().
        scraped_at: one UTC ISO timestamp for the whole run.
    """
    return Record(
        source=QUOTES_SOURCE,
        # The listing page is where the quote was seen; the author page URL
        # goes in author_url instead (plan.md Section 3)
        source_url=normalize_url(raw.get("page_url")),
        # clean the whitespace first, then take the wrapping curly quotes off
        name_or_title=strip_quotes(clean_text(raw.get("text"))),
        author=clean_text(raw.get("author")),
        author_url=normalize_url(raw.get("author_url")),
        tags=clean_tags(raw.get("tags")),
        scraped_at=scraped_at,
        # category, price, currency, availability, rating and description do
        # not exist for quotes -> left as None
    )
