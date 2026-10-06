"""Entry point: scrape both sources, clean, validate, deduplicate, write outputs.

    python main.py                      # everything, duplicates flagged
    python main.py --max-pages 2        # quick check
    python main.py --source quotes      # one source only
    python main.py --drop-duplicates    # remove duplicate rows from the CSV

This file only wires the stages together. All the real work lives in scrapers/
(anything that touches the internet) and processing/ (anything that transforms
data), per the layering rule in plan.md Section 0.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import Counter
from typing import Any

import config
from processing.cleaning import utc_now_iso
from processing.deduplication import mark_duplicates
from processing.models import COLUMNS, Record
from processing.transform import (
    BOOKS_SOURCE,
    QUOTES_SOURCE,
    book_to_record,
    quote_to_record,
)
from processing.validation import Rejection, count_reasons, split_valid
from scrapers.base_scraper import BaseScraper
from scrapers.books_scraper import BooksScraper
from scrapers.quotes_scraper import QuotesScraper

logger = logging.getLogger("main")

REJECTION_COLUMN = "rejection_reasons"


def positive_int(value: str) -> int:
    """argparse type for --max-pages: must be 1 or more.

    Rejecting 0 here keeps the "did this source fail?" rule unambiguous:
    without it, --max-pages 0 would collect nothing and look like a failure.
    """
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {number}")
    return number


# --------------------------------------------------------------------- setup


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Define and read the command line options."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Scrape books.toscrape.com and quotes.toscrape.com, clean and "
            "standardize the results, validate them, detect duplicates, and "
            "write one consolidated CSV plus a run summary."
        ),
        epilog=(
            "Outputs are written to output/ and the run log to logs/scraper.log. "
            "A full run makes about 1,050 requests and takes roughly 17 minutes; "
            "use --max-pages 2 or --skip-details for a fast check."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=["books", "quotes", "all"],
        default="all",
        help="which site(s) to scrape",
    )
    parser.add_argument(
        "--max-pages",
        type=positive_int,
        default=None,
        metavar="N",
        help="stop after N listing pages per source; omit to follow every page",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=config.REQUEST_DELAY,
        metavar="SECONDS",
        help="pause between requests; lower is faster but less polite",
    )
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help=(
            "do not open each book's detail page; much faster, but category, "
            "description and availability will be empty for every book"
        ),
    )
    parser.add_argument(
        "--drop-duplicates",
        action="store_true",
        help=(
            "remove duplicate rows from the CSV instead of keeping them with "
            "is_duplicate=true"
        ),
    )
    return parser.parse_args(argv)


def setup_logging() -> None:
    """Send logs to the console and to logs/scraper.log. Called once, here."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)

    # mode="w" so every run leaves one clean, self-contained log for the ZIP
    log_file = logging.FileHandler(config.LOG_FILE, mode="w", encoding="utf-8")
    log_file.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()  # makes re-running inside one process safe
    root.addHandler(console)
    root.addHandler(log_file)


