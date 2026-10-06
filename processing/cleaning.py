"""Pure cleaning functions: raw scraped text in, standardized values out.

Every function here is pure - no network, no files, no logging, no shared
state. Given the same input it always returns the same output, which is what
makes them trivial to unit test offline.

Every function accepts None and returns None rather than raising, because the
scrapers deliberately produce None for any element that was missing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

# Typographic quotation marks used by quotes.toscrape.com
CURLY_OPEN = "“"   # "
CURLY_CLOSE = "”"  # "

# Matches an optional minus, then digits that may contain thousands commas,
# then an optional decimal part. Keeping the minus means a negative price
# survives cleaning so validation can reject it in Phase 5.
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# Any run of digits, used for the stock count
_DIGITS_RE = re.compile(r"\d+")

# The site appends a "...more" link to most book descriptions
_MORE_SUFFIX_RE = re.compile(r"\s*\.\.\.\s*more\s*$", re.IGNORECASE)

# Rating words map to numbers. Matched by word, never by class position.
_RATING_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

# Phrases that mean zero stock when no number is present
_OUT_OF_STOCK_PHRASES = ("out of stock", "unavailable", "not available", "sold out")


def clean_text(value: str | None) -> str | None:
    """Collapse all whitespace to single spaces and strip; None if empty."""
    if value is None:
        return None
    # \xa0 is a non-breaking space: it looks like a space but is not one
    text = str(value).replace("\xa0", " ")
    # split() with no argument splits on any whitespace run and drops empties,
    # so this collapses newlines, tabs and runs of spaces in one step
    text = " ".join(text.split())
    return text or None


def strip_quotes(value: str | None) -> str | None:
    """Remove quote marks that wrap the whole text, from the ends only."""
    if value is None:
        return None
    text = value.strip()
    # Loop so "..." wrapped in both kinds is handled, in either order
    while len(text) >= 2:
        if text[0] == CURLY_OPEN and text[-1] == CURLY_CLOSE:
            text = text[1:-1].strip()
        elif text[0] == '"' and text[-1] == '"':
            text = text[1:-1].strip()
        else:
            break  # not wrapped: leave any internal quotes alone
    return text or None


def clean_price(raw: str | None) -> float | None:
    """'£51.77' -> 51.77, rounded to 2 decimals; None if there is no number."""
    if raw is None:
        return None
    text = str(raw).replace("\xa0", " ")
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    # Thousands separators must go before float() will accept the string
    number = match.group(0).replace(",", "")
    try:
        return round(float(number), 2)
    except ValueError:
        return None


def clean_rating(raw: str | None) -> int | None:
    """'star-rating Three' -> 3 by matching the word, never its position."""
    if raw is None:
        return None
    # Hyphens become spaces so "star-rating-three" would work too
    for token in str(raw).replace("-", " ").split():
        number = _RATING_WORDS.get(token.lower())
        if number is not None:
            return number
    return None


def clean_availability(raw: str | None) -> int | None:
    """'In stock (22 available)' -> 22; out-of-stock text -> 0; else None."""
    text = clean_text(raw)
    if text is None:
        return None
    lowered = text.lower()
    # Checked before the digits, so "Out of stock" can never pick up a stray
    # number from elsewhere in the sentence
    if any(phrase in lowered for phrase in _OUT_OF_STOCK_PHRASES):
        return 0
    match = _DIGITS_RE.search(text)
    if match is None:
        return None
    return int(match.group(0))


def clean_tags(tags: list[str] | None) -> str | None:
    """['Love',' life ','love'] -> 'life;love'; empty or None -> None."""
    if not tags:
        return None
    # A bare string is iterable, so without this guard "love" would be
    # treated as five separate one-character tags
    if isinstance(tags, str):
        tags = [tags]
    unique = set()
    for tag in tags:
        text = clean_text(tag)
        if text:
            unique.add(text.lower())  # lowercase so "Love" and "love" are one tag
    if not unique:
        return None
    return ";".join(sorted(unique))  # sorted so the same tags always compare equal


def normalize_url(url: str | None, base: str | None = None) -> str | None:
    """Absolute http(s) URL with a host, or None if it is not usable."""
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None
    if base:
        text = urljoin(base, text)
    parsed = urlparse(text)
    # Rejects "javascript:void(0)", "mailto:...", "/path" with no base, and ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return text


def clean_description(raw: str | None) -> str | None:
    """Clean the text and drop the site's trailing '...more' link text."""
    text = clean_text(raw)
    if text is None:
        return None
    # Verified on the live site: 943 of 998 descriptions end with "...more"
    text = _MORE_SUFFIX_RE.sub("", text)
    return text.strip() or None


def utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string, e.g. '2026-10-07T10:15:00Z'."""
    # timezone-aware; datetime.utcnow() is deprecated and returns a naive value
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
