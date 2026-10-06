"""Offline parser tests against the saved HTML in tests/fixtures/.

These prove the selectors still match real markup without making a single
request. conftest.py blocks sockets, so if a test here ever reached the
network it would fail rather than quietly succeed.
"""

from __future__ import annotations

import copy
from urllib.parse import urljoin

import pytest
from bs4 import BeautifulSoup

import config
from processing.transform import book_to_record, quote_to_record
from scrapers import books_scraper as bs
from scrapers import quotes_scraper as qs
from tests.conftest import load_fixture

SCRAPED_AT = "2026-10-07T10:15:00Z"

BOOKS_PAGE_1 = "https://books.toscrape.com/"
BOOKS_PAGE_2 = "https://books.toscrape.com/catalogue/page-2.html"
BOOKS_PAGE_50 = "https://books.toscrape.com/catalogue/page-50.html"
QUOTES_PAGE_1 = "https://quotes.toscrape.com/"
QUOTES_PAGE_3 = "https://quotes.toscrape.com/page/3/"
QUOTES_PAGE_10 = "https://quotes.toscrape.com/page/10/"


class NoFetch:
    """Stands in for BaseScraper so no session is ever built."""

    def fetch(self, url):  # pragma: no cover - must never be called
        raise AssertionError("parser tests must not fetch anything")


def soup_of(name: str) -> BeautifulSoup:
    """Parse a saved fixture into soup."""
    return BeautifulSoup(load_fixture(name), "lxml")


@pytest.fixture
def books() -> bs.BooksScraper:
    return bs.BooksScraper(scraper=NoFetch())


@pytest.fixture
def quotes() -> qs.QuotesScraper:
    return qs.QuotesScraper(scraper=NoFetch())


# -------------------------------------------------- books listing page 1


def test_books_listing_returns_twenty_records(books):
    records, cards_found = books.parse_listing(soup_of("books_listing_page1.html"), BOOKS_PAGE_1)
    assert len(records) == 20
    assert cards_found == 20


def test_books_first_title_is_the_full_title(books):
    """The visible link text is truncated; the title attribute is not."""
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), BOOKS_PAGE_1)
    assert records[0]["title"] == "A Light in the Attic"
    assert "..." not in records[0]["title"]


def test_books_detail_url_is_absolute(books):
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), BOOKS_PAGE_1)
    assert records[0]["detail_url"] == (
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )


def test_books_raw_price_and_rating_are_present(books):
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), BOOKS_PAGE_1)
    first = records[0]
    # Raw, not cleaned: the pound sign is still attached
    assert first["price_text"] == "£51.77"
    assert first["rating_classes"] == "star-rating Three"
    assert first["listing_page_url"] == BOOKS_PAGE_1


def test_books_every_record_has_a_title_and_url(books):
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), BOOKS_PAGE_1)
    for record in records:
        assert record["title"]
        assert record["detail_url"].startswith("https://")


def test_books_detail_fields_start_empty_before_the_detail_fetch(books):
    """parse_listing must not invent detail-page values."""
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), BOOKS_PAGE_1)
    assert records[0]["category"] is None
    assert records[0]["description"] is None
    assert records[0]["availability_text"] is None


# ------------------------------------------------------- books pagination


def test_books_page_1_next_href_and_absolute_url(books):
    soup = soup_of("books_listing_page1.html")
    href = soup.select_one(bs.SEL_NEXT_PAGE)["href"]
    assert href == "catalogue/page-2.html"
    assert books._next_page_url(soup, BOOKS_PAGE_1) == BOOKS_PAGE_2


def test_books_page_2_next_href_and_absolute_url(books):
    """The href loses the catalogue/ prefix after page 1; joining against the
    CURRENT url is what resolves both shapes correctly."""
    soup = soup_of("books_listing_page2.html")
    href = soup.select_one(bs.SEL_NEXT_PAGE)["href"]
    assert href == "page-3.html"
    assert books._next_page_url(soup, BOOKS_PAGE_2) == (
        "https://books.toscrape.com/catalogue/page-3.html"
    )


