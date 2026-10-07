# Multi-Source Web Scraping & Data Consolidation

## 1. Project overview

This project collects data from two public practice websites, cleans and
standardizes it into one shared schema, validates it, detects duplicates, and
writes a single consolidated dataset plus a machine-readable run report. One
command runs the whole thing. The two sources have very different shapes — one
needs a second request per record to get all its fields, the other does not —
so the main design problem is mapping both onto one row format without
inventing values for fields a source cannot provide.

```
Books to Scrape  ─┐
                  ├─> Scrape ─> Clean ─> Validate ─> Deduplicate ─> Consolidate ─> Output
Quotes to Scrape ─┘
```

| Layer | Folder | Responsibility |
|---|---|---|
| Scraping | `scrapers/` | Everything that touches the network |
| Processing | `processing/` | Pure data transformation, no I/O |
| Orchestration | `main.py` | CLI, logging, running the stages in order |

Nothing in `processing/` makes a request, and nothing in `scrapers/` cleans a
value. That separation is why the processing layer can be unit-tested with
literal inputs and the parsers can be tested against saved HTML offline.

## 2. Python version

Developed and tested on **Python 3.12.10** (Windows 11).

The code uses only syntax available from Python 3.10 onwards (`X | None` type
hints, `dataclass(kw_only=True)`), so it should run on 3.10–3.13, but **3.12.10
is the only version it has actually been run on**. If you need a guarantee, use
3.12.

## 3. Installation / setup

**Windows (PowerShell)**

```powershell
cd scraping_assignment
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**macOS / Linux**

```bash
cd scraping_assignment
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Check it worked:

```
python -c "import requests, bs4, lxml, pytest; print('ok')"
```

`output/` and `logs/` are created automatically by the program if they are
missing, so there is nothing else to set up.

## 4. Dependencies

Four direct dependencies, pinned in `requirements.txt`:

| Package | Version | Why it is needed |
|---|---|---|
| `requests` | 2.34.2 | HTTP client. Used for its `Session` (connection pooling across ~1,060 requests) and its retry adapter. |
| `beautifulsoup4` | 4.15.0 | HTML parsing and CSS-selector queries. `select_one` returns `None` for a missing element rather than raising, which is the basis of the "never crash on missing data" approach. |
| `lxml` | 6.1.3 | The parser backend BeautifulSoup uses. Faster and more tolerant of imperfect markup than the standard library's `html.parser`. |
| `pytest` | 9.1.1 | Test runner. Used for fixtures, parametrized tests, `monkeypatch` and `tmp_path`. |

Only direct dependencies are pinned; pip resolves the ten transitive packages
(`urllib3`, `soupsieve`, `certifi` and so on). `urllib3` is used directly for
its `Retry` class, but it arrives as a dependency of `requests`, so pinning it
separately would risk a conflict with whatever `requests` requires.

Both sites serve plain server-rendered HTML — verified with view-source, not
just the browser's inspector — so no browser automation is needed. Selenium or
Playwright would add startup cost and complexity for no benefit.

## 5. How to run

```
python main.py
```

That scrapes both sources completely, writes three files to `output/` and a log
to `logs/scraper.log`, and exits 0.

**Expected run time: about 19 minutes.** The last full run took 1,131 seconds
(18.9 minutes) for 1,060 requests. The cost is almost entirely the 1,000 book
detail pages, at a deliberate 0.5-second delay each.

### Command-line options

| Option | Default | Effect |
|---|---|---|
| `--source {books,quotes,all}` | `all` | Which site(s) to scrape |
| `--max-pages N` | no limit | Stop after N listing pages per source. Must be 1 or more. |
| `--delay SECONDS` | `0.5` | Pause between requests |
| `--skip-details` | off | Do not open book detail pages |
| `--drop-duplicates` | off | Remove duplicate rows instead of flagging them |

```bash
python main.py --max-pages 2          # ~50s: 40 books + 20 quotes, for a quick check
python main.py --source quotes        # ~9s: 100 quotes, 10 requests
python main.py --skip-details         # ~1 min: all 1,000 books, but category,
                                      #   description and availability stay empty
python main.py --drop-duplicates      # 1,099 rows instead of 1,100
python main.py --delay 1.0            # slower, gentler on the servers
python main.py --help                 # full help text
```

`--skip-details` drops the run from ~1,060 requests to 60, which is why it
takes about a minute instead of nineteen. Use it when you want to check that
pagination and the listing parser work without waiting.

