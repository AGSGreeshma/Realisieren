# AI Usage

## 1. Tools used, and what each was used for

**Tool: Claude (Anthropic).** The only AI tool used, in two separate sessions
with different roles.

### 1. Claude in the Claude desktop app (chat) — planning and review

- understanding the assignment and breaking it into 8 phases
- writing `plan.md` (rules, data model, phases, checklists) and the prompt for
  each phase
- explaining each phase's code and results to me in simple terms
- reviewing each phase's report before I committed, and raising follow-up
  questions (e.g. the failure rule, which led to the `collected == 0` fix; the
  no-description book check; the duplicate-titles question)
- interview preparation

### 2. Claude Code — implementation

- writing the code and tests for every phase from my prompts
- running the scrapers, tests and verification against the live sites
- debugging, and reporting corrections to its own earlier output
- drafting `README.md` and `AI_USAGE.md`, which I then reviewed

### How I worked

I gave each phase's prompt to the implementation session, read its report,
checked the results with the planning session, asked follow-up questions where
something looked wrong, and only then committed.

## 2. Representative prompts

These are short excerpts from the actual prompts used. Work was done one phase
at a time, against a written plan, with a "Done when" checklist closing each
phase.

**Phase 1 — setup and exploration**

> "We are doing PHASE 1 ONLY: Setup and exploration. Do not write any scraper,
> cleaning, or pipeline code yet. […] 5. `test_connection.py` […] fetch the
> Books home page: print status code, number of `article.product_pod` items,
> the first book's FULL title (from the title attribute), its raw price, its
> rating class, and the absolute next-page URL built with urljoin […] Explain
> why encoding is set to utf-8 and why urljoin uses the current page URL.
> 6. SELECTOR VERIFICATION GUIDE […] Tell me which ones you are not 100% sure
> about so I check those carefully."

**Phase 2 — base scraper and Books scraper**

> "`base_scraper.py`: […] `fetch(url) -> BeautifulSoup | None`: sets
> `response.encoding = "utf-8"`, calls `raise_for_status()`, catches
> `requests.RequestException` […] logs an ERROR with the URL and reason, and
> returns None. It never crashes. […] 3. Check the 3 flagged selectors from
> Phase 1 […] Look for a book with no description (scan the catalogue if
> needed) and tell me which one, or tell me none were found. The code must
> handle None either way."

**Phase 5 — validation and deduplication**

> "`invalid_rating` (present but not an int 1-5; note bool is a subclass of int
> in Python, so reject True/False explicitly) […] Explain clearly: duplicates
> intentionally SHARE the same `record_id` (it identifies the item, not the
> row), so they can be grouped and audited. Tell me if you think this design has
> a weakness. […] If any books share a title, list them with their URLs and
> prices and tell me whether they are truly the same book or different books
> with the same name. Don't decide silently; this affects my README's
> assumptions."

**Phase 6 — questioning the failure rule**

> "Does a source count as failed if `pages_scraped > 0` but `collected == 0`
> (e.g. a page that returns 200 with no items)? If not, should the rule be
> `collected == 0` instead of 'no page succeeded'? Show me with a quick test."

**Phase 7 — tests and clean-environment check**

> "Add `tests/conftest.py` that BLOCKS real network access during tests (e.g.
> monkeypatch `socket.socket.connect` to raise). This proves the tests run fully
> offline. […] Clone the local repo into a fresh folder OUTSIDE the project […]
> (This catches any file that works on my machine but was never committed.) […]
> List anything that was missing or broken in the clone, and fix it in the real
> project."

**A standing instruction repeated in every phase**

> "Tell me when you're unsure. If a selector or assumption hasn't been checked
> against the live site, say so. […] Log AI mistakes. If you correct something
> you suggested earlier, flag it clearly ('Correction: …') so I can record it in
> `AI_USAGE.md`."

## 3. AI-assisted parts, file by file

