"""End-to-end tests for main.py with the scrapers mocked out.

No network and no writes to the real output/ folder: config's paths are
redirected to pytest's tmp_path for every test.

These call main.run(args) rather than main.main(argv), because main() installs
log handlers (and clears existing ones), which would fight with pytest's own
log capture. run() takes the parsed args and does the actual work.
"""

from __future__ import annotations

import codecs
import csv
import json

import pytest

import config
import main
from processing.models import COLUMNS

BOOKS = "Books to Scrape"
QUOTES = "Quotes to Scrape"


# ----------------------------------------------------------------- helpers


def raw_book(title: str, slug: str = "book", price: str = "£51.77", rating: str = "star-rating Three") -> dict:
    """A raw book dict shaped exactly like BooksScraper produces."""
    return {
        "source": BOOKS,
        "title": title,
        "detail_url": f"https://books.toscrape.com/catalogue/{slug}/index.html",
        "price_text": price,
        "rating_classes": rating,
        "listing_page_url": "https://books.toscrape.com/",
        "category": "Fantasy",
        "description": "A blurb. ...more",
        "availability_text": "In stock (14 available)",
    }


def raw_quote(text: str, author: str = "Albert Einstein", tags: list[str] | None = None) -> dict:
    """A raw quote dict shaped exactly like QuotesScraper produces."""
    return {
        "source": QUOTES,
        "text": f"“{text}”",
        "author": author,
        "author_url": "https://quotes.toscrape.com/author/Albert-Einstein",
        "tags": ["change", "thinking"] if tags is None else tags,
        "page_url": "https://quotes.toscrape.com/",
    }


DEFAULT_STATS = {"pages_scraped": 1, "pages_failed": 0, "pages_empty": 0}


def returns(records: list[dict], stats: dict | None = None):
    """Build a replacement scrape() that returns canned records."""

    def _scrape(self, *args, **kwargs):
        self.stats.update(stats or DEFAULT_STATS)
        self.stats["records_collected"] = len(records)
        return list(records)

    return _scrape


def raises(message: str = "simulated scraper crash"):
    """Build a replacement scrape() that blows up."""

    def _scrape(self, *args, **kwargs):
        raise RuntimeError(message)

    return _scrape


@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path, monkeypatch):
    """Point every output path at tmp_path so the real output/ is never touched."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "FINAL_CSV", tmp_path / "output" / "final_dataset.csv")
    monkeypatch.setattr(config, "REJECTED_CSV", tmp_path / "output" / "rejected_records.csv")
    monkeypatch.setattr(config, "SUMMARY_JSON", tmp_path / "output" / "summary_report.json")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "logs" / "scraper.log")
    return tmp_path


def run_pipeline(argv: list[str] | None = None) -> int:
    """Parse args and run, without touching logging configuration."""
    return main.run(main.parse_args(argv or []))


def read_csv(path) -> list[dict]:
    """Read a CSV written by the pipeline (utf-8-sig strips the BOM)."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_summary() -> dict:
    with config.SUMMARY_JSON.open(encoding="utf-8") as handle:
        return json.load(handle)


def mock_both(monkeypatch, books_scrape, quotes_scrape) -> None:
    monkeypatch.setattr(main.BooksScraper, "scrape", books_scrape)
    monkeypatch.setattr(main.QuotesScraper, "scrape", quotes_scrape)


# --------------------------------------------- directories are created


def test_output_and_log_directories_are_created(monkeypatch):
    assert not config.OUTPUT_DIR.exists()
    assert not config.LOG_DIR.exists()

    mock_both(monkeypatch, returns([raw_book("A")]), returns([raw_quote("B")]))
    run_pipeline()

    assert config.OUTPUT_DIR.is_dir()
    assert config.LOG_DIR.is_dir()