### Running the tests

```
pytest
```

**285 tests, about 2 seconds, entirely offline.** `tests/conftest.py` blocks
socket connections for the whole suite, so a test that tried to reach the
network would fail rather than silently pass.

### Verifying the output independently

```
python scripts/verify_output.py                   # includes a live spot check
python scripts/verify_output.py --no-spot-check   # fully offline
```

This re-reads `output/final_dataset.csv` with the standard library's `csv`
module and re-derives every count, type and range **without importing the
pipeline's own counting code**, so a bug in `main.py` cannot hide by agreeing
with itself. With the spot check on, it also re-fetches five rows from the live
sites and compares them field by field.

See `scripts/README.md` for the other two development scripts. Note that
`scripts/try_failure.py` overwrites `output/`, because it runs the real
pipeline.

## 6. Source exploration

Both sources were inspected with Chrome DevTools (Elements panel, `Ctrl+F` with
CSS selectors) and then confirmed programmatically. Every selector below has
been checked against the live site.

### Books to Scrape — <https://books.toscrape.com/>

A server-rendered catalogue. The landing page is page 1 of the listing; each
listing page holds exactly 20 books as `article.product_pod` cards. Two fields
exist only on a book's own detail page, so a full run makes 50 listing requests
plus 1,000 detail requests.

| Field | Location | Selector |
|---|---|---|
| Title (full) | listing card | `h3 > a` → **`title` attribute** |
| Price | listing card | `p.price_color` (e.g. `£51.77`) |
| Rating | listing card | `p.star-rating` → **CSS class word** |
| Detail URL | listing card | `h3 > a[href]`, relative |
| Category | detail page | `ul.breadcrumb li:nth-of-type(3) a` |
| Description | detail page | `#product_description + p` |
| Availability | detail page | `p.availability` (e.g. `In stock (22 available)`) |

**Tricky parts**

- **Truncated titles.** The visible link text is cut off (`A Light in the ...`).
  The full title is only in the `title` **attribute**. Reading `.get_text()`
  here would silently corrupt every record.
- **`£` encoding.** The server's HTTP header declares `charset=ISO-8859-1`, but
  the bytes are UTF-8. `requests` trusts the header, so `£` decodes as two
  characters and you get `Â£51.77`. Setting `response.encoding = "utf-8"`
  **before** reading `response.text` fixes it; afterwards is too late.
- **Rating is presentation, not content.** There is no numeric rating in the
  markup at all — the star count exists only as a CSS class word (`One`…`Five`)
  and must be mapped to 1–5. The word is matched against a lookup map rather
  than read by class position, because attribute order is not guaranteed.
- **Relative links change shape after page 1.** On the site root the next-page
  href is `catalogue/page-2.html`; from inside `catalogue/` it is just
  `page-3.html`. Detail hrefs shift the same way. Joining against the **current
  page URL** resolves both; joining against a fixed base would 404 from page 3.
- **The `...more` suffix.** **943 of the 998 descriptions present (94%)** end
  with the literal text `...more`, which is a leftover "read more" link from the
  page the site was generated from. It is stripped during cleaning. Measured
  across all 1,000 books, not sampled.
- **Two books have no description at all.** `#product_description + p` returns
  nothing for:
  - *The Bridge to Consciousness: I'm Writing the Bridge Between Science and
    Our Old and New Beliefs.* (category `Default`)
  - *Alice in Wonderland (Alice's Adventures in Wonderland #1)* (category
    `Classics`)

  Both are kept as records with an empty description. Two in a thousand is rare
  enough that a sampling check would miss it, which is why the `None` case had
  to be designed in rather than discovered.
- **Duplicate titles exist in the catalogue.** See section 11.
- **Two odd but genuine categories.** `Default` (152 books) and `Add a comment`
  (67 books) look like scraping errors but are real: the site's own sidebar
  lists exactly 50 categories including both, and the scrape found exactly those
  50.

### Quotes to Scrape — <https://quotes.toscrape.com/>

Also server-rendered, and much flatter. Each page holds exactly 10 quotes as
`div.quote` blocks, and every field is on the listing page, so there is no
detail request. The site also publishes `/js/` and `/login` variants; both are
avoided, since `/js/` renders its quotes with JavaScript that `requests` cannot
execute.

