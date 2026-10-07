"""Verify output/ independently of the pipeline that produced it.

Run with:  python scripts/verify_output.py
           python scripts/verify_output.py --no-spot-check   (fully offline)

Deliberately does NOT import the pipeline's own counting code - it re-reads the
CSV with the stdlib csv module and re-derives every number, so a bug in main.py
cannot hide by agreeing with itself.

Then re-fetches 5 random rows (fixed seed) from the live sites and compares.
"""

# Running this as "python scripts/<name>.py" puts scripts/ on the import path,
# not the project root, so "import config" would fail. Add the project root.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


import csv
import json
import random
import re
import sys
import time
from collections import Counter

import requests
from bs4 import BeautifulSoup

import config

SEED = 20261007
SPOT_CHECK_ROWS = 5

CURLY_OPEN = "“"
CURLY_CLOSE = "”"
MOJIBAKE = "Â"

# Detail-page selectors, confirmed against tests/fixtures/
DETAIL_TITLE = "div.product_main h1"
DETAIL_PRICE = "div.product_main p.price_color"
DETAIL_RATING = "div.product_main p.star-rating"
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

ok_all = True


def check(label: str, passed: bool, detail: str = "") -> None:
    """Print one PASS/FAIL line and remember if anything failed."""
    global ok_all
    ok_all = ok_all and passed
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {label}" + (f"  {detail}" if detail else ""))


def fetch(url: str) -> BeautifulSoup:
    """GET a page with the project's own settings."""
    response = requests.get(
        url, headers={"User-Agent": config.USER_AGENT}, timeout=config.TIMEOUT
    )
    response.encoding = "utf-8"
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def load() -> tuple[list[dict], list[dict], dict]:
    """Read both CSVs and the summary JSON."""
    with config.FINAL_CSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with config.REJECTED_CSV.open(encoding="utf-8-sig", newline="") as handle:
        rejected = list(csv.DictReader(handle))
    with config.SUMMARY_JSON.open(encoding="utf-8") as handle:
        summary = json.load(handle)
    return rows, rejected, summary


# ------------------------------------------------------------------ checks


def check_counts(rows: list[dict], rejected: list[dict], summary: dict) -> None:
    print("\n1. ROW COUNTS (csv module vs summary_report.json)")
    unique = [row for row in rows if row["is_duplicate"] == "false"]

    check("csv_rows matches the actual CSV", summary["csv_rows"] == len(rows),
          f"summary={summary['csv_rows']} actual={len(rows)}")
    check("final_record_count matches non-duplicate rows",
          summary["final_record_count"] == len(unique),
          f"summary={summary['final_record_count']} actual={len(unique)}")
    check("record_id is unique among non-duplicate rows",
          len({row['record_id'] for row in unique}) == len(unique),
          f"{len({row['record_id'] for row in unique})} ids / {len(unique)} rows")
    check("rejected_records.csv is empty", len(rejected) == 0, f"{len(rejected)} rows")
    check("summary reports 0 rejected", summary["rejected_by_reason"] == {},
          str(summary["rejected_by_reason"]))
    check("reconciliation ok", summary["reconciliation"]["ok"] is True)


def check_sources(rows: list[dict]) -> None:
    print("\n2. BOTH SOURCES PRESENT")
    counts = Counter(row["source"] for row in rows)
    check("1000 books", counts["Books to Scrape"] == 1000, f"got {counts['Books to Scrape']}")
    check("100 quotes", counts["Quotes to Scrape"] == 100, f"got {counts['Quotes to Scrape']}")
    check("no other source", set(counts) == {"Books to Scrape", "Quotes to Scrape"},
          str(set(counts)))