def test_joining_page_2_href_against_the_base_url_would_be_wrong():
    """Documents the bug that joining against a fixed base would cause."""
    wrong = urljoin(BOOKS_PAGE_1, "page-3.html")
    assert wrong == "https://books.toscrape.com/page-3.html"  # a 404
    right = urljoin(BOOKS_PAGE_2, "page-3.html")
    assert right == "https://books.toscrape.com/catalogue/page-3.html"


def test_books_last_page_has_no_next_link(books):
    soup = soup_of("books_listing_page50_last.html")
    assert soup.select_one(bs.SEL_NEXT_PAGE) is None
    assert books._next_page_url(soup, BOOKS_PAGE_50) is None


def test_books_page_2_still_has_twenty_records(books):
    records, cards = books.parse_listing(soup_of("books_listing_page2.html"), BOOKS_PAGE_2)
    assert len(records) == 20 and cards == 20


def test_books_page_2_detail_href_shape_differs(books):
    """On page 2 the detail href has no catalogue/ prefix either."""
    records, _ = books.parse_listing(soup_of("books_listing_page2.html"), BOOKS_PAGE_2)
    assert records[0]["detail_url"] == (
        "https://books.toscrape.com/catalogue/in-her-wake_980/index.html"
    )


# ------------------------------------------------------ book detail page


def test_book_detail_extracts_all_three_fields(books):
    detail = books.parse_detail(soup_of("books_detail_a_light_in_the_attic.html"))
    assert detail["category"] == "Poetry"
    assert detail["availability_text"] == "In stock (22 available)"
    assert detail["description"] is not None
    assert detail["description"].startswith("It's hard to imagine a world without")


def test_book_detail_description_still_has_the_more_suffix(books):
    """parse_detail is raw; stripping '...more' is cleaning's job."""
    detail = books.parse_detail(soup_of("books_detail_a_light_in_the_attic.html"))
    assert detail["description"].endswith("...more")


def test_book_detail_breadcrumb_has_four_crumbs():
    soup = soup_of("books_detail_a_light_in_the_attic.html")
    crumbs = [li.get_text(strip=True) for li in soup.select("ul.breadcrumb li")]
    assert crumbs == ["Home", "Books", "Poetry", "A Light in the Attic"]


# ------------------------------------------------------------ quotes pages


def test_quotes_page_1_returns_ten_records(quotes):
    records, blocks = quotes.parse_listing(soup_of("quotes_listing_page1.html"), QUOTES_PAGE_1)
    assert len(records) == 10
    assert blocks == 10


def test_quotes_first_record_fields(quotes):
    records, _ = quotes.parse_listing(soup_of("quotes_listing_page1.html"), QUOTES_PAGE_1)
    first = records[0]
    assert first["author"] == "Albert Einstein"
    assert first["author_url"] == "https://quotes.toscrape.com/author/Albert-Einstein"
    assert first["tags"] == ["change", "deep-thoughts", "thinking", "world"]
    assert first["page_url"] == QUOTES_PAGE_1
    # Raw: the curly quotes are still attached at this layer
    assert first["text"].startswith("“")
    assert first["text"].endswith("”")


def test_quotes_page_3_has_a_zero_tag_quote(quotes):
    records, _ = quotes.parse_listing(soup_of("quotes_listing_page3_zero_tags.html"), QUOTES_PAGE_3)
    no_tags = [record for record in records if record["tags"] == []]
    assert len(no_tags) == 1
    assert no_tags[0]["author"] == "J.K. Rowling"
    # An empty LIST, not None - select() returns [] when nothing matches
    assert no_tags[0]["tags"] == []
    assert isinstance(no_tags[0]["tags"], list)


def test_quotes_zero_tag_count_is_tracked(quotes):
    quotes.parse_listing(soup_of("quotes_listing_page3_zero_tags.html"), QUOTES_PAGE_3)
    assert quotes.stats["quotes_without_tags"] == 1