| Field | Selector |
|---|---|
| Quote text | `span.text` |
| Author | `small.author` |
| Author URL | `a[href^="/author/"]`, root-relative |
| Tags | `a.tag` (zero or more) |

**Tricky parts**

- **Curly quotation marks.** `span.text` is wrapped in typographic quotes
  (`“ … ”`), not ASCII `"`. They are stripped so the stored text is
  the quote itself. This also matters for duplicate detection.
- **Zero-tag quotes.** `a.tag` can match nothing. `select()` returns an empty
  list rather than raising, so three quotes (by J.K. Rowling, Marilyn Monroe and
  Ayn Rand) legitimately have no tags and are stored with an empty `tags` field.
- **Root-relative author URLs.** `/author/Albert-Einstein` begins with `/`, so
  `urljoin` resolves it against the site root — correctly, and differently from
  the Books site's path-relative hrefs. Same function, two relative-URL forms.
- **Pages past the end return HTTP 200, not 404.** `…/page/99999/` responds 200
  with zero `div.quote` elements. A scraper that only treats HTTP errors as
  failures would record that as a successful page with no data. This is why the
  code logs a warning when a page yields no items, and why a source that
  collects nothing is treated as failed (section 12).

### Key differences

| | Books to Scrape | Quotes to Scrape |
|---|---|---|
| Records | 1,000 over 50 pages | 100 over 10 pages |
| Items per page | 20 | 10 |
| Detail page needed | **Yes** — category and description | No |
| Requests for a full run | 1,050 | 10 |
| Relative URL style | path-relative, shape changes after page 1 | root-relative |
| Encoding pitfall | `£` mis-declared as ISO-8859-1 | curly quotes in the text |
| Fields contributed | price, currency, rating, availability, category, description | author, author URL, tags |

The two sources overlap only in `record_id`, `source`, `source_url`,
`name_or_title`, `scraped_at` and `is_duplicate`. Every other column is filled
by exactly one source and left empty for the other.

## 7. How pagination works

Both sources use the same rule, and no page numbers are hard-coded anywhere:

1. Start at the source's base URL.
2. Parse the page.
3. Look for `li.next > a`. If it is absent, stop.
4. Otherwise resolve its `href` with `urljoin(current_page_url, href)` and
   repeat.

The loop condition *is* the stop condition: `_next_page_url()` returns `None`
when there is no next link, which ends the `while` loop. Books page 50 and
Quotes page 10 both have no `li.next`, so the walk terminates naturally at
exactly 1,000 and 100 records. If the sites gained a page tomorrow, the code
would follow it with no change.

**Why `urljoin` uses the current page URL.** The Books next-href changes shape
after page 1:

| Found on | href | Joined against the current URL |
|---|---|---|
| `https://books.toscrape.com/` | `catalogue/page-2.html` | `…/catalogue/page-2.html` |
| `…/catalogue/page-2.html` | `page-3.html` | `…/catalogue/page-3.html` |

Joining `page-3.html` against the site root instead would give
`https://books.toscrape.com/page-3.html`, a 404, and the scraper would stop
after two pages with 40 books instead of 1,000.

`--max-pages N` adds an early exit for quick runs. It is checked *before* the
request, so `--max-pages 2` makes exactly two listing requests. Values below 1
are rejected by the argument parser.

## 8. Data model

One row shape covers both sources. `processing/models.py` defines it as a
dataclass, and `COLUMNS` is derived from that dataclass with
`[f.name for f in fields(Record)]` — so the CSV header and the dataclass can
never drift apart.

| # | Column | Type | Books | Quotes |
|---|---|---|---|---|
| 1 | `record_id` | str | fingerprint hash | fingerprint hash |
| 2 | `source` | str | `Books to Scrape` | `Quotes to Scrape` |
| 3 | `source_url` | str | book detail page URL | listing page URL |
| 4 | `name_or_title` | str | full book title | quote text, curly quotes removed |
| 5 | `category` | str | breadcrumb category | *empty* |
| 6 | `price` | float | e.g. `51.77` | *empty* |
| 7 | `currency` | str | `GBP` | *empty* |
| 8 | `availability` | int | stock count, e.g. `22` | *empty* |
| 9 | `rating` | int | 1–5 | *empty* |
| 10 | `author` | str | *empty* | author name |
| 11 | `author_url` | str | *empty* | absolute author page URL |
| 12 | `tags` | str | *empty* | `change;deep-thoughts;thinking` |
| 13 | `description` | str | detail-page text, may be empty | *empty* |
| 14 | `scraped_at` | str | UTC ISO timestamp | UTC ISO timestamp |
| 15 | `is_duplicate` | bool | `false` unless duplicate | `false` unless duplicate |

