"""Scraper for https://books.toscrape.com/.

Walks every listing page by following the "next" link, reads each book card,
and (unless skipped) visits each book's detail page for the three fields that
only exist there: category, description and availability.

Returns RAW dicts: the text exactly as found on the page. All cleaning and type
conversion happens later in processing/, so this module stays easy to test and
the original values stay visible for debugging.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

import config
from scrapers.base_scraper import BaseScraper, select_attr, select_text

logger = logging.getLogger(__name__)

SOURCE_NAME = "Books to Scrape"

# --- Selectors, all verified against the live site (see README "Source Exploration") ---
SEL_BOOK_CARD = "article.product_pod"                   # one book on a listing page
SEL_TITLE_LINK = "h3 > a"                               # holds the full title + detail href
SEL_PRICE = "p.price_color"                             # e.g. "£51.77"
SEL_RATING = "p.star-rating"                            # rating lives in the class attribute
SEL_NEXT_PAGE = "li.next > a"                           # pagination link, absent on the last page
SEL_CATEGORY = "ul.breadcrumb li:nth-of-type(3) a"      # detail page: 3rd crumb is the category
SEL_DESCRIPTION = "#product_description + p"            # detail page: may legitimately be absent
SEL_AVAILABILITY = "p.availability"                      # detail page: "In stock (22 available)"


class BooksScraper:
    """Collects raw book records from Books to Scrape."""

    def __init__(
        self,
        scraper: BaseScraper | None = None,
        base_url: str | None = None,
    ) -> None:
        """Accept an injected BaseScraper so tests can supply a fake one."""
        self.scraper = scraper or BaseScraper()
        self.base_url = base_url or config.BOOKS_BASE_URL
        self.stats: dict[str, int] = {
            "pages_scraped": 0,
            "pages_failed": 0,
            "pages_empty": 0,
            "records_collected": 0,
            "detail_pages_failed": 0,
        }

    # ------------------------------------------------------------------ public

    def scrape(
        self,
        max_pages: int | None = None,
        skip_details: bool = False,
    ) -> list[dict[str, Any]]:
        """Walk the listing pages and return one raw dict per book.

        Args:
            max_pages: stop after this many listing pages (None = all of them).
            skip_details: skip the per-book detail request, leaving category,
                description and availability as None.
        """
        records: list[dict[str, Any]] = []
        page_url: str | None = self.base_url
        page_number = 0

        while page_url:
            if max_pages is not None and page_number >= max_pages:
                logger.info("Books: reached max_pages=%s, stopping", max_pages)
                break

            page_number += 1
            soup = self.scraper.fetch(page_url)

            if soup is None:
                # A listing page is the spine of the walk: without it we cannot
                # find the next link, so stop this source but keep what we have.
                self.stats["pages_failed"] += 1
                logger.error(
                    "Books listing page %s failed: %s - stopping this source with %s record(s) collected",
                    page_number,
                    page_url,
                    len(records),
                )
                break

            cards = soup.select(SEL_BOOK_CARD)
            self.stats["pages_scraped"] += 1
            logger.info("Books page %s: %s (%s items)", page_number, page_url, len(cards))

            if not cards:
                self.stats["pages_empty"] += 1
                logger.warning("Books page %s had no %r elements - check the selector", page_number, SEL_BOOK_CARD)

            for card in cards:
                record = self._parse_card(card, page_url)
                if record is None:
                    continue  # already logged; skip just this book
                if not skip_details:
                    self._add_detail_fields(record)
                records.append(record)
                self.stats["records_collected"] += 1

            page_url = self._next_page_url(soup, page_url)

        logger.info("Books finished: %s record(s), stats=%s", len(records), self.stats)
        return records

    # ----------------------------------------------------------------- parsing

    def _parse_card(self, card: Tag, page_url: str) -> dict[str, Any] | None:
        """Read one book card into a raw dict, or return None if it cannot be read."""
        try:
            href = select_attr(card, SEL_TITLE_LINK, "href")
            rating_node = card.select_one(SEL_RATING)

            return {
                "source": SOURCE_NAME,
                # Full title from the attribute: the link TEXT is truncated with "..."
                "title": select_attr(card, SEL_TITLE_LINK, "title"),
                "detail_url": urljoin(page_url, href) if href else None,
                "price_text": select_text(card, SEL_PRICE),
                # e.g. "star-rating Three" - the word is mapped to 1-5 in Phase 4
                "rating_classes": " ".join(rating_node.get("class", [])) if rating_node else None,
                "listing_page_url": page_url,
                # Detail-page fields start empty and are filled in below if we fetch them
                "category": None,
                "description": None,
                "availability_text": None,
            }
        # Deliberately broad: any surprise in one card must not kill the whole page
        except Exception as exc:
            logger.warning("Skipping an unreadable book card on %s: %s", page_url, exc)
            return None

    def _add_detail_fields(self, record: dict[str, Any]) -> None:
        """Fetch the book's detail page and fill in category, description, availability.

        On any failure the record keeps its listing data and the three fields
        stay None, as required by the error-handling rules in plan.md Section 8.
        """
        detail_url = record.get("detail_url")
        if not detail_url:
            self.stats["detail_pages_failed"] += 1
            logger.warning(
                "No detail URL for %r - category, description and availability stay empty",
                record.get("title"),
            )
            return

        soup = self.scraper.fetch(detail_url)
        if soup is None:
            self.stats["detail_pages_failed"] += 1
            logger.warning(
                "Detail page failed for %r (%s) - keeping listing data with empty "
                "category, description and availability",
                record.get("title"),
                detail_url,
            )
            return

        try:
            record["category"] = select_text(soup, SEL_CATEGORY)
            # None here is normal, not an error: some books have no description
            record["description"] = select_text(soup, SEL_DESCRIPTION)
            record["availability_text"] = select_text(soup, SEL_AVAILABILITY)
        # Deliberately broad: a surprise here must not lose the listing data we already have
        except Exception as exc:
            self.stats["detail_pages_failed"] += 1
            logger.warning("Could not parse detail page %s: %s", detail_url, exc)

    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """Resolve the next listing page, or None when pagination is finished."""
        href = select_attr(soup, SEL_NEXT_PAGE, "href")
        if not href:
            logger.info("No next link on %s - Books pagination finished", current_url)
            return None
        # Join against the CURRENT page: page 1 gives "catalogue/page-2.html"
        # while page 2 gives "page-3.html". Only the current URL resolves both.
        return urljoin(current_url, href)
