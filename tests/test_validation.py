"""Offline tests for validate_record, split_valid and count_reasons."""

from __future__ import annotations

from dataclasses import replace

import pytest

from processing.models import Record
from processing.validation import count_reasons, split_valid, validate_record

SCRAPED_AT = "2026-10-07T10:15:00Z"


def valid_book(**overrides) -> Record:
    """A book Record with nothing wrong with it."""
    record = Record(
        source="Books to Scrape",
        source_url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        name_or_title="A Light in the Attic",
        category="Poetry",
        price=51.77,
        currency="GBP",
        availability=22,
        rating=3,
        description="A blurb.",
        scraped_at=SCRAPED_AT,
    )
    return replace(record, **overrides) if overrides else record


def valid_quote(**overrides) -> Record:
    """A quote Record with nothing wrong with it."""
    record = Record(
        source="Quotes to Scrape",
        source_url="https://quotes.toscrape.com/",
        name_or_title="The world as we have created it is a process of our thinking.",
        author="Albert Einstein",
        author_url="https://quotes.toscrape.com/author/Albert-Einstein",
        tags="change;thinking",
        scraped_at=SCRAPED_AT,
    )
    return replace(record, **overrides) if overrides else record


# ------------------------------------------------------------- happy path


def test_valid_book_has_no_problems():
    assert validate_record(valid_book()) == []


def test_valid_quote_has_no_problems():
    assert validate_record(valid_quote()) == []


def test_book_without_optional_fields_is_still_valid():
    """Missing category and description are normal, not errors."""
    record = valid_book(category=None, description=None)
    assert validate_record(record) == []


def test_quote_without_tags_is_still_valid():
    assert validate_record(valid_quote(tags=None)) == []


def test_book_without_author_url_is_valid():
    """Books have no author page; None must not be an error."""
    assert validate_record(valid_book(author_url=None)) == []


# --------------------------------------------------------- unknown_source


@pytest.mark.parametrize("source", ["books to scrape", "Books", "", None, "Other Site"])
def test_unknown_source(source):
    assert "unknown_source" in validate_record(valid_book(source=source))


# ----------------------------------------------------------- missing_name


@pytest.mark.parametrize("name", [None, "", "   ", "\t"])
def test_missing_name(name):
    assert "missing_name" in validate_record(valid_book(name_or_title=name))


# ------------------------------------------------------------ invalid_url


@pytest.mark.parametrize(
    "url",
    [None, "", "javascript:void(0)", "mailto:x@example.com", "/relative/only", "not a url"],
)
def test_invalid_url(url):
    assert "invalid_url" in validate_record(valid_book(source_url=url))


# ----------------------------------------------------- invalid_author_url


@pytest.mark.parametrize("url", ["javascript:void(0)", "/author/x", "nonsense", ""])
def test_invalid_author_url(url):
    assert "invalid_author_url" in validate_record(valid_quote(author_url=url))


def test_absent_author_url_is_not_invalid():
    assert "invalid_author_url" not in validate_record(valid_quote(author_url=None))


# ---------------------------------------------------------- invalid_price


def test_invalid_price_negative():
    assert "invalid_price" in validate_record(valid_book(price=-1))


def test_invalid_price_nan():
    # nan < 0 is False, so a naive range check would let this through
    assert "invalid_price" in validate_record(valid_book(price=float("nan")))


def test_invalid_price_infinity():
    assert "invalid_price" in validate_record(valid_book(price=float("inf")))


def test_invalid_price_not_a_number():
    assert "invalid_price" in validate_record(valid_book(price="51.77"))


def test_invalid_price_bool():
    assert "invalid_price" in validate_record(valid_book(price=True))


def test_price_zero_is_valid():
    """Free is a legitimate price; only negative is wrong."""
    assert "invalid_price" not in validate_record(valid_book(price=0.0))


# ------------------------------------------------- price_currency_mismatch


def test_price_without_currency():
    assert "price_currency_mismatch" in validate_record(valid_book(currency=None))


def test_currency_without_price():
    assert "price_currency_mismatch" in validate_record(valid_book(price=None))


def test_neither_price_nor_currency_is_fine():
    record = valid_book(price=None, currency=None)
    assert "price_currency_mismatch" not in validate_record(record)


# --------------------------------------------------------- invalid_rating


@pytest.mark.parametrize("rating", [0, 6, -1, 100])
def test_invalid_rating_out_of_range(rating):
    assert "invalid_rating" in validate_record(valid_book(rating=rating))