A field a source cannot provide is **empty**, never zero, never `"N/A"`, never a
guess. All 1,100 rows in a run share one `scraped_at`, so a run can be
identified as a unit.

### `record_id` is an item identifier, not a row identifier

`record_id` is the deduplication fingerprint, so **duplicates deliberately
share the same `record_id`**. It identifies the *item*, not the *row*. This is
intentional — it lets copies be grouped and audited together — but it means:

> **The unique key is `record_id` where `is_duplicate = false`.**

If you load the CSV into a database with `record_id` as a primary key, the
import will fail on the one duplicate pair. Filter to `is_duplicate = false`
first, or use `(record_id, source_url)`. Verified on the real output: the 1,099
non-duplicate rows have 1,099 distinct `record_id` values.

## 9. Cleaning approach

`processing/cleaning.py` holds nine pure functions — no network, no files, no
shared state. Every one accepts `None` and returns `None` instead of raising,
because the scrapers deliberately produce `None` for any element that was
missing. That property is what makes a missing field impossible to crash on.

| Function | Rule |
|---|---|
| `clean_text` | Replace `\xa0`, collapse all whitespace runs to single spaces, strip. Returns `None` if nothing is left. Does **not** lowercase — display casing is preserved. |
| `strip_quotes` | Remove curly or straight quote marks that wrap the whole string, from the ends only. Internal quotes are untouched. |
| `clean_price` | `£51.77` → `51.77`, rounded to 2 decimals. Skips any currency symbol or mojibake prefix, strips thousands commas. Keeps a minus sign so a negative price survives to be rejected by validation. |
| `clean_rating` | `star-rating Three` → `3` by matching the word against a map, never by class position. |
| `clean_availability` | `In stock (22 available)` → `22`. Out-of-stock wording → `0`. `In stock` with no number → `None`, because an unknown count is not zero. |
| `clean_tags` | Strip, lowercase, drop blanks, deduplicate, sort, join with `;`. Empty list → `None`. |
| `normalize_url` | Join to a base if relative, then require an `http`/`https` scheme and a host. Rejects `javascript:`, `mailto:` and bare paths. |
| `clean_description` | `clean_text`, then remove a trailing `...more`. |
| `utc_now_iso` | `2026-10-07T10:15:00Z`. Uses `datetime.now(timezone.utc)`; `utcnow()` is deprecated and returns a naive value. |

`processing/transform.py` maps a raw dict to a `Record` using only these
functions. It does no string manipulation of its own, reads every field with
`.get()` so a missing key cannot raise, and sets `currency` to `GBP` **only
when a price actually parsed**, so the pair is never half-populated.

## 10. Validation approach

`validate_record(record)` returns a list of problem codes; an empty list means
valid. It never repairs and never guesses. Records with problems are excluded
from `final_dataset.csv` and written to `rejected_records.csv` with their
reasons, so nothing disappears silently.

| Code | Meaning |
|---|---|
| `unknown_source` | Not exactly one of the two expected source names |
| `missing_name` | `name_or_title` empty or whitespace |
| `invalid_url` | `source_url` missing, or not `http`/`https` with a host |
| `invalid_author_url` | `author_url` present but not a valid URL |
| `invalid_price` | Present but not a real number, or NaN, or infinite, or `< 0` |
| `price_currency_mismatch` | A price with no currency, or a currency with no price |
| `invalid_rating` | Present but not an `int` in 1–5 |
| `invalid_availability` | Present but not an `int` `>= 0` |
| `missing_author` | Quotes only: no author |
| `missing_scraped_at` | No run timestamp |

Problems accumulate — the function does not return early — so a record with two
faults reports both codes and can be fixed in one pass.

Two Python traps are handled explicitly:

- **`bool` is a subclass of `int`**, so `isinstance(True, int)` is `True` and
  `1 <= True <= 5` evaluates to `True`. A rating of `True` would pass a naive
  range check and reach the CSV. The code rejects `bool` before testing the
  range.
- **`float("nan") < 0` is `False`**, and so is `> 0`. A naive "less than zero"
  check passes NaN. `math.isnan()` is the only reliable test.

### Honest note: five of these ten cannot be triggered by site data

The transform layer makes them structurally impossible:

