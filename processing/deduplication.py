"""Duplicate detection by normalized fingerprint.

The rule (plan.md Section 7):
  normalize -> join identity fields -> SHA-256
    Books:  source + title
    Quotes: source + author + full quote text

Duplicates are FLAGGED, never deleted, so the counts stay auditable and the
evidence remains in the dataset. main.py's --drop-duplicates removes them at
write time if you want a deduplicated file.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from typing import Iterable

from processing.models import Record
from processing.transform import QUOTES_SOURCE

logger = logging.getLogger(__name__)

# Joins the identity fields. \x1f is the ASCII "unit separator" control
# character, which cannot occur in scraped page text, so two different field
# splits can never produce the same key (e.g. author "AB" + text "C" versus
# author "A" + text "BC").
_FIELD_SEPARATOR = "\x1f"


def normalize_for_key(text: str | None) -> str:
    """Lowercase, NFKC-normalize, drop punctuation, collapse whitespace.

    Used only for comparison. The Record's own display values are never
    changed by this function.
    """
    if text is None:
        return ""

    # NFKC folds compatibility forms, so full-width and ligature characters
    # compare equal to their plain equivalents
    normalized = unicodedata.normalize("NFKC", str(text))

    # Unicode category "P*" is every kind of punctuation, which includes the
    # curly quotes (Pi/Pf) as well as commas, apostrophes and dashes.
    # Punctuation becomes a SPACE rather than being deleted, so that
    # "Hello, World!" and "hello world" normalize to the same thing.
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )

    return " ".join(without_punctuation.lower().split())


def make_fingerprint(record: Record) -> str:
    """SHA-256 hex digest of the record's normalized identity fields."""
    if record.source == QUOTES_SOURCE:
        # Author is part of the identity: the same words said by two people
        # are two different quotations
        parts = [record.source, record.author, record.name_or_title]
    else:
        parts = [record.source, record.name_or_title]

    key = _FIELD_SEPARATOR.join(normalize_for_key(part) for part in parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def mark_duplicates(records: list[Record]) -> list[Record]:
    """Set record_id on every record and flag repeat occurrences.

    The first record with a given fingerprint keeps is_duplicate=False; every
    later one is set to True. Input order decides which is "first", so the
    result is stable for a stable input.
    """
    first_seen: dict[str, Record] = {}
    duplicate_count = 0

    for record in records:
        fingerprint = make_fingerprint(record)
        # Duplicates deliberately SHARE this id: it identifies the item, not
        # the row, so copies can be grouped and audited together.
        record.record_id = fingerprint

        original = first_seen.get(fingerprint)
        if original is None:
            first_seen[fingerprint] = record
            record.is_duplicate = False
            continue

        record.is_duplicate = True
        duplicate_count += 1
        logger.info(
            "Duplicate: %r (%s) duplicates %r (%s)",
            (record.name_or_title or "")[:50],
            record.source_url,
            (original.name_or_title or "")[:50],
            original.source_url,
        )

    logger.info(
        "Duplicate detection: %s duplicate(s) among %s record(s), %s unique",
        duplicate_count,
        len(records),
        len(first_seen),
    )
    return records


def count_duplicates(records: Iterable[Record]) -> int:
    """How many records are flagged as duplicates."""
    return sum(1 for record in records if record.is_duplicate)