def test_all_three_output_files_are_written(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A")]), returns([raw_quote("B")]))
    run_pipeline()

    assert config.FINAL_CSV.exists()
    assert config.REJECTED_CSV.exists()
    assert config.SUMMARY_JSON.exists()


# ------------------------------------------- one source fails, other survives


def test_one_source_raising_does_not_stop_the_other(monkeypatch):
    mock_both(monkeypatch, raises(), returns([raw_quote("survivor")]))
    exit_code = run_pipeline()

    rows = read_csv(config.FINAL_CSV)
    assert len(rows) == 1
    assert rows[0]["source"] == QUOTES
    assert "survivor" in rows[0]["name_or_title"]
    assert exit_code == 0  # one source survived, so the run succeeded


def test_the_crash_is_recorded_in_the_summary(monkeypatch):
    mock_both(monkeypatch, raises("boom"), returns([raw_quote("ok")]))
    run_pipeline()

    summary = read_summary()
    assert summary["run"]["failed_sources"] == [BOOKS]
    assert "boom" in summary["per_source"][BOOKS]["error"]
    assert summary["per_source"][BOOKS]["collected"] == 0
    assert summary["per_source"][QUOTES]["error"] is None
    assert summary["per_source"][QUOTES]["collected"] == 1


def test_books_surviving_a_quotes_crash(monkeypatch):
    """The isolation works in both directions."""
    mock_both(monkeypatch, returns([raw_book("Survivor")]), raises())
    run_pipeline()

    rows = read_csv(config.FINAL_CSV)
    assert len(rows) == 1
    assert rows[0]["source"] == BOOKS
    assert read_summary()["run"]["failed_sources"] == [QUOTES]


# ------------------------------------- a source that collects nothing


def test_source_with_zero_records_is_listed_as_failed(monkeypatch):
    """HTTP 200 on every page but no items: a broken selector, not a crash."""
    empty = returns([], {"pages_scraped": 1, "pages_failed": 0, "pages_empty": 1})
    mock_both(monkeypatch, empty, returns([raw_quote("ok")]))
    exit_code = run_pipeline()

    summary = read_summary()
    assert summary["run"]["failed_sources"] == [BOOKS]
    assert summary["per_source"][BOOKS]["pages_scraped"] == 1   # a page DID succeed
    assert summary["per_source"][BOOKS]["pages_failed"] == 0    # nothing errored
    assert summary["per_source"][BOOKS]["pages_empty"] == 1
    assert summary["per_source"][BOOKS]["error"] is None        # no exception
    assert summary["per_source"][BOOKS]["collected"] == 0
    assert exit_code == 0  # quotes still produced data


def test_zero_record_source_logs_an_error(monkeypatch, caplog):
    empty = returns([], {"pages_scraped": 1, "pages_failed": 0, "pages_empty": 1})
    mock_both(monkeypatch, empty, returns([raw_quote("ok")]))
    with caplog.at_level("ERROR"):
        run_pipeline()
    assert "produced no records" in caplog.text


# ------------------------------------------------- every source fails


def test_every_source_failing_exits_one(monkeypatch):
    mock_both(monkeypatch, raises(), raises())
    assert run_pipeline() == 1


def test_every_source_empty_exits_one(monkeypatch):
    empty = returns([], {"pages_scraped": 1, "pages_failed": 0, "pages_empty": 1})
    mock_both(monkeypatch, empty, empty)
    assert run_pipeline() == 1


def test_the_only_selected_source_failing_exits_one(monkeypatch):
    mock_both(monkeypatch, raises(), returns([raw_quote("never scraped")]))
    assert run_pipeline(["--source", "books"]) == 1


def test_total_failure_still_writes_all_files(monkeypatch):
    """Even a failed run must leave the evidence behind."""
    mock_both(monkeypatch, raises(), raises())
    run_pipeline()

    assert read_csv(config.FINAL_CSV) == []
    summary = read_summary()
    assert summary["csv_rows"] == 0
    assert sorted(summary["run"]["failed_sources"]) == sorted([BOOKS, QUOTES])


# --------------------------------------------------------- validation


def test_invalid_records_go_to_rejected_not_final(monkeypatch):
    """rating 9 and a negative price must be rejected with the right codes."""
    good = raw_book("Good Book", slug="good")
    bad_rating = raw_book("Bad Rating", slug="bad-rating", rating="star-rating Nine")
    bad_price = raw_book("Bad Price", slug="bad-price", price="£-5.00")

    mock_both(monkeypatch, returns([good, bad_rating, bad_price]), returns([]))
    run_pipeline(["--source", "books"])

    final_titles = [row["name_or_title"] for row in read_csv(config.FINAL_CSV)]
    rejected = read_csv(config.REJECTED_CSV)
    rejected_titles = [row["name_or_title"] for row in rejected]

    # "Nine" is not in the rating word map, so it cleans to None and is simply
    # empty rather than invalid; the negative price is the real rejection.
    assert "Good Book" in final_titles
    assert "Bad Price" not in final_titles
    assert "Bad Price" in rejected_titles

    reasons = {row["name_or_title"]: row["rejection_reasons"] for row in rejected}
    assert "invalid_price" in reasons["Bad Price"]


def test_out_of_range_rating_is_rejected(monkeypatch):
    """A rating that survives cleaning but is out of range must be rejected.

    Built by transforming then tampering, because clean_rating can only ever
    produce 1-5 from real markup.
    """
    original = main.transform_one_source

    def tamper(source, raw_records, scraped_at):
        records, failed = original(source, raw_records, scraped_at)
        for record in records:
            record.rating = 9
        return records, failed

    monkeypatch.setattr(main, "transform_one_source", tamper)
    mock_both(monkeypatch, returns([raw_book("Nine Stars")]), returns([]))
    run_pipeline(["--source", "books"])

    assert read_csv(config.FINAL_CSV) == []
    rejected = read_csv(config.REJECTED_CSV)
    assert len(rejected) == 1
    assert "invalid_rating" in rejected[0]["rejection_reasons"]


def test_rejected_reasons_are_counted_in_the_summary(monkeypatch):
    mock_both(
        monkeypatch,
        returns([raw_book("Bad A", slug="a", price="£-1.00"), raw_book("Bad B", slug="b", price="£-2.00")]),
        returns([]),
    )
    run_pipeline(["--source", "books"])

    summary = read_summary()
    assert summary["rejected_by_reason"]["invalid_price"] == 2
    assert summary["per_source"][BOOKS]["rejected"] == 2


def test_rejected_csv_has_a_header_even_when_empty(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("Fine")]), returns([raw_quote("Fine")]))
    run_pipeline()

    with config.REJECTED_CSV.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        remaining = list(reader)

    assert header == COLUMNS + ["rejection_reasons"]
    assert remaining == []  # the honest result on good data


