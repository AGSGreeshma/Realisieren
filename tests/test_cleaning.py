"""Offline unit tests for the pure cleaning functions.

Every function here is tested in isolation with literal inputs. The
fixture-based transform tests live in test_parsers.py, next to the parsing
they depend on.
"""

from __future__ import annotations


import pytest

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
