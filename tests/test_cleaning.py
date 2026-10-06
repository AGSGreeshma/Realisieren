"""Offline tests for the cleaning functions and the raw-dict -> Record transform.

Nothing here touches the network. The transform tests parse HTML saved in
tests/fixtures/ during Phase 2 and Phase 3.
"""

from __future__ import annotations

import pathlib

import pytest
from bs4 import BeautifulSoup

import config
from processing.cleaning import (
    clean_availability,
    clean_description,
    clean_price,
    clean_rating,
    clean_tags,
    clean_text,
    normalize_url,
    strip_quotes,
    utc_now_iso,
)
from processing.transform import book_to_record, quote_to_record
from scrapers import books_scraper as bs
from scrapers import quotes_scraper as qs
from scrapers.base_scraper import select_text

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# --------------------------------------------------------------- clean_price


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("£51.77", 51.77),       # the normal case
        ("Â£51.77", 51.77),  # mojibake prefix must be skipped
        ("£1,234.50", 1234.50),   # thousands separator
        ("51.77", 51.77),              # no currency symbol at all
        ("£-5.00", -5.00),        # minus survives so validation can reject it
        ("", None),
        (None, None),
        ("free", None),                # no digits anywhere
    ],
)
def test_clean_price(raw, expected):
    assert clean_price(raw) == expected


def test_clean_price_returns_float():
    assert isinstance(clean_price("£51.77"), float)


def test_clean_price_rounds_to_two_decimals():
    assert clean_price("1.005678") == 1.01


# -------------------------------------------------------------- clean_rating


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("star-rating Three", 3),
        ("star-rating Five", 5),
        ("star-rating One", 1),
        ("star-rating", None),       # class present but no rating word
        ("", None),
        (None, None),
        ("Three star-rating", 3),    # word first: position must not matter
        ("star-rating js-x Four", 4),  # extra class in between
    ],
)
def test_clean_rating(raw, expected):
    assert clean_rating(raw) == expected


def test_clean_rating_is_case_insensitive():
    assert clean_rating("star-rating THREE") == 3


# ---------------------------------------------------------------- clean_text


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Hello \n  World ", "Hello World"),
        ("  a \n b ", "a b"),          # the plan.md Done-when case
        ("\xa0", None),                # a lone non-breaking space is empty
        ("a\xa0b", "a b"),             # non-breaking space becomes a space
        ("   ", None),
        ("", None),
        (None, None),
        ("already clean", "already clean"),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


def test_clean_text_preserves_case():
    # Lowercasing happens only in the Phase 5 fingerprint, never here
    assert clean_text("A Light in the Attic") == "A Light in the Attic"


# -------------------------------------------------------------- strip_quotes


def test_strip_quotes_removes_curly_pair():
    raw = "“The world as we have created it.”"
    assert strip_quotes(raw) == "The world as we have created it."


def test_strip_quotes_removes_straight_pair():
    assert strip_quotes('"hello"') == "hello"


def test_strip_quotes_keeps_internal_quotes():
    raw = "“He said \"hi\" to me”"
    assert strip_quotes(raw) == 'He said "hi" to me'


def test_strip_quotes_leaves_unwrapped_text_alone():
    assert strip_quotes('he said "hi"') == 'he said "hi"'


def test_strip_quotes_handles_none():
    assert strip_quotes(None) is None


# ---------------------------------------------------------------- clean_tags


@pytest.mark.parametrize(
    "raw, expected",
    [
        (["Love", " life ", "love"], "life;love"),  # dedupe, lowercase, sort
        ([], None),
        (None, None),
        (["single"], "single"),
        (["b", "a"], "a;b"),                        # sorted, not input order
        (["", "  ", "x"], "x"),                     # blanks dropped
        (["", "  "], None),                         # all blank -> None
    ],
)
def test_clean_tags(raw, expected):
    assert clean_tags(raw) == expected


def test_clean_tags_rejects_bare_string():
    # A string is iterable: without the guard this would give "e;l;o;v"
    assert clean_tags("love") == "love"


# --------------------------------------------------------- clean_availability


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("In stock (22 available)", 22),
        ("In stock (1 available)", 1),
        ("Out of stock", 0),
        ("out of stock", 0),
        ("In stock", None),      # no count known -> empty, never invented as 0
        ("", None),
        (None, None),
    ],
)
def test_clean_availability(raw, expected):
    assert clean_availability(raw) == expected


def test_clean_availability_out_of_stock_beats_a_stray_number():
    assert clean_availability("Out of stock, 5 similar available") == 0


# -------------------------------------------------------------- normalize_url


def test_normalize_url_joins_relative_to_base():
    base = "https://books.toscrape.com/catalogue/page-2.html"
    assert normalize_url("page-3.html", base) == "https://books.toscrape.com/catalogue/page-3.html"


def test_normalize_url_joins_root_relative():
    base = "https://quotes.toscrape.com/page/2/"
    assert normalize_url("/author/Albert-Einstein", base) == "https://quotes.toscrape.com/author/Albert-Einstein"


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:void(0)",
        "mailto:someone@example.com",
        "/relative/with/no/base",
        "not a url",
        "",
        "   ",
        None,
    ],
)
def test_normalize_url_rejects_unusable(raw):
    assert normalize_url(raw) is None


def test_normalize_url_passes_absolute_through():
    url = "https://books.toscrape.com/index.html"
    assert normalize_url(url) == url


# ------------------------------------------------------- clean_description


def test_clean_description_strips_more_suffix():
    raw = "A short blurb about the book. ...more"
    assert clean_description(raw) == "A short blurb about the book."