| File | What AI did | What I reviewed or changed |
|---|---|---|
| `config.py` | Wrote all settings with one-line comments | Removed my email address from `USER_AGENT`; corrected the backoff comment from `1s, 2s, 4s` to `0s, 2s, 4s`; chose to keep `BACKOFF_FACTOR = 1.0` as a locked decision |
| `scrapers/base_scraper.py` | Session, `urllib3.Retry`, timeout, polite delay, `fetch()` returning `None` | Reviewed the `finally`-block delay (so a failing server is not hammered) and `raise_on_status=False` (so error messages are readable); later approved moving the shared soup helpers here to remove duplication |
| `scrapers/books_scraper.py` | Pagination loop, listing and detail parsing, per-record `try/except` | Verified every selector in DevTools myself; required the rating be read by word rather than class position; approved extracting `parse_listing`/`parse_detail` in Phase 7 so parsing is testable offline |
| `scrapers/quotes_scraper.py` | Same pattern, reusing the base scraper | Chose to move the duplicated helpers into `base_scraper.py` rather than copy them; confirmed zero-tag quotes give `[]` not `None` |
| `processing/models.py` | `Record` dataclass and `COLUMNS` | Approved `kw_only=True` (15 fields cannot be mixed up positionally) and deriving `COLUMNS` from the dataclass so the two cannot drift |
| `processing/cleaning.py` | The nine pure functions | Required the `...more` suffix be verified against the live site before being coded; confirmed the minus sign is kept in `clean_price` so validation can reject negatives; noted the `\xa0` replace is redundant but kept it for readability |
| `processing/transform.py` | Raw dict to `Record` mapping | Specified one `scraped_at` per run rather than per record; confirmed `currency` is only set when a price parsed |
| `processing/validation.py` | All ten problem codes, `split_valid`, `count_reasons` | Specified the explicit `bool` rejection and the NaN check; expanded the plan from six codes to ten |
| `processing/deduplication.py` | Normalization, SHA-256 fingerprint, `mark_duplicates` | Asked for the design weakness to be stated rather than hidden, which surfaced that `record_id` is not unique per row; required the real duplicate be investigated rather than assumed |
| `main.py` | CLI, logging setup, the stage pipeline, all three output writers, the reconciliation block | Questioned the source-failure rule twice until it was correct; required `--max-pages 0` be rejected; required the reconciliation arithmetic be written into the output with an `ok` flag |
| `tests/` (285 tests) | Wrote all six test files and `conftest.py` | Required the network be blocked during tests and the block be proven; required the fixture-based tests move next to the parsing they depend on |
| `scripts/verify_output.py` | Independent verification and the live spot check | Required it not import the pipeline's counting code; caught that the spot check sampled no quotes and required stratified sampling |
| `README.md` | Drafted all 18 sections | Required every number come from the real output files; required the honest note that five validation codes cannot fire from site data |
| `pytest.ini`, `.gitignore`, `requirements.txt` | Wrote all three | Required only the four direct dependencies be pinned, not a full `pip freeze`; decided to commit the final outputs in Phase 8 |

## 4. Important changes after review, and incorrect AI suggestions

Every item below was found and corrected during the work. They are grouped by
the phase in which they happened.

**Which session was wrong matters, so it is stated honestly.** Some of these
were mistakes in the **planning session's `plan.md`**, not in the generated
code — the plan asserted things that turned out to be false, and the
**implementation session's testing caught them**:

| Mistake in the plan | How it was caught |
|---|---|
| Retry backoff stated as `1 → 2 → 4 s` | Reading the urllib3 source and measuring a real DNS failure: the true schedule is `0, 2, 4 s`, and no setting produces 1/2/4 |
| "Titles are unique per book" listed as an assumption | Fingerprinting all 1,000 books found one counter-example (*The Star-Touched Queen*) |
| Six validation problem codes | Expanded to ten during Phase 5; five of the ten then proved unreachable from site data |
| `book_to_record(raw)` with no timestamp argument | Changed to `book_to_record(raw, scraped_at)` so one timestamp covers a whole run |