| Code | Why it cannot fire from the sites |
|---|---|
| `unknown_source` | `transform.py` sets `source` from a module constant |
| `price_currency_mismatch` | `currency` is set from `price`, so they are always consistent |
| `invalid_rating` | `clean_rating` can only ever return 1–5 or `None` |
| `invalid_availability` | `clean_availability` can only return `>= 0` or `None` |
| `missing_scraped_at` | The timestamp is passed in once per run |

They are guards against a **future code change**, not against the websites —
which is a legitimate reason to keep them, but worth stating plainly rather than
implying the pipeline screens dirty input it never actually receives. It is also
the reason the real run rejects **0 records**: that is structural, not luck, so
`rejected_records.csv` in this submission contains a header and no data rows.
That is the true result, not a missing feature. The rejection path itself is
proven by tests that construct invalid records directly (see section 17).

## 11. Deduplication approach

### The exact rule, as implemented

```
normalize each identity field:
    NFKC Unicode normalization
    every Unicode punctuation character (category P*) -> a space
    lowercase
    collapse whitespace runs to single spaces
join the normalized fields with \x1f (ASCII unit separator)
SHA-256 the result, store the hex digest as record_id
```

Identity fields per source:

- **Books:** `source` + `title`
- **Quotes:** `source` + `author` + full quote text

So `"Example Book Title"`, `" Example Book Title "` and `"EXAMPLE BOOK TITLE"`
all produce one fingerprint, and `"Hello, World!"` matches `"hello world"`.
Punctuation becomes a **space** rather than being deleted, so that
`"Hello, World!"` and `"hello world"` agree; deleting would give `"helloworld"`,
which would not match.

`\x1f` is used as the field separator because it cannot occur in page text. A
plain character like `|` is a Unicode *symbol*, not punctuation, so it would
survive normalization and could shift a field boundary — without a separator,
author `"AB"` + text `"C"` and author `"A"` + text `"BC"` would hash identically.

`mark_duplicates()` walks the records in order, sets `record_id` on every one,
leaves the **first** occurrence of a fingerprint with `is_duplicate = false`,
and sets every later one to `true`. Input order decides which copy is kept, so
the result is stable for a stable input.

### Why flag instead of delete

Deleting a row destroys the evidence that there was ever anything to decide.
Flagging keeps both copies visible, keeps the counts auditable
(`1,100 rows − 1 duplicate = 1,099 unique`), and leaves the judgement to whoever
reads the data. `--drop-duplicates` removes them if you want a deduplicated
file, so the default costs nothing.

### The one real duplicate: The Star-Touched Queen

The live catalogue contains exactly one duplicate, and it is a genuine edge case
rather than a scraping error:

| | Copy 1 | Copy 2 |
|---|---|---|
| Title | The Star-Touched Queen | The Star-Touched Queen |
| Price | **£46.02** | **£32.30** |
| Stock | 14 | 12 |
| Rating | 5 | 5 |
| Category | Fantasy | Fantasy |
| URL | `…/the-star-touched-queen_764/…` | `…/the-star-touched-queen_642/…` |
| `is_duplicate` | `false` | `true` |

They are the **same work listed twice as two separate products**, not two
different books that happen to share a title. Both descriptions open with the
same sentence and describe the same plot and character (similarity 0.83 by
`difflib`), differing mainly in typography (`'` vs `’`, `...` vs `…`). The
longer one has an extra closing line — *"a novel that no **listener** will soon
forget"* — which is audiobook copy, so the two are most likely different
formats or editions.

This means the fingerprint rule answers *"how many distinct works?"* (1,099),
not *"how many products are for sale?"* (1,100). Both are reasonable questions;
the rule picks one and the flag preserves the other.

**What `--drop-duplicates` would lose:** the `£32.30` listing. The first
occurrence is kept, which happens to be the £46.02 copy, so the cheaper edition
is the one discarded. That is a concrete argument for flagging being the
default.

## 12. Error handling

| Failure | Behaviour |
|---|---|
| Connection error / timeout / 5xx / 429 | Retry with backoff; after the final retry, log an ERROR and return `None` |
| 404 or other 4xx | No retry; log an ERROR and skip |
| Listing page fails | Log an ERROR, stop that source, keep the records already collected, continue with the other source |
| Detail page fails | Keep the book with category, description and availability empty; log a WARNING |
| Missing HTML element | `select_one` returns `None` → the field stays empty; never crashes |
| One record fails to parse | `try/except` around that record; log a WARNING; continue |
| One record fails to transform | Counted as `transform_failed`; log a WARNING; continue |
| Invalid value after cleaning | Validation rejects the record with a reason code; counted in the summary |
| A whole source crashes | Caught in `main.py`, logged with a traceback, recorded in the summary; the run continues |