def test_quotes_page_1_next_link(quotes):
    soup = soup_of("quotes_listing_page1.html")
    assert soup.select_one(qs.SEL_NEXT_PAGE)["href"] == "/page/2/"
    assert quotes._next_page_url(soup, QUOTES_PAGE_1) == "https://quotes.toscrape.com/page/2/"


def test_quotes_last_page_has_no_next_link(quotes):
    soup = soup_of("quotes_listing_page10_last.html")
    assert soup.select_one(qs.SEL_NEXT_PAGE) is None
    assert quotes._next_page_url(soup, QUOTES_PAGE_10) is None


def test_quotes_page_10_still_has_ten_records(quotes):
    records, blocks = quotes.parse_listing(soup_of("quotes_listing_page10_last.html"), QUOTES_PAGE_10)
    assert len(records) == 10 and blocks == 10


# ------------------------------------------- missing elements must not crash


def test_books_missing_price_gives_none(books):
    """Delete the price tag from the HTML and confirm the field is None."""
    soup = soup_of("books_listing_page1.html")
    card = soup.select_one(bs.SEL_BOOK_CARD)
    card.select_one(bs.SEL_PRICE).decompose()  # remove the element entirely

    records, cards_found = books.parse_listing(soup, BOOKS_PAGE_1)
    assert cards_found == 20          # the card is still there
    assert len(records) == 20         # and still produced a record
    assert records[0]["price_text"] is None
    assert records[0]["title"] == "A Light in the Attic"  # other fields survive


def test_books_missing_rating_gives_none(books):
    soup = soup_of("books_listing_page1.html")
    soup.select_one(bs.SEL_BOOK_CARD).select_one(bs.SEL_RATING).decompose()
    records, _ = books.parse_listing(soup, BOOKS_PAGE_1)
    assert records[0]["rating_classes"] is None


def test_books_missing_title_link_gives_none(books):
    soup = soup_of("books_listing_page1.html")
    soup.select_one(bs.SEL_BOOK_CARD).select_one(bs.SEL_TITLE_LINK).decompose()
    records, _ = books.parse_listing(soup, BOOKS_PAGE_1)
    assert records[0]["title"] is None
    assert records[0]["detail_url"] is None  # no href to join


def test_book_detail_missing_description_gives_none(books):
    soup = soup_of("books_detail_a_light_in_the_attic.html")
    soup.select_one(bs.SEL_DESCRIPTION).decompose()
    detail = books.parse_detail(soup)
    assert detail["description"] is None
    assert detail["category"] == "Poetry"  # the others still work


def test_book_detail_missing_everything_gives_all_none(books):
    """An empty page must produce empty fields, not an exception."""
    detail = books.parse_detail(BeautifulSoup("<html></html>", "lxml"))
    assert detail == {"category": None, "description": None, "availability_text": None}


def test_quotes_missing_author_gives_none(quotes):
    soup = soup_of("quotes_listing_page1.html")
    soup.select_one(qs.SEL_QUOTE_BLOCK).select_one(qs.SEL_AUTHOR).decompose()
    records, _ = quotes.parse_listing(soup, QUOTES_PAGE_1)
    assert records[0]["author"] is None
    assert records[0]["text"] is not None  # the quote itself survived


def test_quotes_missing_author_link_gives_none(quotes):
    soup = soup_of("quotes_listing_page1.html")
    soup.select_one(qs.SEL_QUOTE_BLOCK).select_one(qs.SEL_AUTHOR_LINK).decompose()
    records, _ = quotes.parse_listing(soup, QUOTES_PAGE_1)
    assert records[0]["author_url"] is None


def test_quotes_missing_text_gives_none(quotes):
    soup = soup_of("quotes_listing_page1.html")
    soup.select_one(qs.SEL_QUOTE_BLOCK).select_one(qs.SEL_TEXT).decompose()
    records, _ = quotes.parse_listing(soup, QUOTES_PAGE_1)
    assert records[0]["text"] is None


def test_empty_page_yields_no_records(books, quotes):
    empty = BeautifulSoup("<html><body></body></html>", "lxml")
    assert books.parse_listing(empty, BOOKS_PAGE_1) == ([], 0)
    assert quotes.parse_listing(empty, QUOTES_PAGE_1) == ([], 0)