The rest were mistakes in the implementation session's own output, which it
corrected and reported. Both kinds are listed below without distinction of
blame, because the point is that they were found before submission — but the
plan was not a source of truth, and treating it as one is what let the
`...more` suffix and the uniqueness assumption survive as long as they did.

### Phase 1 — setup and exploration

- **A personal email address was placed in the `USER_AGENT` string.** The
  User-Agent is transmitted to every server the scraper contacts and would also
  have sat in a public repository. This broke an explicit project rule about not
  putting personal data in the code. Removed, and replaced with a descriptive
  string containing no personal data.
- **A Python release candidate was used.** The first virtual environment was
  built on **3.11.0rc1** — a pre-release, not a final version. It worked, but
  writing "Python 3.11" in the README while running a release candidate would
  have been inaccurate. Rebuilt on **3.12.10**, a stable release.

### Phase 2 — base scraper and Books scraper

- **The retry backoff timings were wrong, in both the plan and the code
  comments.** They claimed waits of `1s, 2s, 4s`. Reading the urllib3 2.x source
  shows `if consecutive_errors_len <= 1: return 0`, so the first retry is
  immediate and the real schedule is **`0s, 2s, 4s`**. Confirmed by measurement:
  the DNS-failure test takes 6.6 seconds, not 7. No `backoff_factor` value
  produces 1/2/4 with this formula, so the plan's target was unachievable. The
  comment was corrected rather than the locked setting changed.
- **Linter suppression comments that could not be justified.** Two
  `# noqa: BLE001` markers were added to broad `except` clauses. Those suppress
  warnings from a linter this project does not use, so they were two lines that
  could not be explained in an interview. Replaced with plain-English comments
  stating why the catch is deliberately broad.
- **A background job was reported as finished when it was still running.** A
  long catalogue scan was described as complete based on a process-exit signal;
  the underlying Python process was in fact still working, because the command
  had been backgrounded with `&` and only the wrapper shell had exited. The
  lesson applied for the rest of the project: **verify a long job by its output
  artifact, not by a process-exit signal.** The same mistake was nearly repeated
  later and was caught by checking for the expected output file.

### Phase 3 — Quotes scraper

- **A test was labelled "404" when the URL actually returned 200.** A
  broken-URL check used `quotes.toscrape.com/page/99999/` under the heading
  "404 on the first listing page". That URL returns **HTTP 200 with zero
  quotes**, not a 404. The label was wrong, and the mislabelling hid a more
  interesting case. Split into three honestly-named scenarios: a real 404 (using
  a path that does 404), a 200 with no items, and a DNS failure. The 200-with-no-
  items case later turned out to matter a great deal (see Phase 6).
- **A truncation check produced false positives.** A test for truncated titles
  used `'...' in title`, which flagged three of the thousand books. All three
  were false positives — their real titles genuinely contain ellipses, for
  example *"I Had a Nice Time And Other Lies...: How to find love & sh\*t like
  that"*. Since titles are read from the `title` attribute, which is never
  truncated, the check was unnecessary as well as wrong.

### Phase 4 — cleaning and transform

- **The Phase 1 source-exploration notes missed the `...more` suffix.** The
  original notes recorded that descriptions "may be missing" but said nothing
  about the trailing `...more` link text, which affects **943 of the 998
  descriptions present, about 94%**. This was only discovered when the cleaning
  functions were written and the live data was measured rather than sampled. The
  README now documents it.

### Phase 5 — validation and deduplication

- **The plan's stated assumption "titles are unique per book" was disproven by
  the real data.** It had been accepted without testing through four phases.
  Checking all 1,000 books found exactly one counter-example: *The Star-Touched
  Queen* is listed twice, at **£46.02** and **£32.30**, with different stock
  counts and different URLs. Comparing the two descriptions (similarity 0.83,
  one mentioning a "listener") showed they are the same work in two formats, not
  two different books sharing a name. The README now documents the real
  behaviour instead of repeating the assumption, and explains what
  `--drop-duplicates` would discard.