Retries are configured once on the `requests.Session`: `total=3`,
`backoff_factor=1.0`, `status_forcelist=[429, 500, 502, 503, 504]`, GET only,
and a 10-second timeout on every request. Only the listed status codes are
retried — a 404 will not exist in four seconds either, so retrying it wastes
time.

`fetch(url)` cannot raise. It catches `requests.RequestException`, the base
class covering connection errors, timeouts, HTTP errors and exhausted retries,
logs an ERROR naming the URL and the reason, and returns `None`. The politeness
delay is in a `finally` block, so a failing server is not hammered at exactly
the moment it is struggling.

This was exercised for real: the full catalogue scan during development hit one
`RemoteDisconnected` on a detail page. The retry succeeded, no ERROR was logged
and no record was lost.

### A source counts as failed when it collected 0 records

The exit code is 0 unless **every** selected source failed. A source is
considered failed when it produced no records — whatever the cause:

```python
if not raw:
    failed_sources.append(source)
```

This measures the **outcome, not the mechanism**. Three different causes all
mean "this source contributed nothing":

| Cause | `pages_scraped` | `pages_failed` | `error` |
|---|---|---|---|
| The scraper raised | 0 | 0 | set |
| Every page request failed | 0 | > 0 | none |
| Pages returned HTTP 200 with no items | > 0 | **0** | **none** |

The third is the dangerous one, because nothing errored: a broken selector
serves 200s all day and quietly yields zero records. An earlier version of this
check tested whether any page request had failed, and waved that case through.
Checking the outcome catches all three with one condition.

`--max-pages 0` would also collect nothing without anything being wrong, so the
argument parser rejects values below 1 and the rule stays unambiguous.

## 13. Output description

All numbers below are from the `summary_report.json` in this submission, for a
run that started `2026-10-06T22:02:41Z` and took **1,131.25 seconds (18.9
minutes)**.

### `output/final_dataset.csv` — 1.7 MB, 1,100 data rows

The consolidated dataset. 15 columns in the order given in section 8. Written
as **`utf-8-sig`** — UTF-8 with a byte-order mark — because Excel on Windows
otherwise reads a CSV in the local code page and displays `£` as `Â£`. The BOM
is the signal that makes Excel pick UTF-8. Python's `csv` module reads it back
cleanly with the same encoding.

Formatting: empty values are empty cells; prices always have two decimals
(`51.80`, not `51.8`); `is_duplicate` is written lowercase `true`/`false`.

| | Value |
|---|---|
| Rows in the file | **1,100** |
| Unique items (`is_duplicate = false`) | **1,099** |
| Duplicates flagged | **1** |
| Books | **1,000** |
| Quotes | **100** |

### `output/rejected_records.csv` — header only

The same 15 columns plus a `rejection_reasons` column holding the codes joined
with `;`. **This run rejected 0 records, so the file contains a header and no
data rows.** The header is always written, so the file is valid CSV either way.
See section 10 for why zero is the expected, structural result.

### `output/summary_report.json` — 3.5 KB

The machine-readable run report:

- `run` — start and finish timestamps, duration, the exact CLI options used,
  and `failed_sources` (empty for this run)
- `per_source` — for each source: `pages_scraped`, `pages_failed`,
  `pages_empty`, `requests_made`, `requests_failed`, `detail_pages_failed`,
  `collected`, `transform_failed`, `after_cleaning`, `rejected`, `duplicates`,
  `final_unique`, `error`
- `rejected_by_reason` — `{}` for this run
- `duplicates` — `detected: 1`, `action: "flagged"`, and a `groups` list naming
  the duplicated title with every `source_url` in the group
- `csv_rows` (1,100) and `final_record_count` (1,099) — deliberately **two
  separate fields**, because in flagging mode they differ
- `data_quality.empty_values_per_column` — empty-value counts per column,
  reported for all records and for each source separately
- `reconciliation` — see below

For this run:

| Source | Pages | Requests | Collected | Rejected | Duplicates | Final unique |
|---|---|---|---|---|---|---|
| Books to Scrape | 50 | 1,050 | 1,000 | 0 | 1 | 999 |
| Quotes to Scrape | 10 | 10 | 100 | 0 | 0 | 100 |

