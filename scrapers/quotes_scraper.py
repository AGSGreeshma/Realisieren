"""Scraper for https://quotes.toscrape.com/.

Walks every listing page by following the "next" link and reads each quote
block. Simpler than the Books scraper: every field is on the listing page, so
there are no detail requests. Author pages are deliberately NOT visited - the
plan only asks for the author's URL, not the contents of that page.

Returns RAW dicts: the text exactly as found, curly quotes still attached.
Stripping them is cleaning, which belongs in processing/ (Phase 4).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

import config
from scrapers.base_scraper import BaseScraper, select_attr, select_text

logger = logging.getLogger(__name__)

SOURCE_NAME = "Quotes to Scrape"

# --- Selectors, all verified against the live site (see README "Source Exploration") ---
SEL_QUOTE_BLOCK = "div.quote"               # one quote on a listing page
SEL_TEXT = "span.text"                      # the quote, wrapped in curly quotes
SEL_AUTHOR = "small.author"                 # the author's name
SEL_AUTHOR_LINK = 'a[href^="/author/"]'     # root-relative, e.g. "/author/Albert-Einstein"
SEL_TAG = "a.tag"                           # zero or more tags per quote
SEL_NEXT_PAGE = "li.next > a"               # pagination link, absent on the last page


class QuotesScraper:
    """Collects raw quote records from Quotes to Scrape."""

    def __init__(
        self,
        scraper: BaseScraper | None = None,
        base_url: str | None = None,
    ) -> None:
        """Accept an injected BaseScraper so tests can supply a fake one."""
        self.scraper = scraper or BaseScraper()
        self.base_url = base_url or config.QUOTES_BASE_URL
        self.stats: dict[str, int] = {
            "pages_scraped": 0,
            "pages_failed": 0,
            "pages_empty": 0,
            "records_collected": 0,
            "quotes_without_tags": 0,
        }

    # ------------------------------------------------------------------ public

    def scrape(self, max_pages: int | None = None) -> list[dict[str, Any]]:
        """Walk the listing pages and return one raw dict per quote.

        Args:
            max_pages: stop after this many listing pages (None = all of them).
        """
        records: list[dict[str, Any]] = []
        page_url: str | None = self.base_url
        page_number = 0

        while page_url:
            if max_pages is not None and page_number >= max_pages:
                logger.info("Quotes: reached max_pages=%s, stopping", max_pages)
                break

            page_number += 1
            soup = self.scraper.fetch(page_url)

            if soup is None:
                # Without the page we cannot find the next link, so stop this
                # source but keep everything collected so far.
                self.stats["pages_failed"] += 1
                logger.error(
                    "Quotes listing page %s failed: %s - stopping this source with %s record(s) collected",
                    page_number,
                    page_url,
                    len(records),
                )
                break

            page_records, blocks_found = self.parse_listing(soup, page_url)
            self.stats["pages_scraped"] += 1
            logger.info("Quotes page %s: %s (%s items)", page_number, page_url, blocks_found)

            if not blocks_found:
                self.stats["pages_empty"] += 1
                logger.warning(
                    "Quotes page %s had no %r elements - check the selector",
                    page_number,
                    SEL_QUOTE_BLOCK,
                )

            for record in page_records:
                records.append(record)
                self.stats["records_collected"] += 1

            page_url = self._next_page_url(soup, page_url)

        logger.info("Quotes finished: %s record(s), stats=%s", len(records), self.stats)
        return records

    # ----------------------------------------------------------------- parsing

    def parse_listing(
        self,
        soup: BeautifulSoup,
        page_url: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Read every quote on one listing page. Pure parsing, no network.

        Returns (records, blocks_found), for the same reason as the Books
        scraper: "no quote blocks at all" and "blocks present but unparseable"
        are different problems.
        """
        blocks = soup.select(SEL_QUOTE_BLOCK)
        records = [
            record
            for record in (self._parse_quote(block, page_url) for block in blocks)
            if record is not None
        ]
        return records, len(blocks)

    def _parse_quote(self, block: Tag, page_url: str) -> dict[str, Any] | None:
        """Read one quote block into a raw dict, or None if it cannot be read."""
        try:
            author_href = select_attr(block, SEL_AUTHOR_LINK, "href")

            # select() returns [] when nothing matches, so zero tags is a normal
            # result, not an error. Empty strings are dropped but [] is kept.
            tags = [tag.get_text(strip=True) for tag in block.select(SEL_TAG)]
            tags = [tag for tag in tags if tag]
            if not tags:
                self.stats["quotes_without_tags"] += 1

            return {
                "source": SOURCE_NAME,
                # Curly quotes are kept on purpose; strip_quotes() handles them in Phase 4
                "text": select_text(block, SEL_TEXT),
                "author": select_text(block, SEL_AUTHOR),
                # "/author/Albert-Einstein" is root-relative, so urljoin resolves
                # it against the site root rather than the current path
                "author_url": urljoin(page_url, author_href) if author_href else None,
                "tags": tags,
                "page_url": page_url,
            }
        # Deliberately broad: any surprise in one quote must not kill the whole page
        except Exception as exc:
            logger.warning("Skipping an unreadable quote on %s: %s", page_url, exc)
            return None

    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """Resolve the next listing page, or None when pagination is finished."""
        href = select_attr(soup, SEL_NEXT_PAGE, "href")
        if not href:
            logger.info("No next link on %s - Quotes pagination finished", current_url)
            return None
        # Same rule as Books: join against the page the link was found on
        return urljoin(current_url, href)