def test_invalid_rating_true_is_rejected():
    """bool is a subclass of int, and 1 <= True <= 5 is True, so this needs
    an explicit bool check to be caught."""
    assert "invalid_rating" in validate_record(valid_book(rating=True))


def test_invalid_rating_false_is_rejected():
    assert "invalid_rating" in validate_record(valid_book(rating=False))


@pytest.mark.parametrize("rating", [3.5, "3", 3.0])
def test_invalid_rating_wrong_type(rating):
    assert "invalid_rating" in validate_record(valid_book(rating=rating))


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_valid_ratings_accepted(rating):
    assert "invalid_rating" not in validate_record(valid_book(rating=rating))


def test_absent_rating_is_not_invalid():
    assert "invalid_rating" not in validate_record(valid_book(rating=None))


# --------------------------------------------------- invalid_availability


@pytest.mark.parametrize("availability", [-1, -100, True, 2.5, "22"])
def test_invalid_availability(availability):
    assert "invalid_availability" in validate_record(valid_book(availability=availability))


def test_availability_zero_is_valid():
    """Out of stock is a real, meaningful value."""
    assert "invalid_availability" not in validate_record(valid_book(availability=0))


def test_absent_availability_is_not_invalid():
    assert "invalid_availability" not in validate_record(valid_book(availability=None))


# --------------------------------------------------------- missing_author


@pytest.mark.parametrize("author", [None, "", "   "])
def test_missing_author_on_quote(author):
    assert "missing_author" in validate_record(valid_quote(author=author))


def test_missing_author_does_not_apply_to_books():
    """Books legitimately have no author field in this schema."""
    assert "missing_author" not in validate_record(valid_book(author=None))


# ----------------------------------------------------- missing_scraped_at


@pytest.mark.parametrize("stamp", [None, "", "   "])
def test_missing_scraped_at(stamp):
    assert "missing_scraped_at" in validate_record(valid_book(scraped_at=stamp))


# ------------------------------------------------------- multiple problems


def test_two_problems_returns_both_codes():
    record = valid_book(name_or_title=None, price=-5)
    problems = validate_record(record)
    assert "missing_name" in problems
    assert "invalid_price" in problems
    assert len(problems) >= 2


def test_many_problems_returns_all_of_them():
    record = Record(
        source="Nowhere",
        source_url="javascript:void(0)",
        name_or_title="",
        price=float("nan"),
        currency=None,
        rating=True,
        availability=-1,
        scraped_at="",
    )
    problems = validate_record(record)
    for code in (
        "unknown_source",
        "missing_name",
        "invalid_url",
        "invalid_price",
        "price_currency_mismatch",
        "invalid_rating",
        "invalid_availability",
        "missing_scraped_at",
    ):
        assert code in problems, f"{code} missing from {problems}"


# ------------------------------------------------ split_valid / count_reasons


def test_split_valid_separates_the_two_groups():
    good = valid_book()
    bad = valid_book(name_or_title=None)
    valid, rejected = split_valid([good, bad])

    assert valid == [good]
    assert len(rejected) == 1
    assert rejected[0].record is bad
    assert rejected[0].reasons == ["missing_name"]


def test_split_valid_on_an_empty_list():
    valid, rejected = split_valid([])
    assert valid == []
    assert rejected == []


def test_split_valid_keeps_input_order():
    records = [valid_book(name_or_title=f"Book {n}") for n in range(5)]
    valid, _ = split_valid(records)
    assert [r.name_or_title for r in valid] == ["Book 0", "Book 1", "Book 2", "Book 3", "Book 4"]


def test_count_reasons_totals_every_code():
    records = [
        valid_book(name_or_title=None),      # missing_name
        valid_book(name_or_title=None),      # missing_name
        valid_book(price=-1),                # invalid_price
    ]
    _, rejected = split_valid(records)
    counts = count_reasons(rejected)
    assert counts["missing_name"] == 2
    assert counts["invalid_price"] == 1


def test_count_reasons_counts_both_codes_of_one_record():
    """A record with two problems contributes to two totals, so the counts
    can sum to more than the number of rejected records."""
    _, rejected = split_valid([valid_book(name_or_title=None, price=-5)])
    counts = count_reasons(rejected)
    assert counts["missing_name"] == 1
    assert counts["invalid_price"] == 1
    assert sum(counts.values()) == 2
    assert len(rejected) == 1


def test_split_valid_logs_a_warning_per_rejection(caplog):
    with caplog.at_level("WARNING"):
        split_valid([valid_book(name_or_title=None)])
    assert len(caplog.records) == 1
    assert "missing_name" in caplog.text