# ---------------------------------- transform, moved here from test_cleaning


@pytest.fixture
def raw_book(books) -> dict:
    """First book from the saved listing page plus its saved detail page."""
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), config.BOOKS_BASE_URL)
    record = records[0]
    record.update(books.parse_detail(soup_of("books_detail_a_light_in_the_attic.html")))
    return record


@pytest.fixture
def raw_quote(quotes) -> dict:
    records, _ = quotes.parse_listing(soup_of("quotes_listing_page1.html"), config.QUOTES_BASE_URL)
    return records[0]


def test_book_to_record_every_field(raw_book):
    record = book_to_record(raw_book, SCRAPED_AT)

    assert record.source == "Books to Scrape"
    assert record.source_url == (
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )
    assert record.name_or_title == "A Light in the Attic"
    assert record.category == "Poetry"
    assert record.price == 51.77 and isinstance(record.price, float)
    assert record.currency == "GBP"
    assert record.availability == 22 and isinstance(record.availability, int)
    assert record.rating == 3
    assert record.scraped_at == SCRAPED_AT

    # Quote-only fields stay empty for a book
    assert record.author is None
    assert record.author_url is None
    assert record.tags is None

    # Phase 5 fills these
    assert record.record_id is None
    assert record.is_duplicate is False

    # Description cleaned: no "...more", no mojibake
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

    # Curly quotes stripped by the cleaning layer
    assert "“" not in record.name_or_title
    assert "”" not in record.name_or_title

    # Book-only fields stay empty for a quote
    assert record.category is None
    assert record.price is None
    assert record.currency is None
    assert record.availability is None
    assert record.rating is None
    assert record.description is None

    assert record.record_id is None
    assert record.is_duplicate is False


def test_book_with_no_description_survives(raw_book):
    raw = copy.deepcopy(raw_book)
    raw["description"] = None
    record = book_to_record(raw, SCRAPED_AT)
    assert record.description is None
    assert record.name_or_title == "A Light in the Attic"


def test_quote_with_no_tags_transforms_to_none(quotes):
    """The real zero-tag quote from page 3 must become tags=None."""
    records, _ = quotes.parse_listing(
        soup_of("quotes_listing_page3_zero_tags.html"), QUOTES_PAGE_3
    )
    raw = next(record for record in records if record["tags"] == [])
    record = quote_to_record(raw, SCRAPED_AT)
    assert record.tags is None
    assert record.author == "J.K. Rowling"
    assert record.name_or_title is not None


def test_currency_is_none_when_price_missing(raw_book):
    raw = copy.deepcopy(raw_book)
    raw["price_text"] = None
    record = book_to_record(raw, SCRAPED_AT)
    assert record.price is None
    assert record.currency is None


def test_transform_survives_an_empty_raw_dict():
    book = book_to_record({}, SCRAPED_AT)
    quote = quote_to_record({}, SCRAPED_AT)
    assert book.source == "Books to Scrape"
    assert quote.source == "Quotes to Scrape"
    assert book.name_or_title is None
    assert quote.name_or_title is None


def test_all_twenty_books_transform_cleanly(books):
    """Every record on a real page must produce a usable Record."""
    records, _ = books.parse_listing(soup_of("books_listing_page1.html"), config.BOOKS_BASE_URL)
    for raw in records:
        record = book_to_record(raw, SCRAPED_AT)
        assert record.name_or_title
        assert isinstance(record.price, float)
        assert record.rating in (1, 2, 3, 4, 5)
        assert record.currency == "GBP"


def test_all_ten_quotes_transform_cleanly(quotes):
    records, _ = quotes.parse_listing(soup_of("quotes_listing_page1.html"), config.QUOTES_BASE_URL)
    for raw in records:
        record = quote_to_record(raw, SCRAPED_AT)
        assert record.name_or_title
        assert record.author
        assert record.author_url.startswith("https://")
        assert "“" not in record.name_or_title