def test_clean_description_keeps_plain_text():
    assert clean_description("No suffix here.") == "No suffix here."


def test_clean_description_handles_none():
    assert clean_description(None) is None


# ------------------------------------------------------------- utc_now_iso


def test_utc_now_iso_format():
    stamp = utc_now_iso()
    assert stamp.endswith("Z")
    assert len(stamp) == 20          # 2026-10-07T10:15:00Z
    assert stamp[4] == "-" and stamp[10] == "T"


# ------------------------------------------------- transform, from fixtures

SCRAPED_AT = "2026-10-07T10:15:00Z"


def _load(name: str) -> BeautifulSoup:
    """Parse a saved fixture - no network."""
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return BeautifulSoup(html, "lxml")


class _NoFetch:
    """Stand-in for BaseScraper: present so nothing tries to build a session."""

    def fetch(self, url):  # pragma: no cover - must never be called offline
        raise AssertionError("tests must not hit the network")


@pytest.fixture
def raw_book() -> dict:
    """First book from the saved listing page, plus its saved detail page."""
    scraper = bs.BooksScraper(scraper=_NoFetch())
    listing = _load("books_listing_page1.html")
    card = listing.select_one(bs.SEL_BOOK_CARD)
    raw = scraper._parse_card(card, config.BOOKS_BASE_URL)

    # Fill the detail fields from the saved detail page instead of fetching
    detail = _load("books_detail_a_light_in_the_attic.html")
    raw["category"] = select_text(detail, bs.SEL_CATEGORY)
    raw["description"] = select_text(detail, bs.SEL_DESCRIPTION)
    raw["availability_text"] = select_text(detail, bs.SEL_AVAILABILITY)
    return raw


@pytest.fixture
def raw_quote() -> dict:
    """First quote from the saved listing page."""
    scraper = qs.QuotesScraper(scraper=_NoFetch())
    listing = _load("quotes_listing_page1.html")
    block = listing.select_one(qs.SEL_QUOTE_BLOCK)
    return scraper._parse_quote(block, config.QUOTES_BASE_URL)


def test_book_to_record_every_field(raw_book):
    record = book_to_record(raw_book, SCRAPED_AT)

    assert record.source == "Books to Scrape"
    assert record.source_url == (
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )
    assert record.name_or_title == "A Light in the Attic"
    assert record.category == "Poetry"
    assert record.price == 51.77
    assert isinstance(record.price, float)
    assert record.currency == "GBP"
    assert record.availability == 22
    assert isinstance(record.availability, int)
    assert record.rating == 3
    assert record.scraped_at == SCRAPED_AT

    # Quote-only fields must stay empty for a book
    assert record.author is None
    assert record.author_url is None
    assert record.tags is None

    # Phase 5 fills these
    assert record.record_id is None
    assert record.is_duplicate is False

    # Description is present, cleaned, and free of the "...more" suffix
    assert record.description is not None
    assert record.description.startswith("It's hard to imagine a world without")
    assert not record.description.endswith("more")
    assert "Â" not in record.description


def test_quote_to_record_every_field(raw_quote):
    record = quote_to_record(raw_quote, SCRAPED_AT)

    assert record.source == "Quotes to Scrape"
    assert record.source_url == "https://quotes.toscrape.com/"
    assert record.name_or_title == (
        "The world as we have created it is a process of our thinking. "
        "It cannot be changed without changing our thinking."
    )
    assert record.author == "Albert Einstein"
    assert record.author_url == "https://quotes.toscrape.com/author/Albert-Einstein"
    assert record.tags == "change;deep-thoughts;thinking;world"
    assert record.scraped_at == SCRAPED_AT

    # Curly quotes must be gone from the stored text
    assert "“" not in record.name_or_title
    assert "”" not in record.name_or_title

    # Book-only fields must stay empty for a quote
    assert record.category is None
    assert record.price is None
    assert record.currency is None
    assert record.availability is None
    assert record.rating is None
    assert record.description is None

    assert record.record_id is None
    assert record.is_duplicate is False


def test_book_with_no_description_survives(raw_book):
    """A missing description must leave the field empty, not drop the record."""
    raw_book["description"] = None
    record = book_to_record(raw_book, SCRAPED_AT)
    assert record.description is None
    assert record.name_or_title == "A Light in the Attic"  # the record still exists


def test_quote_with_no_tags_survives():
    """The real zero-tag quote from page 3 must transform to tags=None."""
    scraper = qs.QuotesScraper(scraper=_NoFetch())
    listing = _load("quotes_listing_page3_zero_tags.html")
    block = next(
        b for b in listing.select(qs.SEL_QUOTE_BLOCK) if not b.select(qs.SEL_TAG)
    )
    raw = scraper._parse_quote(block, "https://quotes.toscrape.com/page/3/")
    assert raw["tags"] == []

    record = quote_to_record(raw, SCRAPED_AT)
    assert record.tags is None
    assert record.author == "J.K. Rowling"
    assert record.name_or_title is not None


def test_currency_is_none_when_price_missing(raw_book):
    """A currency label is meaningless without an amount."""
    raw_book["price_text"] = None
    record = book_to_record(raw_book, SCRAPED_AT)
    assert record.price is None
    assert record.currency is None


def test_transform_survives_an_empty_raw_dict():
    """Missing keys must not raise - .get() plus None-safe cleaning."""
    book = book_to_record({}, SCRAPED_AT)
    quote = quote_to_record({}, SCRAPED_AT)
    assert book.source == "Books to Scrape"
    assert quote.source == "Quotes to Scrape"
    assert book.name_or_title is None
    assert quote.name_or_title is None