# -------------------------------------------------------- duplicates


DUPLICATE_PAIR = [
    raw_book("The Star-Touched Queen", slug="stq-764", price="£46.02"),
    raw_book("The Star-Touched Queen", slug="stq-642", price="£32.30"),
    raw_book("Something Else", slug="other"),
]


def test_duplicates_are_flagged_by_default(monkeypatch):
    mock_both(monkeypatch, returns(DUPLICATE_PAIR), returns([]))
    run_pipeline(["--source", "books"])

    rows = read_csv(config.FINAL_CSV)
    assert len(rows) == 3  # both copies kept

    stq = [row for row in rows if row["name_or_title"] == "The Star-Touched Queen"]
    assert len(stq) == 2
    assert [row["is_duplicate"] for row in stq] == ["false", "true"]  # first kept
    assert stq[0]["record_id"] == stq[1]["record_id"]  # same item id

    summary = read_summary()
    assert summary["duplicates"]["detected"] == 1
    assert summary["duplicates"]["action"] == "flagged"
    assert summary["csv_rows"] == 3
    assert summary["final_record_count"] == 2


def test_drop_duplicates_removes_the_row(monkeypatch):
    mock_both(monkeypatch, returns(DUPLICATE_PAIR), returns([]))
    run_pipeline(["--source", "books", "--drop-duplicates"])

    rows = read_csv(config.FINAL_CSV)
    assert len(rows) == 2  # the second copy is gone
    assert [row["is_duplicate"] for row in rows] == ["false", "false"]

    summary = read_summary()
    assert summary["duplicates"]["action"] == "removed"
    assert summary["csv_rows"] == 2
    assert summary["final_record_count"] == 2


def test_duplicate_group_is_described_in_the_summary(monkeypatch):
    mock_both(monkeypatch, returns(DUPLICATE_PAIR), returns([]))
    run_pipeline(["--source", "books"])

    groups = read_summary()["duplicates"]["groups"]
    assert len(groups) == 1
    assert groups[0]["title"] == "The Star-Touched Queen"
    assert groups[0]["copies"] == 2
    assert len(groups[0]["source_urls"]) == 2
    assert all("stq-" in url for url in groups[0]["source_urls"])


def test_title_variants_are_one_duplicate(monkeypatch):
    """Case and punctuation differences collapse to one item."""
    variants = [
        raw_book("Example Book Title", slug="a"),
        raw_book("  example book title  ", slug="b"),
        raw_book("EXAMPLE BOOK TITLE!", slug="c"),
    ]
    mock_both(monkeypatch, returns(variants), returns([]))
    run_pipeline(["--source", "books"])

    summary = read_summary()
    assert summary["duplicates"]["detected"] == 2
    assert summary["final_record_count"] == 1


def test_same_text_across_sources_is_not_a_duplicate(monkeypatch):
    mock_both(
        monkeypatch,
        returns([raw_book("Identical Text")]),
        returns([raw_quote("Identical Text", author="Identical Text")]),
    )
    run_pipeline()
    assert read_summary()["duplicates"]["detected"] == 0


# ------------------------------------------------------ reconciliation