### Phase 6 — main program and outputs

- **Failure detection missed a source whose only page returned 404.** The first
  version treated a source as failed only if it raised an exception. A source
  whose single listing page 404'd returned zero records, reported
  `failed_sources: []`, and exited 0 — so `python main.py --source books`
  against a dead URL would have claimed success while writing an empty CSV.
- **The second version still missed the case that matters most.** It was changed
  to "no page succeeded", which caught the 404 but still waved through a page
  that returns **HTTP 200 with no items** — a broken selector. That case has
  `pages_scraped = 1`, `pages_failed = 0` and no exception, so every
  error-shaped signal looks healthy while the scraper silently produces nothing.
- **The final rule is `collected == 0`.** It subsumes all three causes — a
  crash, every page failing, and 200-with-no-items — in one condition, because
  it measures the **outcome** rather than the mechanism. This was found by
  questioning the rule directly, **not by a failing test**: every test passed
  against the wrong rule, because no test described that case yet. A test was
  then written for it.
- **`--max-pages 0` is now rejected.** It would collect nothing without anything
  being wrong, which was the one case that made `collected == 0` ambiguous.
  Rejecting values below 1 at the argument parser removes the ambiguity rather
  than special-casing it in the rule.

### Phase 7 — tests and clean-environment check

- **The first live spot check proved less than it claimed.** It sampled five
  rows uniformly from 1,100 and, because books are 91% of the data, drew **five
  books and zero quotes** — then reported that all spot-checked fields matched.
  The `author` and `tags` fields had not been checked at all. Changed to
  stratified sampling (three books, two quotes). A passing verification on an
  unrepresentative sample is worse than none, because it creates false
  confidence.
- **Five of the ten validation codes cannot be triggered by site data.** All ten
  had been presented as equally meaningful. Writing the pipeline tests showed
  otherwise: a deliberately bad rating of `"star-rating Nine"` did not produce
  `invalid_rating`, because `"Nine"` is not in the word map, so cleaning returns
  an empty value, which is valid. Forcing that code to fire required
  monkeypatching the transform step. The transform layer makes
  `unknown_source`, `price_currency_mismatch`, `invalid_rating`,
  `invalid_availability` and `missing_scraped_at` structurally impossible from
  the websites; they guard against future code changes. This is now stated
  plainly in the README, and it is the real reason the run rejects zero records.
- **A throwaway script was collected by pytest for six phases.** The Phase 1
  `test_connection.py` sat in the project root, and its `test_` prefix meant
  pytest collected it on every run. It was flagged in Phase 1 as "harmless" —
  which was true, since it contained no test functions and made no network calls
  on import — but the two-line fix (`pytest.ini` with `testpaths = tests`) was
  not applied until Phase 7. It should have been fixed when first noticed.

### Phase 8 — documentation and cleanup

- **A commit that had already been pushed was rewritten.** A commit with a
  placeholder message (`"Phase N: ..."`) was amended to give it a proper message
  and fold in two pending fixes. The local reflog was checked first, but **the
  remote was not** — earlier phases had no remote, and that was assumed to still
  be true. The commit had in fact been pushed, so the amend rewrote published
  history and left the branch unable to fast-forward. No work was lost, since
  the amended commit contains everything the original did, but the correct order
  is to check for a remote *before* rewriting any commit.
- **A warning in `scripts/README.md` over-claimed.** It stated that both
  `try_failure.py` and `try_books.py` overwrite the final output files. Checking
  the code showed only `try_failure.py` does, because only it invokes the
  pipeline; `try_books.py` and `verify_output.py` are read-only. Corrected.

### A pattern worth noting

