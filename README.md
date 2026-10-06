# Multi-Source Web Scraping & Data Consolidation

A Python pipeline that scrapes two public practice sites, cleans and standardizes the
results, validates them, detects duplicates, and writes one consolidated dataset plus a
run summary.

> **Status:** Phase 1 complete (setup and source exploration). The remaining sections
> required by the assignment — setup, how to run, data model, cleaning, validation,
> deduplication, error handling, outputs, assumptions, limitations, production notes and
> AI usage — are written in Phase 8.

- **Python:** 3.12.10 (plan allows 3.10–3.12)
- **Dependencies:** `requests`, `beautifulsoup4`, `lxml`, `pytest`

---

## Source Exploration

Both sources were inspected with Chrome DevTools (Elements panel, `Ctrl+F` with CSS
selectors) and confirmed programmatically with a throwaway `test_connection.py` script.
All selectors below are verified against the live sites unless explicitly flagged.

### Books to Scrape — <https://books.toscrape.com/>

**Page structure.** A server-rendered catalogue. The landing page is page 1 of the
listing; each listing page holds exactly **20** books, each one an
`article.product_pod` card. Every card links to its own detail page, which carries the
two fields the listing does not have: category and description.

**Pagination.** Follow `li.next > a` and resolve its `href` with
`urljoin(current_page_url, href)` until the link disappears. **Page 50 has no
`li.next`**, which terminates the loop naturally — 50 pages x 20 books = **1,000
books**. No page numbers are hard-coded.

**Fields and where they live.**

| Field | Location | Selector |
|---|---|---|
| Title (full) | listing card | `h3 > a` → **`title` attribute** |
| Price | listing card | `p.price_color` (e.g. `£51.77`) |
| Rating | listing card | `p.star-rating` → **CSS class**, e.g. `['star-rating', 'Three']` |
| Detail URL | listing card | `h3 > a[href]`, relative |
| Category | detail page | `ul.breadcrumb li:nth-of-type(3) a` |
| Description | detail page | `#product_description + p` (**may be absent**) |
| Availability | detail page | `p.availability` (e.g. `In stock (22 available)`) |

**Tricky parts.**

- **Truncated titles.** The visible link text is cut off — `A Light in the ...`. The
  complete title is only in the `title` **attribute** (`A Light in the Attic`). Reading
  `.get_text()` here would silently corrupt every record, so the attribute is the source
  of truth.
- **`£` encoding.** The server's HTTP header declares `charset=ISO-8859-1`, but the bytes
  are UTF-8. `requests` trusts the header, so `£` (UTF-8 `0xC2 0xA3`) decodes as two
  characters — the classic `Â£51.77`. Setting `response.encoding = "utf-8"` **before**
  reading `response.text` fixes it; afterwards is too late, the decode has happened.
- **Rating is presentation, not content.** There is no numeric rating anywhere in the
  markup — the star count is encoded purely as a CSS class word (`One`…`Five`) and has to
  be mapped to 1–5. The word is matched against a lookup map rather than read by class
  position, since attribute order is not guaranteed.
- **Relative next-links change shape after page 1.** On the site root the href is
  `catalogue/page-2.html`; from inside `catalogue/` it is just `page-3.html`. Detail
  hrefs shift the same way (`catalogue/in-her-wake_980/index.html` on page 1 versus
  `in-her-wake_980/index.html` on page 2). Joining against the **current page URL**
  resolves both correctly; joining against a fixed base URL would 404 from page 3 on.
- **Missing descriptions.** `#product_description + p` is an adjacent-sibling selector
  and returns `None` for books that have no description. The field is left empty — never
  substituted with a placeholder.
- **Two requests per book.** Category and description require visiting each detail page,
  so a full run is ~1,050 requests (50 listing + 1,000 detail). A `--skip-details` flag
  exists for fast runs.

### Quotes to Scrape — <https://quotes.toscrape.com/>

**Page structure.** Also server-rendered, and much flatter. Each page holds exactly
**10** quotes, each a `div.quote` containing everything needed — there is no detail page
to visit. The site also publishes `/js/` and `/login` variants; both are deliberately
avoided, since `/js/` renders its quotes with JavaScript that `requests` cannot execute.

**Pagination.** Identical rule: `li.next > a` joined with the current URL. **Page 10 has
no `li.next`** — 10 pages x 10 quotes = **100 quotes**.

**Fields and where they live.**

| Field | Location | Selector |
|---|---|---|
| Quote text | quote block | `span.text` |
| Author | quote block | `small.author` |
| Author URL | quote block | `a[href^="/author/"]`, root-relative |
| Tags | quote block | `a.tag` (zero or more) |

**Tricky parts.**

- **Curly quotation marks.** `span.text` is wrapped in typographic quotes
  (`“ … ”`), not ASCII `"`. They are stripped so the stored text is the quote
  itself, which also matters for deduplication — the fingerprint must not depend on
  punctuation.
- **Zero-tag quotes.** `a.tag` can match nothing. `select()` returns an empty list (it
  does not raise), which becomes an empty `tags` field rather than a missing row.
- **Root-relative author URLs.** `/author/Albert-Einstein` begins with `/`, so `urljoin`
  resolves it against the site root — correctly, and differently from the Books site's
  path-relative hrefs. Same function, two different relative-URL forms.
- **No category, price, rating or availability.** These simply do not exist for quotes
  and are left empty. Inventing a category would be fabricating data.

### Key differences between the two sources

| | Books to Scrape | Quotes to Scrape |
|---|---|---|
| Records | ~1,000 over 50 pages | 100 over 10 pages |
| Items per page | 20 | 10 |
| Detail page needed | **Yes** — category and description | No — one page has everything |
| Requests for a full run | ~1,050 | 10 |
| Relative URL style | path-relative, **shape changes after page 1** | root-relative (`/author/...`) |
| Encoding pitfall | `£` mis-declared as ISO-8859-1 | curly quotes in the text |
| Field completeness | price, rating, availability, category | author, author URL, tags |
| Pagination rule | `li.next > a` | `li.next > a` (identical) |

The two sources overlap only in `source`, `source_url`, `name_or_title`, `scraped_at` and
`is_duplicate`. Every other column is populated by exactly one source and left empty for
the other — which is why the unified schema in the data model keeps source-specific
columns nullable instead of forcing a shared shape. The shared pagination rule is the one
piece of logic both scrapers genuinely reuse from `base_scraper.py`.
