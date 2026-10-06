"""The single row shape that both sources are mapped into.

One dataclass covers Books and Quotes. Fields that only one source can fill are
nullable and stay None for the other - never filled with a placeholder.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(kw_only=True)
class Record:
    """One output row. Field order here IS the CSV column order.

    kw_only=True forces construction by keyword, so 15 fields can never be
    mixed up positionally, and it lets record_id keep a default while later
    fields stay required.
    """

    record_id: str | None = None      # SHA-256 fingerprint; Phase 5 fills this
    source: str                        # "Books to Scrape" or "Quotes to Scrape"
    source_url: str | None = None      # book detail page / quote listing page
    name_or_title: str | None = None   # book title or the quote text
    category: str | None = None        # books only
    price: float | None = None         # books only
    currency: str | None = None        # "GBP" only when a price was parsed
    availability: int | None = None    # books only, stock count
    rating: int | None = None          # books only, 1-5
    author: str | None = None          # quotes only
    author_url: str | None = None      # quotes only
    tags: str | None = None            # quotes only, "a;b;c"
    description: str | None = None     # books only, may be absent
    scraped_at: str                    # one UTC ISO timestamp per run
    is_duplicate: bool = False         # Phase 5 flips this

    def as_dict(self) -> dict[str, object]:
        """Plain dict for the CSV writer, keys in COLUMNS order."""
        return asdict(self)


# Derived from the dataclass rather than retyped, so the two can never drift
# apart. Section 4 of plan.md fixes this order.
COLUMNS: list[str] = [field.name for field in fields(Record)]
