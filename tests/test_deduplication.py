"""Offline tests for normalize_for_key, make_fingerprint and mark_duplicates."""

from __future__ import annotations

import pytest

from processing.deduplication import (
    count_duplicates,
    make_fingerprint,
    mark_duplicates,
    normalize_for_key,
)
from processing.models import Record

SCRAPED_AT = "2026-10-07T10:15:00Z"


def book(title: str, url: str = "https://books.toscrape.com/x/index.html") -> Record:
    """A minimal book Record carrying only what the fingerprint uses."""
    return Record(
        source="Books to Scrape",
        source_url=url,
        name_or_title=title,
        scraped_at=SCRAPED_AT,
    )


def quote(text: str, author: str) -> Record:
    """A minimal quote Record carrying only what the fingerprint uses."""
    return Record(
        source="Quotes to Scrape",
        source_url="https://quotes.toscrape.com/",
        name_or_title=text,
        author=author,
        scraped_at=SCRAPED_AT,
    )


# ------------------------------------------------------- normalize_for_key


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Example Book Title", "example book title"),
        ("  Example Book Title  ", "example book title"),
        ("EXAMPLE BOOK TITLE", "example book title"),
        ("Hello, World!", "hello world"),
        ("hello world", "hello world"),
        ("“quoted”", "quoted"),          # curly quotes are punctuation
        ("a b", "a b"),                        # non-breaking space
        ("Multi   space\ttab\nnewline", "multi space tab newline"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_for_key(raw, expected):
    assert normalize_for_key(raw) == expected


def test_normalize_does_not_change_the_record():
    """Normalization is for comparison only; display values stay untouched."""
    record = book("  Example Book Title  ")
    normalize_for_key(record.name_or_title)
    assert record.name_or_title == "  Example Book Title  "


# ------------------------------------------------- the plan.md Done-when case


def test_three_title_variants_are_one_unique_record():
    """plan.md Phase 5: these three must collapse to 1 unique, 2 duplicates."""
    records = [
        book("Example Book Title"),
        book(" Example Book Title "),
        book("EXAMPLE BOOK TITLE"),
    ]
    mark_duplicates(records)

    assert count_duplicates(records) == 2
    assert len({r.record_id for r in records}) == 1
    assert [r.is_duplicate for r in records] == [False, True, True]


def test_punctuation_only_difference_is_a_duplicate():
    records = [book("Hello, World!"), book("hello world")]
    mark_duplicates(records)
    assert records[1].is_duplicate is True
    assert records[0].record_id == records[1].record_id


def test_curly_quote_difference_is_a_duplicate():
    records = [book("“The Title”"), book("The Title")]
    mark_duplicates(records)
    assert records[1].is_duplicate is True


# ----------------------------------------------------------- non-duplicates


def test_same_quote_text_different_author_is_not_a_duplicate():
    """Author is part of a quote's identity."""
    records = [
        quote("The same words exactly.", "Albert Einstein"),
        quote("The same words exactly.", "Marilyn Monroe"),
    ]
    mark_duplicates(records)

    assert count_duplicates(records) == 0
    assert records[0].record_id != records[1].record_id


def test_same_author_and_text_is_a_duplicate():
    records = [
        quote("The same words exactly.", "Albert Einstein"),
        quote("  the SAME words, exactly!  ", "albert einstein"),
    ]
    mark_duplicates(records)
    assert records[1].is_duplicate is True


def test_same_title_across_sources_is_not_a_duplicate():
    """source is part of every fingerprint, so the two sources never collide."""
    as_book = book("Identical Text")
    as_quote = quote("Identical Text", "Identical Text")
    records = [as_book, as_quote]
    mark_duplicates(records)

    assert count_duplicates(records) == 0
    assert as_book.record_id != as_quote.record_id


def test_different_titles_are_not_duplicates():
    records = [book("First Book"), book("Second Book"), book("Third Book")]
    mark_duplicates(records)
    assert count_duplicates(records) == 0
    assert len({r.record_id for r in records}) == 3


def test_field_separator_prevents_a_boundary_collision():
    """author "AB" + text "C" must not hash the same as "A" + "BC"."""
    first = quote("C", "AB")
    second = quote("BC", "A")
    assert make_fingerprint(first) != make_fingerprint(second)


# ----------------------------------------------------------- order and ids


def test_first_occurrence_is_the_one_kept():
    first = book("Same Title", url="https://books.toscrape.com/first/index.html")
    second = book("Same Title", url="https://books.toscrape.com/second/index.html")
    third = book("Same Title", url="https://books.toscrape.com/third/index.html")
    mark_duplicates([first, second, third])

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert third.is_duplicate is True


def test_order_decides_which_is_first():
    """Reversing the input reverses which copy is kept - it is order-stable,
    not content-based."""
    a = book("Same Title", url="https://books.toscrape.com/a/index.html")
    b = book("Same Title", url="https://books.toscrape.com/b/index.html")
    mark_duplicates([b, a])
    assert b.is_duplicate is False
    assert a.is_duplicate is True


def test_duplicates_share_a_record_id():
    records = [book("Same Title"), book("same title")]
    mark_duplicates(records)
    assert records[0].record_id == records[1].record_id


def test_non_duplicates_have_different_record_ids():
    records = [book("One"), book("Two")]
    mark_duplicates(records)
    assert records[0].record_id != records[1].record_id


def test_every_record_gets_a_record_id():
    records = [book("One"), book("Two"), book("one")]
    mark_duplicates(records)
    for record in records:
        assert record.record_id is not None
        assert len(record.record_id) == 64  # SHA-256 hex digest


def test_fingerprint_is_deterministic():
    """Same input, same hash - every run, every machine."""
    assert make_fingerprint(book("A Title")) == make_fingerprint(book("A Title"))


def test_mark_duplicates_is_idempotent():
    """Running it twice must not turn first occurrences into duplicates."""
    records = [book("Same"), book("same")]
    mark_duplicates(records)
    mark_duplicates(records)
    assert [r.is_duplicate for r in records] == [False, True]


def test_mark_duplicates_on_an_empty_list():
    assert mark_duplicates([]) == []


def test_mark_duplicates_returns_the_same_list():
    records = [book("One")]
    assert mark_duplicates(records) is records


def test_duplicate_logs_one_info_line(caplog):
    with caplog.at_level("INFO"):
        mark_duplicates([book("Same"), book("same")])
    assert any("Duplicate:" in message for message in caplog.messages)