def test_reconciliation_is_ok_on_a_clean_run(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A", slug="a"), raw_book("B", slug="b")]), returns([raw_quote("C")]))
    run_pipeline()

    rec = read_summary()["reconciliation"]
    assert rec["ok"] is True
    assert all(block["ok"] for block in rec.values() if isinstance(block, dict))


def test_reconciliation_arithmetic_with_duplicates_and_rejections(monkeypatch):
    records = DUPLICATE_PAIR + [raw_book("Bad", slug="bad", price="£-9.00")]
    mock_both(monkeypatch, returns(records), returns([]))
    run_pipeline(["--source", "books"])

    summary = read_summary()
    rec = summary["reconciliation"]

    # 4 collected - 0 transform_failed - 1 rejected = 3 after validation
    assert rec["collected_minus_transform_failed_minus_rejected"]["after_validation"] == 3
    # 3 after validation - 1 duplicate = 2 unique
    assert rec["after_validation_minus_duplicates"]["final_unique"] == 2
    # flag mode keeps all 3 rows in the file
    assert summary["csv_rows"] == 3
    assert summary["final_record_count"] == 2
    assert rec["ok"] is True


def test_reconciliation_matches_the_actual_csv_row_count(monkeypatch):
    mock_both(monkeypatch, returns(DUPLICATE_PAIR), returns([raw_quote("Q")]))
    run_pipeline()

    summary = read_summary()
    assert summary["csv_rows"] == len(read_csv(config.FINAL_CSV))


def test_csv_rows_and_final_record_count_are_separate_fields(monkeypatch):
    """In flag mode they differ, which is why they are two fields."""
    mock_both(monkeypatch, returns(DUPLICATE_PAIR), returns([]))
    run_pipeline(["--source", "books"])

    summary = read_summary()
    assert summary["csv_rows"] == 3
    assert summary["final_record_count"] == 2
    assert summary["csv_rows"] != summary["final_record_count"]


# ---------------------------------------------------------- CSV format


def test_csv_column_order_is_exactly_models_columns(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A")]), returns([raw_quote("B")]))
    run_pipeline()

    with config.FINAL_CSV.open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == COLUMNS


def test_none_is_written_as_an_empty_cell(monkeypatch):
    """A quote has no price, rating or category: those cells must be empty."""
    mock_both(monkeypatch, returns([]), returns([raw_quote("Q", tags=[])]))
    run_pipeline(["--source", "quotes"])

    row = read_csv(config.FINAL_CSV)[0]
    for column in ("category", "price", "currency", "availability", "rating", "description", "tags"):
        assert row[column] == "", f"{column} should be empty, got {row[column]!r}"
    # and never the string "None"
    assert "None" not in row.values()


def test_price_is_written_with_two_decimals(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("Round", price="£51.80")]), returns([]))
    run_pipeline(["--source", "books"])
    assert read_csv(config.FINAL_CSV)[0]["price"] == "51.80"


def test_is_duplicate_is_written_lowercase(monkeypatch):
    mock_both(monkeypatch, returns(DUPLICATE_PAIR), returns([]))
    run_pipeline(["--source", "books"])

    values = {row["is_duplicate"] for row in read_csv(config.FINAL_CSV)}
    assert values == {"true", "false"}
    assert "True" not in values and "False" not in values


def test_csv_is_written_with_a_utf8_bom(monkeypatch):
    """utf-8-sig writes a BOM so Excel on Windows reads the file as UTF-8."""
    mock_both(monkeypatch, returns([raw_book("A")]), returns([]))
    run_pipeline(["--source", "books"])

    head = config.FINAL_CSV.read_bytes()[:3]
    assert head == codecs.BOM_UTF8


def test_pound_sign_survives_the_round_trip(monkeypatch):
    """The price is numeric in the CSV, and no mojibake appears anywhere."""
    mock_both(monkeypatch, returns([raw_book("A", price="£51.77")]), returns([]))
    run_pipeline(["--source", "books"])

    row = read_csv(config.FINAL_CSV)[0]
    assert row["price"] == "51.77"
    assert "Â" not in config.FINAL_CSV.read_text(encoding="utf-8-sig")


def test_quote_text_has_no_curly_quotes_in_the_csv(monkeypatch):
    mock_both(monkeypatch, returns([]), returns([raw_quote("Plain text")]))
    run_pipeline(["--source", "quotes"])

    text = read_csv(config.FINAL_CSV)[0]["name_or_title"]
    assert text == "Plain text"
    assert "“" not in text and "”" not in text


