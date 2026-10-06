"""Shared HTTP layer for every scraper.

This is the only place in the project that talks to the internet. It owns the
connection pool, the retry policy, the timeout and the politeness delay, so the
site-specific scrapers only ever deal with parsed HTML.
"""

from __future__ import annotations

import logging
import time

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

# Named after this module ("scrapers.base_scraper"). main.py configures the
# handlers in Phase 6; a library module must never call basicConfig itself.
logger = logging.getLogger(__name__)


# --- Shared soup helpers -----------------------------------------------------
# Both scrapers read fields the same way, so these live here once instead of
# being copied into each one. They are the reason a missing element can never
# raise: select_one returns None, and these turn that into a None field.


def select_text(node: Tag | BeautifulSoup, selector: str) -> str | None:
    """Stripped text of the first match, or None when nothing matches."""
    found = node.select_one(selector)
    if found is None:
        return None
    text = found.get_text(strip=True)
    return text or None  # an element that exists but is empty counts as empty


def select_attr(node: Tag | BeautifulSoup, selector: str, attribute: str) -> str | None:
    """One attribute of the first match, or None when absent."""
    found = node.select_one(selector)
    if found is None or not found.has_attr(attribute):
        return None
    value = found[attribute]
    # Multi-valued attributes (like class) come back as a list, not a string
    return value.strip() if isinstance(value, str) else None


class BaseScraper:
    """Fetches URLs politely and returns parsed soup, or None on failure."""

    def __init__(
        self,
        delay: float | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Build one reusable session. Arguments override config for testing."""
        self.delay = config.REQUEST_DELAY if delay is None else delay
        self.timeout = config.TIMEOUT if timeout is None else timeout
        self.session = self._build_session(user_agent or config.USER_AGENT)

        # Counters so main.py can report request volume in summary_report.json
        self.requests_made = 0
        self.requests_failed = 0

    @staticmethod
    def _build_session(user_agent: str) -> requests.Session:
        """Create a Session with our User-Agent and the retry policy attached."""
        session = requests.Session()
        session.headers.update({"User-Agent": user_agent})

        retry = Retry(
            total=config.MAX_RETRIES,                   # 3 retries after the first attempt
            backoff_factor=config.BACKOFF_FACTOR,       # waits 0s, 2s, 4s
            status_forcelist=config.RETRY_STATUS_CODES,  # only 429 and 5xx are retried
            allowed_methods=frozenset(["GET"]),         # never replay anything but GET
            raise_on_status=False,                      # hand the response back; we raise it ourselves
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def fetch(self, url: str) -> BeautifulSoup | None:
        """GET a URL and return parsed soup, or None if it could not be fetched.

        Never raises: any network or HTTP problem is logged and becomes None so
        the caller can decide whether to skip a record or stop a source.
        """
        self.requests_made += 1
        try:
            response = self.session.get(url, timeout=self.timeout)
            # Both sites mis-declare their charset, so fix it BEFORE reading .text
            response.encoding = "utf-8"
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except requests.RequestException as exc:
            self.requests_failed += 1
            logger.error("Request failed: %s (%s)", url, exc)
            return None
        finally:
            # Runs on success and on failure, so we stay polite even while erroring
            self._sleep()

    def _sleep(self) -> None:
        """Pause between requests so we never hammer the server."""
        if self.delay > 0:
            time.sleep(self.delay)

    def close(self) -> None:
        """Release the pooled connections."""
        self.session.close()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