def check_types(rows: list[dict]) -> None:
    print("\n3. VALUE TYPES AND RANGES")
    books = [row for row in rows if row["source"] == "Books to Scrape"]
    quotes = [row for row in rows if row["source"] == "Quotes to Scrape"]

    bad_price = []
    for row in books:
        try:
            value = float(row["price"])
            if value < 0:
                bad_price.append(row["price"])
        except ValueError:
            bad_price.append(row["price"])
    check("every book price parses as a float >= 0", not bad_price, str(bad_price[:5]))
    check("every price has 2 decimal places",
          all(re.fullmatch(r"-?\d+\.\d{2}", row["price"]) for row in books))

    bad_rating = [row["rating"] for row in books
                  if not (row["rating"].isdigit() and 1 <= int(row["rating"]) <= 5)]
    check("every book rating is an int 1-5", not bad_rating, str(bad_rating[:5]))

    bad_avail = [row["availability"] for row in books
                 if not (row["availability"].isdigit() and int(row["availability"]) >= 0)]
    check("every book availability is an int >= 0", not bad_avail, str(bad_avail[:5]))

    check("every book has currency GBP",
          all(row["currency"] == "GBP" for row in books))
    check("quotes have no price/rating/currency",
          all(row["price"] == "" and row["rating"] == "" and row["currency"] == ""
              for row in quotes))
    check("every quote has an author", all(row["author"] for row in quotes))
    check("every quote author_url is absolute",
          all(row["author_url"].startswith("https://") for row in quotes))
    check("every row has a source_url",
          all(row["source_url"].startswith("https://") for row in rows))
    check("all rows share one scraped_at",
          len({row["scraped_at"] for row in rows}) == 1)


def check_encoding(rows: list[dict]) -> None:
    print("\n4. ENCODING")
    mojibake = [
        (column, value[:40])
        for row in rows
        for column, value in row.items()
        if MOJIBAKE in value
    ]
    check(f"no field contains {MOJIBAKE!r}", not mojibake, str(mojibake[:3]))

    quotes = [row for row in rows if row["source"] == "Quotes to Scrape"]
    curly = [row["name_or_title"][:40] for row in quotes
             if CURLY_OPEN in row["name_or_title"] or CURLY_CLOSE in row["name_or_title"]]
    check("no curly quotes in quote text", not curly, str(curly[:3]))

    check("the CSV starts with a UTF-8 BOM",
          config.FINAL_CSV.read_bytes()[:3] == b"\xef\xbb\xbf")

    pounds = [row for row in rows if "£" in row["name_or_title"]]
    print(f"       (titles containing a literal pound sign: {len(pounds)})")


def check_duplicates(rows: list[dict], summary: dict) -> None:
    print("\n5. DUPLICATES")
    flagged = [row for row in rows if row["is_duplicate"] == "true"]
    check("exactly 1 duplicate flagged", len(flagged) == 1, f"got {len(flagged)}")
    check("summary agrees", summary["duplicates"]["detected"] == len(flagged))
    check("action is 'flagged'", summary["duplicates"]["action"] == "flagged")

    if not flagged:
        return

    title = flagged[0]["name_or_title"]
    check("the duplicate is The Star-Touched Queen",
          title == "The Star-Touched Queen", repr(title))

    group = [row for row in rows if row["name_or_title"] == title]
    check("both copies are present in the CSV", len(group) == 2, f"got {len(group)}")
    check("only one of them is flagged",
          [row["is_duplicate"] for row in group].count("true") == 1)
    check("both share the same record_id",
          len({row["record_id"] for row in group}) == 1)
    print("       copies:")
    for row in group:
        print(f"         is_duplicate={row['is_duplicate']:5} price={row['price']:>7}"
              f" avail={row['availability']:>3}  {row['source_url']}")


# -------------------------------------------------------------- spot check