def ensure_directories() -> None:
    """Create output/ and logs/ if they are missing."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------- scraping


def selected_sources(choice: str) -> list[str]:
    """Turn the --source option into the list of source names to run."""
    if choice == "books":
        return [BOOKS_SOURCE]
    if choice == "quotes":
        return [QUOTES_SOURCE]
    return [BOOKS_SOURCE, QUOTES_SOURCE]


def scrape_one_source(
    source: str,
    session: BaseScraper,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, int], str | None]:
    """Scrape one source. Returns (raw records, stats, error message or None).

    Any exception is caught here so one failing source can never stop the
    other. The error text is kept for the summary report.
    """
    try:
        if source == BOOKS_SOURCE:
            scraper = BooksScraper(scraper=session)
            raw = scraper.scrape(
                max_pages=args.max_pages,
                skip_details=args.skip_details,
            )
        else:
            scraper = QuotesScraper(scraper=session)
            raw = scraper.scrape(max_pages=args.max_pages)
        return raw, dict(scraper.stats), None

    # Deliberately broad: a crash in one source must not end the run
    except Exception as exc:
        logger.error("Source %s failed and was abandoned: %s", source, exc, exc_info=True)
        return [], {}, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- transforming


def transform_one_source(
    source: str,
    raw_records: list[dict[str, Any]],
    scraped_at: str,
) -> tuple[list[Record], int]:
    """Map raw dicts to Records. Returns (records, number that failed)."""
    to_record = book_to_record if source == BOOKS_SOURCE else quote_to_record
    records: list[Record] = []
    failed = 0

    for raw in raw_records:
        try:
            records.append(to_record(raw, scraped_at))
        # Deliberately broad: one unmappable record must not lose the rest
        except Exception as exc:
            failed += 1
            logger.warning(
                "Transform failed for a %s record (%s); skipping it",
                source,
                exc,
            )

    if failed:
        logger.warning("%s: %s record(s) could not be transformed", source, failed)
    return records, failed


# -------------------------------------------------------------------- writing


def format_cell(column: str, value: object) -> object:
    """Render one value the way the CSV should show it."""
    if value is None:
        return ""  # empty cell, never "None" and never a stand-in value
    if column == "price":
        return f"{value:.2f}"  # 51.8 must still read as 51.80
    if column == "is_duplicate":
        return "true" if value else "false"
    return value


def record_to_row(record: Record, extra: dict[str, str] | None = None) -> dict[str, object]:
    """Turn a Record into a CSV row dict in COLUMNS order."""
    data = record.as_dict()
    row = {column: format_cell(column, data[column]) for column in COLUMNS}
    if extra:
        row.update(extra)
    return row


def write_final_csv(records: list[Record]) -> int:
    """Write output/final_dataset.csv and return the number of data rows."""
    # utf-8-sig writes a byte-order mark, which is what makes Excel on Windows
    # read the file as UTF-8 instead of the local code page (so "£" and curly
    # characters display correctly rather than as mojibake).
    with config.FINAL_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record_to_row(record))

    logger.info("Wrote %s row(s) to %s", len(records), config.FINAL_CSV)
    return len(records)


def write_rejected_csv(rejections: list[Rejection]) -> int:
    """Write output/rejected_records.csv; always writes the header row."""
    fieldnames = COLUMNS + [REJECTION_COLUMN]

    with config.REJECTED_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rejection in rejections:
            writer.writerow(
                record_to_row(
                    rejection.record,
                    {REJECTION_COLUMN: ";".join(rejection.reasons)},
                )
            )

    logger.info("Wrote %s rejected row(s) to %s", len(rejections), config.REJECTED_CSV)
    return len(rejections)


# -------------------------------------------------------------------- summary


def empty_values_per_column(records: list[Record]) -> dict[str, int]:
    """How many records have nothing in each column."""
    counts = {column: 0 for column in COLUMNS}
    for record in records:
        data = record.as_dict()
        for column in COLUMNS:
            if data[column] is None or data[column] == "":
                counts[column] += 1
    return counts


def duplicate_groups(records: list[Record]) -> list[dict[str, Any]]:
    """One entry per record_id that occurs more than once."""
    by_id: dict[str, list[Record]] = {}
    for record in records:
        by_id.setdefault(record.record_id or "", []).append(record)

    groups = []
    for record_id, group in by_id.items():
        if len(group) < 2:
            continue
        groups.append(
            {
                "title": group[0].name_or_title,
                "source": group[0].source,
                "record_id": record_id,
                "copies": len(group),
                "source_urls": [record.source_url for record in group],
            }
        )
    return groups


def build_reconciliation(
    collected: int,
    transform_failed: int,
    rejected: int,
    after_validation: int,
    duplicates: int,
    final_unique: int,
    csv_rows: int,
    drop_duplicates: bool,
) -> dict[str, Any]:
    """Show the arithmetic that must hold, and whether it does."""
    validation_ok = collected - transform_failed - rejected == after_validation
    dedup_ok = after_validation - duplicates == final_unique
    expected_rows = final_unique if drop_duplicates else after_validation
    rows_ok = csv_rows == expected_rows

    return {
        "collected_minus_transform_failed_minus_rejected": {
            "formula": f"{collected} - {transform_failed} - {rejected} = {after_validation}",
            "after_validation": after_validation,
            "ok": validation_ok,
        },
        "after_validation_minus_duplicates": {
            "formula": f"{after_validation} - {duplicates} = {final_unique}",
            "final_unique": final_unique,
            "ok": dedup_ok,
        },
        "csv_rows_match_mode": {
            "mode": "removed" if drop_duplicates else "flagged",
            "formula": f"csv_rows {csv_rows} == expected {expected_rows}",
            "ok": rows_ok,
        },
        "ok": validation_ok and dedup_ok and rows_ok,
    }


def write_summary(summary: dict[str, Any]) -> None:
    """Write output/summary_report.json."""
    with config.SUMMARY_JSON.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
    logger.info("Wrote %s", config.SUMMARY_JSON)


# ----------------------------------------------------------------------- main


def run(args: argparse.Namespace) -> int:
    """Run the whole pipeline. Returns the process exit code."""
    started_at = utc_now_iso()
    started = time.perf_counter()
    cli_options = vars(args)

    logger.info("=" * 70)
    logger.info("RUN START %s", started_at)
    logger.info("options: %s", cli_options)
    logger.info("=" * 70)

    ensure_directories()

    sources = selected_sources(args.source)
    # One session for every source, so connections are pooled across the run
    session = BaseScraper(delay=args.delay)

    per_source: dict[str, dict[str, Any]] = {}
    valid_by_source: dict[str, list[Record]] = {}
    all_rejections: list[Rejection] = []
    failed_sources: list[str] = []

    # ---------- scrape -> transform -> validate, one source at a time ----------
    for source in sources:
        logger.info("--- %s ---", source)
        requests_before = session.requests_made
        failures_before = session.requests_failed

        raw, stats, error = scrape_one_source(source, session, args)

        # A source failed if it produced no records at all, whatever the cause:
        # it raised, every page request failed, or the pages returned HTTP 200
        # with nothing in them (a broken selector). "Contributed no data" is
        # the thing the exit code is about, so that is what we measure.
        # --max-pages 0 cannot reach here: argparse rejects it.
        if not raw:
            failed_sources.append(source)
            logger.error(
                "Source %s produced no records (pages_scraped=%s, pages_failed=%s, "
                "pages_empty=%s, error=%s)",
                source,
                stats.get("pages_scraped", 0),
                stats.get("pages_failed", 0),
                stats.get("pages_empty", 0),
                error,
            )

        records, transform_failed = transform_one_source(source, raw, started_at)
        valid, rejected = split_valid(records)

        valid_by_source[source] = valid
        all_rejections.extend(rejected)

        per_source[source] = {
            "pages_scraped": stats.get("pages_scraped", 0),
            "pages_failed": stats.get("pages_failed", 0),
            "pages_empty": stats.get("pages_empty", 0),
            "requests_made": session.requests_made - requests_before,
            "requests_failed": session.requests_failed - failures_before,
            "detail_pages_failed": stats.get("detail_pages_failed", 0),
            "collected": len(raw),
            "transform_failed": transform_failed,
            "after_cleaning": len(records),
            "rejected": len(rejected),
            "duplicates": 0,      # filled in after deduplication
            "final_unique": 0,    # filled in after deduplication
            "error": error,
        }
        logger.info(
            "%s: collected=%s after_cleaning=%s valid=%s rejected=%s",
            source,
            len(raw),
            len(records),
            len(valid),
            len(rejected),
        )

    session.close()

    # ---------- deduplicate across the combined, validated records ----------
    all_valid: list[Record] = []
    for source in sources:
        all_valid.extend(valid_by_source[source])

    logger.info("--- deduplication ---")
    mark_duplicates(all_valid)

    for source in sources:
        group = valid_by_source[source]
        duplicates = sum(1 for record in group if record.is_duplicate)
        per_source[source]["duplicates"] = duplicates
        per_source[source]["final_unique"] = len(group) - duplicates

    total_duplicates = sum(1 for record in all_valid if record.is_duplicate)
    final_unique = len(all_valid) - total_duplicates

    # ---------- write outputs ----------
    logger.info("--- outputs ---")
    rows_to_write = (
        [record for record in all_valid if not record.is_duplicate]
        if args.drop_duplicates
        else all_valid
    )
    csv_rows = write_final_csv(rows_to_write)
    write_rejected_csv(all_rejections)

    # ---------- summary ----------
    collected = sum(per_source[s]["collected"] for s in sources)
    transform_failed = sum(per_source[s]["transform_failed"] for s in sources)
    rejected_total = sum(per_source[s]["rejected"] for s in sources)

    reconciliation = build_reconciliation(
        collected=collected,
        transform_failed=transform_failed,
        rejected=rejected_total,
        after_validation=len(all_valid),
        duplicates=total_duplicates,
        final_unique=final_unique,
        csv_rows=csv_rows,
        drop_duplicates=args.drop_duplicates,
    )
    if not reconciliation["ok"]:
        logger.error("Reconciliation FAILED: %s", reconciliation)

    finished = time.perf_counter()
    summary = {
        "run": {
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "duration_seconds": round(finished - started, 2),
            "cli_options": cli_options,
            "failed_sources": failed_sources,
        },
        "per_source": per_source,
        "rejected_by_reason": dict(count_reasons(all_rejections)),
        "duplicates": {
            "detected": total_duplicates,
            "action": "removed" if args.drop_duplicates else "flagged",
            "groups": duplicate_groups(all_valid),
        },
        "csv_rows": csv_rows,
        "final_record_count": final_unique,
        "data_quality": {
            "empty_values_per_column": {
                "all": empty_values_per_column(all_valid),
                **{
                    source: empty_values_per_column(valid_by_source[source])
                    for source in sources
                },
            }
        },
        "reconciliation": reconciliation,
    }
    write_summary(summary)

    duration = finished - started
    logger.info("=" * 70)
    logger.info("RUN END   duration=%.1fs (%.1f min)", duration, duration / 60)
    logger.info(
        "collected=%s rejected=%s duplicates=%s csv_rows=%s final_unique=%s reconciliation_ok=%s",
        collected,
        rejected_total,
        total_duplicates,
        csv_rows,
        final_unique,
        reconciliation["ok"],
    )
    if failed_sources:
        logger.error("failed sources: %s", failed_sources)
    logger.info("=" * 70)

    # Only a total failure is a failed run; one source surviving is a success
    if failed_sources and len(failed_sources) == len(sources):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, set logging up, run the pipeline."""
    args = parse_args(argv)
    setup_logging()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