def test_every_row_has_a_record_id(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A", slug="a"), raw_book("B", slug="b")]), returns([raw_quote("C")]))
    run_pipeline()

    for row in read_csv(config.FINAL_CSV):
        assert len(row["record_id"]) == 64  # SHA-256 hex


def test_all_rows_share_one_scraped_at(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A", slug="a"), raw_book("B", slug="b")]), returns([raw_quote("C")]))
    run_pipeline()

    stamps = {row["scraped_at"] for row in read_csv(config.FINAL_CSV)}
    assert len(stamps) == 1
    assert stamps.pop().endswith("Z")


# ------------------------------------------------------- transform_failed


def test_an_unmappable_record_is_counted_not_fatal(monkeypatch):
    """A raw record that cannot be transformed must not lose the others."""
    original = main.book_to_record
    calls = {"n": 0}

    def sometimes_fails(raw, scraped_at):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("cannot map this one")
        return original(raw, scraped_at)

    monkeypatch.setattr(main, "book_to_record", sometimes_fails)
    mock_both(
        monkeypatch,
        returns([raw_book("One", slug="a"), raw_book("Two", slug="b"), raw_book("Three", slug="c")]),
        returns([]),
    )
    run_pipeline(["--source", "books"])

    summary = read_summary()
    assert summary["per_source"][BOOKS]["collected"] == 3
    assert summary["per_source"][BOOKS]["transform_failed"] == 1
    assert summary["per_source"][BOOKS]["after_cleaning"] == 2
    assert summary["csv_rows"] == 2
    assert summary["reconciliation"]["ok"] is True


# ------------------------------------------------------------ CLI / args


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_argparse_rejects_non_positive_max_pages(value):
    with pytest.raises(SystemExit):
        main.parse_args(["--max-pages", value])


@pytest.mark.parametrize("value", ["1", "2", "50"])
def test_argparse_accepts_positive_max_pages(value):
    assert main.parse_args(["--max-pages", value]).max_pages == int(value)


def test_max_pages_defaults_to_none():
    assert main.parse_args([]).max_pages is None


def test_argparse_rejects_an_unknown_source():
    with pytest.raises(SystemExit):
        main.parse_args(["--source", "nonsense"])


def test_source_choice_selects_the_right_sources():
    assert main.selected_sources("books") == [BOOKS]
    assert main.selected_sources("quotes") == [QUOTES]
    assert main.selected_sources("all") == [BOOKS, QUOTES]


def test_source_option_limits_the_summary(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A")]), returns([raw_quote("B")]))
    run_pipeline(["--source", "quotes"])

    summary = read_summary()
    assert list(summary["per_source"]) == [QUOTES]


def test_cli_options_are_recorded_in_the_summary(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A")]), returns([]))
    run_pipeline(["--source", "books", "--max-pages", "3", "--delay", "0.1", "--skip-details"])

    options = read_summary()["run"]["cli_options"]
    assert options["source"] == "books"
    assert options["max_pages"] == 3
    assert options["delay"] == 0.1
    assert options["skip_details"] is True
    assert options["drop_duplicates"] is False


def test_delay_default_comes_from_config():
    assert main.parse_args([]).delay == config.REQUEST_DELAY


# -------------------------------------------------------- data quality


def test_data_quality_counts_are_reported_per_source(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A")]), returns([raw_quote("B")]))
    run_pipeline()

    quality = read_summary()["data_quality"]["empty_values_per_column"]
    assert set(quality) == {"all", BOOKS, QUOTES}
    # a book has no author; a quote has no price
    assert quality[BOOKS]["author"] == 1
    assert quality[BOOKS]["price"] == 0
    assert quality[QUOTES]["price"] == 1
    assert quality[QUOTES]["author"] == 0


def test_summary_has_every_required_key(monkeypatch):
    mock_both(monkeypatch, returns([raw_book("A")]), returns([raw_quote("B")]))
    run_pipeline()

    summary = read_summary()
    for key in ("run", "per_source", "rejected_by_reason", "duplicates",
                "csv_rows", "final_record_count", "data_quality", "reconciliation"):
        assert key in summary, f"missing {key}"
    for key in ("started_at", "finished_at", "duration_seconds", "cli_options", "failed_sources"):
        assert key in summary["run"], f"missing run.{key}"
    for key in ("pages_scraped", "pages_failed", "pages_empty", "requests_made",
                "requests_failed", "detail_pages_failed", "collected",
                "transform_failed", "after_cleaning", "rejected", "duplicates",
                "final_unique", "error"):
        assert key in summary["per_source"][BOOKS], f"missing per_source.{key}"