Almost every item above was caught by **measuring instead of assuming**: reading
the urllib3 source rather than trusting a remembered formula, scanning all 1,000
books rather than sampling, checking what a URL actually returns rather than
what its name suggests, and asking whether a rule covered a case rather than
waiting for a test to fail. The three mistakes that survived longest — the
`...more` suffix, the "titles are unique" assumption and the pytest collection
problem — all survived because something was accepted as true without being
checked.

## 5. How the final solution was tested and verified

**285 automated tests, about 2 seconds, entirely offline.**

| File | Tests |
|---|---|
| `tests/test_validation.py` | 71 |
| `tests/test_cleaning.py` | 63 |
| `tests/test_pipeline.py` | 48 |
| `tests/test_parsers.py` | 39 |
| `tests/test_base_scraper.py` | 35 |
| `tests/test_deduplication.py` | 29 |

- **The network is blocked during tests.** `tests/conftest.py` patches
  `socket.socket.connect`, `connect_ex` and `socket.create_connection` to raise,
  with `autouse=True`. This was proven by writing a throwaway test that called
  `requests.get()` and confirming it raised rather than succeeded.
- **Parser tests run against saved HTML** in `tests/fixtures/` — Books listing
  pages 1, 2 and 50, a book detail page, and Quotes pages 1, 3 and 10. Pages 2
  and 50 exist specifically to test the next-href shape change and the end of
  pagination; Quotes page 3 contains a real zero-tag quote. Missing-element
  tests delete an element from a real fixture with `.decompose()` and assert the
  field is empty while the rest still works.
- **Fresh-clone install check.** The repository was cloned into a new folder
  outside the project, a new virtual environment built from `requirements.txt`
  alone, and `pytest` plus `python main.py --max-pages 2` run there. Python
  3.12.10, install succeeded with the exact pinned versions, 285 tests passed,
  the pipeline ran and created `output/` and `logs/` automatically. Cloning
  rather than rebuilding the local environment also proves no required file was
  left uncommitted.
- **Independent output verification.** `scripts/verify_output.py` re-reads
  `output/final_dataset.csv` with the standard library's `csv` module and
  re-derives every count, type and range **without importing the pipeline's own
  counting code**, so a bug in `main.py` cannot hide by agreeing with itself.
  All checks pass: the row counts match the summary, the 1,099 non-duplicate
  rows have 1,099 distinct `record_id` values, every price is a float `>= 0`
  with two decimals, every rating is an integer 1–5, no field contains `Â`, no
  quote text contains a curly quote, the file begins with a UTF-8 BOM, and both
  *Star-Touched Queen* rows are present with exactly one flagged.
- **Live spot check: 5 of 5 rows match.** Three books and two quotes, chosen
  with a fixed random seed, re-fetched from the live sites and compared field by
  field — title, price and rating for books; author and tags for quotes.
- **Reconciliation inside the output itself.** `summary_report.json` states its
  own arithmetic (`1100 − 0 − 0 = 1100`, `1100 − 1 = 1099`,
  `csv_rows 1100 == 1100`) with an `ok` flag, and the run logs an ERROR if the
  numbers do not add up. All three checks are `true` in this submission.
- **Real-world reliability, observed by accident.** During development a full
  catalogue scan hit a genuine `RemoteDisconnected` on one detail page. The
  retry succeeded, no ERROR was logged and no record was lost — unplanned
  evidence that the retry policy works against the real internet.

## 6. Closing note

I reviewed every file in this project line by line, ran every check reported
here myself, and can explain what each part does and why it was written that
way. Where the AI's suggestions were wrong, they were caught by checking against
the real sites and the real output files rather than by accepting them — the
retry timings, the `...more` suffix, the "titles are unique" assumption and the
source-failure rule are all documented above, along with how each was found. I
made the design decisions the plan locked down, questioned the ones that looked
wrong, and kept the record of my own mistakes as well as the AI's.