The empty-value counts are a useful cross-check: `description` is empty in
**102** records, which is the 100 quotes plus the 2 books that genuinely have no
description; `tags` is empty in **1,003**, which is the 1,000 books plus the 3
zero-tag quotes.

### The reconciliation block

The summary states its own arithmetic and whether it holds, so the numbers check
themselves:

```
collected − transform_failed − rejected = after_validation    1100 − 0 − 0 = 1100
after_validation − duplicates           = final_unique        1100 − 1     = 1099
csv_rows                                = after_validation    1100 == 1100    (flagging mode)
                                          or final_unique                     (--drop-duplicates)
ok: true
```

If any of these did not hold, the run would log an ERROR saying so. All three
are `true` in this submission.

### `logs/scraper.log` — 83 lines

The run log, overwritten on each run so it always describes exactly one run. One
INFO line per page with its URL and item count, plus start and end banners
carrying the CLI options, the duration and the headline counts. This run
contains **0 WARNING and 0 ERROR lines**.

## 14. Assumptions

- **A normalized title identifies a book.** True for 999 of 1,000 books; the one
  exception is documented in section 11, and flagging rather than deleting means
  the assumption being wrong costs nothing.
- **An author plus a quote's full text identifies a quotation.** No collisions
  in the live data.
- **All book prices are GBP.** The site shows `£` and provides no currency
  field, so `GBP` is applied whenever a price parses.
- **The site structure is stable during a single run.** A 19-minute run assumes
  the markup does not change underneath it. A mid-run change would show up as a
  warning about a page with no items.
- **Stock counts are point-in-time.** `availability` is whatever the page said
  at that moment.
- **Both sites are intended for scraping.** They are published practice sites.
  The code identifies itself with a descriptive User-Agent, keeps a delay
  between requests, uses timeouts, and does not attempt to bypass anything.

## 15. Known limitations

- **A full run takes 17–19 minutes**, almost entirely because of the 1,000 book
  detail pages. `--skip-details` reduces this to about a minute at the cost of
  category, description and availability.
- **Requests are sequential.** One connection, one request at a time. Simple to
  reason about and polite, but it means the run time is essentially
  `1,060 × (delay + latency)`.
- **The retry backoff is 0, 2 and 4 seconds, not 1, 2 and 4.** urllib3's formula
  returns 0 for the first retry (`if consecutive_errors_len <= 1: return 0`), so
  `backoff_factor=1.0` gives `0s, 2s, 4s`. This was measured, not assumed: the
  DNS-failure test takes 6.6 seconds. No factor produces 1/2/4 with this
  formula.
- **`record_id` is not unique per row.** Duplicates share it by design. See
  section 8 for the correct unique key.
- **Punctuation handling in the fingerprint is asymmetric.** `"Alice's"`
  normalizes to `alice s`, so a variant written `"Alices"` would not match.
  Fixing this would need fuzzy matching, which brings its own false positives.
- **Five validation codes cannot fire from site data.** See section 10.
- **The log is overwritten on each run**, so there is no history. Deliberate for
  a submission, wrong for production.
- **No incremental scraping.** Every run re-fetches everything; there is no
  change detection or caching between runs.
- **Only tested on Python 3.12.10 and Windows 11.** The code should be portable
  — it uses `pathlib` throughout and no OS-specific calls — but that is untested.

## 16. What I would change for production

- **Scheduling** — run it on a schedule (cron, or a managed scheduler) rather
  than by hand, with alerting on failure instead of a non-zero exit code nobody
  sees.
- **A database instead of CSV** — Postgres with `record_id` plus a surrogate row
  key, so queries, joins and history are possible, and a 1.7 MB file does not
  have to be rewritten in full every run.
- **Incremental scraping** — store a hash per item and only re-fetch detail
  pages for items whose listing row changed. On this catalogue that would cut a
  typical run from 1,060 requests to a few dozen.
- **Concurrency for detail pages** — a small worker pool (4–8) with a shared
  rate limiter would cut the 19 minutes to 2–3 while staying polite. The detail
  fetches are independent, so this is the single biggest available win.
- **Alerting on `collected == 0`** — the pipeline already detects a source that
  collected nothing; in production that should page someone, because it is the
  signature of a broken selector, which is the most common and most silent
  scraper failure.
