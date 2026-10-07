"""Demonstrate that one failing source never stops the other.

Run with:  python scripts/try_failure.py

Monkeypatches at runtime so no pipeline code is edited. Three scenarios:
  1. Books pointed at a 404 URL  -> graceful failure, pages_failed=1
  2. BooksScraper.scrape raises   -> caught, recorded in summary.run.failed_sources
  3. Both sources raise           -> exit code 1
In 1 and 2 the Quotes source must still finish and the outputs must still be written.
"""

# Running this as "python scripts/<name>.py" puts scripts/ on the import path,
# not the project root, so "import config" would fail. Add the project root.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


import json

import config
import main as pipeline
from scrapers.books_scraper import BooksScraper
from scrapers.quotes_scraper import QuotesScraper


def report(label: str, exit_code: int) -> None:
    """Print what the summary recorded for this scenario."""
    # config's absolute path, so the script does not depend on the working directory
    with config.SUMMARY_JSON.open(encoding="utf-8") as handle:
        summary = json.load(handle)

    print(f"\n  exit code              : {exit_code}")
    print(f"  failed_sources         : {summary['run']['failed_sources']}")
    for source, stats in summary["per_source"].items():
        print(
            f"  {source:18} collected={stats['collected']:<4}"
            f" pages_failed={stats['pages_failed']}"
            f" final_unique={stats['final_unique']:<4}"
            f" error={stats['error']}"
        )
    print(f"  csv_rows               : {summary['csv_rows']}")
    print(f"  reconciliation ok      : {summary['reconciliation']['ok']}")


def scenario_bad_url() -> None:
    """Books base URL returns 404: the scraper stops that source cleanly."""
    print("\n" + "=" * 78)
    print("1. BOOKS POINTED AT A 404 URL (graceful source failure)")
    print("=" * 78)
    original = config.BOOKS_BASE_URL
    config.BOOKS_BASE_URL = "https://books.toscrape.com/no-such-page-exists.html"
    try:
        code = pipeline.main(["--source", "all", "--max-pages", "1"])
    finally:
        config.BOOKS_BASE_URL = original
    report("bad url", code)
    print("  -> Quotes still completed and the CSV was still written")


def scenario_books_raises() -> None:
    """BooksScraper.scrape raises: main.py catches it and carries on."""
    print("\n" + "=" * 78)
    print("2. BooksScraper.scrape RAISES (unexpected crash in one source)")
    print("=" * 78)
    original = BooksScraper.scrape

    def boom(self, *args, **kwargs):
        raise RuntimeError("simulated scraper crash")

    BooksScraper.scrape = boom
    try:
        code = pipeline.main(["--source", "all", "--max-pages", "1"])
    finally:
        BooksScraper.scrape = original
    report("books raises", code)
    print("  -> the traceback is LOGGED (exc_info=True) but never raised; the run continued")


def scenario_both_raise() -> None:
    """Every source fails: the run is a failure and exits 1."""
    print("\n" + "=" * 78)
    print("3. BOTH SOURCES RAISE (total failure -> exit code 1)")
    print("=" * 78)
    original_books = BooksScraper.scrape
    original_quotes = QuotesScraper.scrape

    def boom(self, *args, **kwargs):
        raise RuntimeError("simulated scraper crash")

    BooksScraper.scrape = boom
    QuotesScraper.scrape = boom
    try:
        code = pipeline.main(["--source", "all", "--max-pages", "1"])
    finally:
        BooksScraper.scrape = original_books
        QuotesScraper.scrape = original_quotes
    report("both raise", code)
    print("  -> exit code 1 because EVERY selected source failed")


def scenario_only_source_fails() -> None:
    """--source books with a dead URL: the whole run produced nothing -> exit 1."""
    print("\n" + "=" * 78)
    print("4. THE ONLY SELECTED SOURCE FAILS (--source books, 404) -> exit code 1")
    print("=" * 78)
    original = config.BOOKS_BASE_URL
    config.BOOKS_BASE_URL = "https://books.toscrape.com/no-such-page-exists.html"
    try:
        code = pipeline.main(["--source", "books", "--max-pages", "1"])
    finally:
        config.BOOKS_BASE_URL = original
    report("only source fails", code)
    print("  -> a run that collected nothing must not report success")


if __name__ == "__main__":
    scenario_bad_url()
    scenario_books_raises()
    scenario_both_raise()
    scenario_only_source_fails()
    print("\ntry_failure finished - nothing crashed the process\n")
