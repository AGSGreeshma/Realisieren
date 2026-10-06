"""Checks that a cleaned Record is fit to publish.

Validation never repairs and never guesses: it reports problem codes and lets
the caller decide. A record with an empty problem list is valid; anything else
is rejected, written to output/rejected_records.csv with its reasons, and
counted in the summary.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Iterable, NamedTuple

from processing.cleaning import normalize_url
from processing.models import Record
from processing.transform import BOOKS_SOURCE, QUOTES_SOURCE

logger = logging.getLogger(__name__)

KNOWN_SOURCES = (BOOKS_SOURCE, QUOTES_SOURCE)


class Rejection(NamedTuple):
    """A rejected record together with why it was rejected."""

    record: Record
    reasons: list[str]


def _is_real_number(value: object) -> bool:
    """True for a usable int/float. Rejects bool, NaN and infinity."""
    # bool is a subclass of int in Python, so True would otherwise pass as 1
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not (math.isnan(value) or math.isinf(value))


def _is_real_int(value: object) -> bool:
    """True for a genuine int. Rejects bool and floats."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_blank(value: object) -> bool:
    """True for None or a string with nothing but whitespace in it."""
    return value is None or (isinstance(value, str) and not value.strip())


def validate_record(record: Record) -> list[str]:
    """Return a list of problem codes; an empty list means the record is valid."""
    problems: list[str] = []

    if record.source not in KNOWN_SOURCES:
        problems.append("unknown_source")

    if _is_blank(record.name_or_title):
        problems.append("missing_name")

    # Re-use the same URL rule the cleaning layer uses, so the two agree
    if normalize_url(record.source_url) is None:
        problems.append("invalid_url")

    # Absent is fine (books have no author page); present but broken is not
    if record.author_url is not None and normalize_url(record.author_url) is None:
        problems.append("invalid_author_url")

    if record.price is not None:
        if not _is_real_number(record.price) or record.price < 0:
            problems.append("invalid_price")

    # A price with no currency label, or a currency with no amount, is incomplete
    if (record.price is None) != (record.currency is None):
        problems.append("price_currency_mismatch")

    if record.rating is not None:
        if not _is_real_int(record.rating) or not 1 <= record.rating <= 5:
            problems.append("invalid_rating")

    if record.availability is not None:
        if not _is_real_int(record.availability) or record.availability < 0:
            problems.append("invalid_availability")

    # Source-specific rule: a quote without its author is not usable
    if record.source == QUOTES_SOURCE and _is_blank(record.author):
        problems.append("missing_author")

    if _is_blank(record.scraped_at):
        problems.append("missing_scraped_at")

    return problems


def split_valid(records: Iterable[Record]) -> tuple[list[Record], list[Rejection]]:
    """Split records into (valid, rejected), logging one WARNING per rejection."""
    valid: list[Record] = []
    rejected: list[Rejection] = []

    for record in records:
        problems = validate_record(record)
        if not problems:
            valid.append(record)
            continue

        rejected.append(Rejection(record=record, reasons=problems))
        logger.warning(
            "Rejected record from %s: %r - %s",
            record.source,
            (record.name_or_title or "")[:60],
            ", ".join(problems),
        )

    return valid, rejected


def count_reasons(rejected: Iterable[Rejection]) -> Counter[str]:
    """Count how often each problem code occurred, for summary_report.json."""
    counter: Counter[str] = Counter()
    for rejection in rejected:
        # update() with a list counts every code, so a record with two
        # problems contributes to both totals
        counter.update(rejection.reasons)
    return counter