- **Selector-break detection as a first-class metric** — track items-per-page
  over time and alert on a sudden change, rather than only on zero.
- **Docker** — pin the Python version and system libraries in an image so the
  run is reproducible and does not depend on a local interpreter.
- **Structured logging** — JSON log lines to a log aggregator rather than a text
  file, so failures can be queried rather than read.
- **Respect `robots.txt` programmatically** and make the rate limit
  configuration-driven per host.

## 17. Testing and verification

**285 tests, about 2 seconds, entirely offline.**

| File | Tests | Covers |
|---|---|---|
| `tests/test_validation.py` | 71 | All 10 problem codes, including `rating=True`, `price=NaN`, `price=-1`, `javascript:` URLs, and a record returning 8 codes at once |
| `tests/test_cleaning.py` | 63 | Each cleaning function with literal inputs, including `None` for every one |
| `tests/test_pipeline.py` | 48 | `main.py` end to end with mocked scrapers: source isolation, exit codes, rejection, duplicate flagging and dropping, CSV format, reconciliation |
| `tests/test_parsers.py` | 39 | The real selectors against saved HTML, pagination href shapes, and missing elements |
| `tests/test_base_scraper.py` | 35 | `fetch()` failure handling, retry configuration, the UTF-8 override |
| `tests/test_deduplication.py` | 29 | Normalization, fingerprints, order stability, cross-source isolation |

**The network is blocked during tests.** `tests/conftest.py` patches
`socket.socket.connect`, `connect_ex` and `socket.create_connection` to raise,
with `autouse=True` so it applies to every test automatically. A test that
tried to reach the network would fail with a clear message rather than quietly
succeeding. This was confirmed by writing a throwaway test that called
`requests.get()` and watching it raise.

**Parser tests use saved HTML**, captured in `tests/fixtures/`: Books listing
pages 1, 2 and 50, a book detail page, and Quotes pages 1, 3 and 10. Pages 2 and
50 exist specifically to test the next-href shape change and the end of
pagination; Quotes page 3 contains a real zero-tag quote. Missing-element tests
take a real fixture and delete an element from the parsed tree with
`.decompose()`, then assert the field is empty and the other fields still work.

**Rejection is proven by tests even though the real run rejects 0.** Because the
transform layer makes most invalid states unreachable from site data
(section 10), `test_pipeline.py` constructs invalid records directly — including
monkeypatching the transform step to force an out-of-range rating — and asserts
they land in `rejected_records.csv` with the right codes and are absent from
`final_dataset.csv`.

**Fresh-clone install check.** The repository was cloned into a new folder
outside the project, a new virtual environment created from
`requirements.txt` alone, and both `pytest` and `python main.py --max-pages 2`
run there. Result: Python 3.12.10, install succeeded with the exact pinned
versions, **285 tests passed**, the pipeline ran and created `output/` and
`logs/` automatically. Cloning rather than just rebuilding the local
environment also proves no needed file was left uncommitted.

**Independent output verification.** `scripts/verify_output.py` re-reads the CSV
with the standard library and re-derives every number without the pipeline's own
code. All checks pass: row counts match the summary, the 1,099 non-duplicate
rows have 1,099 distinct `record_id` values, every price is a float `>= 0` with
two decimals, every rating is an int 1–5, no field contains `Â`, no quote text
contains a curly quote, the file begins with a UTF-8 BOM, and both Star-Touched
Queen rows are present with exactly one flagged.

**Live spot check: 5 of 5 rows match.** Three books and two quotes, chosen with
a fixed random seed, re-fetched from the live sites and compared field by field
— book title, price and rating; quote author and tags. The sample is stratified
across both sources on purpose: books are 91% of the rows, so a uniform sample
of five almost never includes a quote, and would leave `author` and `tags`
unverified.

## 18. AI usage summary

AI assistance was used throughout this project, for planning, for writing and
running code, and for explanations. Every file was reviewed line by line, every
number in this README comes from the generated output files rather than from an
estimate, and the AI's incorrect suggestions were caught by measurement rather
than by assumption — the retry timings, the `...more` suffix frequency, the
"titles are unique" assumption and the source-failure rule were all corrected
after being checked against real data.

**`AI_USAGE.md` contains the full account**: the tools used, representative
prompts, a file-by-file breakdown of what was AI-generated versus reviewed or
changed, and an honest list of every incorrect AI suggestion and how it was
found.