def spot_check(rows: list[dict]) -> None:
    """Re-fetch 5 random rows from the live sites and compare field by field."""
    print(f"\n6. LIVE SPOT CHECK ({SPOT_CHECK_ROWS} rows, random seed {SEED})")
    random.seed(SEED)

    # Stratified, not uniform: books are 91% of the rows, so a plain sample of
    # 5 almost never includes a quote, leaving author and tags unverified.
    books = [row for row in rows if row["source"] == "Books to Scrape"]
    quotes = [row for row in rows if row["source"] == "Quotes to Scrape"]
    sample = random.sample(books, 3) + random.sample(quotes, 2)

    results = []
    for row in sample:
        time.sleep(config.REQUEST_DELAY)
        try:
            soup = fetch(row["source_url"])
        except requests.RequestException as exc:
            results.append((row, {"error": str(exc)}))
            continue
        if row["source"] == "Books to Scrape":
            results.append((row, live_book(soup)))
        else:
            results.append((row, live_quote(soup, row)))

    print()
    print(f"  {'source':17} {'field':12} {'CSV':34} {'LIVE':34} match")
    print("  " + "-" * 104)
    all_match = True
    for row, live in results:
        if "error" in live:
            print(f"  {row['source']:17} {'(fetch)':12} {live['error'][:60]}")
            all_match = False
            continue
        for field, live_value in live.items():
            csv_value = row[field]
            same = str(csv_value) == str(live_value)
            all_match = all_match and same
            print(f"  {row['source']:17} {field:12} {str(csv_value)[:32]:34}"
                  f" {str(live_value)[:32]:34} {'OK' if same else 'DIFF'}")
        print("  " + "-" * 104)

    check("all spot-checked fields match the live sites", all_match)


def live_book(soup: BeautifulSoup) -> dict:
    """Read title, price and rating straight off a book's detail page."""
    title = soup.select_one(DETAIL_TITLE)
    price = soup.select_one(DETAIL_PRICE)
    rating = soup.select_one(DETAIL_RATING)

    price_value = ""
    if price is not None:
        match = re.search(r"\d+\.\d{2}", price.get_text(strip=True))
        if match:
            price_value = match.group(0)

    rating_value = ""
    if rating is not None:
        for word in rating.get("class", []):
            if word in RATING_WORDS:
                rating_value = str(RATING_WORDS[word])
                break

    return {
        "name_or_title": title.get_text(strip=True) if title else "",
        "price": price_value,
        "rating": rating_value,
    }


def live_quote(soup: BeautifulSoup, row: dict) -> dict:
    """Find this quote on its listing page and read author and tags."""
    for block in soup.select("div.quote"):
        text = block.select_one("span.text")
        if text is None:
            continue
        stripped = text.get_text(strip=True).strip(CURLY_OPEN + CURLY_CLOSE)
        if stripped[:60] == row["name_or_title"][:60]:
            author = block.select_one("small.author")
            tags = sorted({tag.get_text(strip=True).lower() for tag in block.select("a.tag")})
            return {
                "author": author.get_text(strip=True) if author else "",
                "tags": ";".join(tags),
            }
    return {"error": f"quote not found on {row['source_url']}"}


def main() -> int:
    # --no-spot-check skips the live requests, so the whole verification can
    # run offline (useful for a reviewer with no network, or in CI).
    live = "--no-spot-check" not in sys.argv

    rows, rejected, summary = load()

    print("=" * 108)
    print(f"VERIFYING {config.FINAL_CSV}")
    print(f"run started {summary['run']['started_at']}, "
          f"duration {summary['run']['duration_seconds']}s "
          f"({summary['run']['duration_seconds'] / 60:.1f} min)")
    print("=" * 108)

    check_counts(rows, rejected, summary)
    check_sources(rows)
    check_types(rows)
    check_encoding(rows)
    check_duplicates(rows, summary)
    if live:
        spot_check(rows)
    else:
        print("\n6. LIVE SPOT CHECK - skipped (--no-spot-check)")

    print()
    print("=" * 108)
    print("ALL CHECKS PASSED" if ok_all else "SOME CHECKS FAILED")
    print("=" * 108)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
