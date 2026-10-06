"""Offline tests for the HTTP layer, using a fake session instead of the network.

The retry policy is checked by inspecting the configured adapter rather than by
provoking real retries, which would be slow and need a server.
"""

from __future__ import annotations

import logging

import pytest
import requests
from bs4 import BeautifulSoup

import config
from scrapers.base_scraper import BaseScraper, select_attr, select_text

URL = "https://books.toscrape.com/"

# "£51.77" encoded as UTF-8 bytes: 0xC2 0xA3 for the pound sign
POUND_HTML_BYTES = "<html><body><p class='price_color'>£51.77</p></body></html>".encode("utf-8")


class FakeResponse:
    """Mimics the part of requests.Response that fetch() touches.

    Crucially .text decodes the raw bytes using whatever .encoding currently
    is - exactly like the real thing - so a test can prove that setting
    encoding to utf-8 changes the result.
    """

    def __init__(self, body: bytes, status_code: int = 200, declared_encoding: str = "ISO-8859-1"):
        self._body = body
        self.status_code = status_code
        self.encoding = declared_encoding

    @property
    def text(self) -> str:
        return self._body.decode(self.encoding)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url: {URL}")


@pytest.fixture
def scraper() -> BaseScraper:
    """A BaseScraper with no delay, so tests do not sleep."""
    return BaseScraper(delay=0)


def give_response(scraper: BaseScraper, response: FakeResponse) -> None:
    """Make session.get return this response instead of making a request."""
    scraper.session.get = lambda url, timeout=None: response


def make_raise(scraper: BaseScraper, exception: Exception) -> None:
    """Make session.get raise instead of making a request."""

    def boom(url, timeout=None):
        raise exception

    scraper.session.get = boom


# ------------------------------------------------------------ happy path


def test_fetch_returns_soup_on_success(scraper):
    give_response(scraper, FakeResponse(POUND_HTML_BYTES))
    soup = scraper.fetch(URL)
    assert isinstance(soup, BeautifulSoup)


def test_fetch_counts_a_successful_request(scraper):
    give_response(scraper, FakeResponse(POUND_HTML_BYTES))
    scraper.fetch(URL)
    assert scraper.requests_made == 1
    assert scraper.requests_failed == 0


# ------------------------------------------------------------- encoding


def test_fetch_forces_utf8_encoding(scraper):
    """The server declares ISO-8859-1 but sends UTF-8, so fetch must override."""
    response = FakeResponse(POUND_HTML_BYTES, declared_encoding="ISO-8859-1")
    give_response(scraper, response)

    soup = scraper.fetch(URL)

    price = select_text(soup, "p.price_color")
    assert price == "£51.77"            # a single pound sign
    assert ord(price[0]) == 0xA3
    assert "Â" not in price             # not the "Â£" mojibake
    assert response.encoding == "utf-8"      # fetch changed it


def test_without_the_override_the_pound_sign_would_be_mojibake():
    """Documents the bug the encoding line prevents."""
    assert POUND_HTML_BYTES.decode("ISO-8859-1").count("Â£") == 1
    assert POUND_HTML_BYTES.decode("utf-8").count("£") == 1


# ------------------------------------------------- failures return None


@pytest.mark.parametrize(
    "exception",
    [
        requests.ConnectionError("connection refused"),
        requests.Timeout("timed out"),
        requests.HTTPError("500 Server Error"),
        requests.TooManyRedirects("too many redirects"),
        requests.RequestException("something generic"),
    ],
)
def test_fetch_returns_none_on_request_exceptions(scraper, exception):
    make_raise(scraper, exception)
    assert scraper.fetch(URL) is None


@pytest.mark.parametrize(
    "exception",
    [
        requests.ConnectionError("connection refused"),
        requests.Timeout("timed out"),
        requests.HTTPError("500 Server Error"),
    ],
)
def test_fetch_logs_an_error_on_failure(scraper, exception, caplog):
    make_raise(scraper, exception)
    with caplog.at_level(logging.ERROR):
        scraper.fetch(URL)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "ERROR"
    assert URL in caplog.text           # the log names the URL
    assert "Request failed" in caplog.text


def test_fetch_counts_a_failed_request(scraper):
    make_raise(scraper, requests.Timeout("timed out"))
    scraper.fetch(URL)
    assert scraper.requests_made == 1
    assert scraper.requests_failed == 1


def test_http_error_status_returns_none(scraper):
    """raise_for_status turns a 404 into an HTTPError, which fetch catches."""
    give_response(scraper, FakeResponse(b"<html></html>", status_code=404))
    assert scraper.fetch(URL) is None
    assert scraper.requests_failed == 1


def test_fetch_never_raises(scraper):
    """Whatever requests throws, fetch returns None instead of propagating."""
    make_raise(scraper, requests.ConnectionError("boom"))
    try:
        result = scraper.fetch(URL)
    except Exception as exc:  # pragma: no cover - this is the failure we test for
        pytest.fail(f"fetch raised {exc!r} instead of returning None")
    assert result is None


# ------------------------------------------------------- retry policy


def retry_policy(scraper: BaseScraper):
    """The Retry object the session will actually use for https URLs."""
    return scraper.session.get_adapter(URL).max_retries


def test_retry_total_matches_config(scraper):
    assert retry_policy(scraper).total == config.MAX_RETRIES


def test_retry_backoff_matches_config(scraper):
    assert retry_policy(scraper).backoff_factor == config.BACKOFF_FACTOR


def test_retry_status_forcelist_matches_config(scraper):
    assert set(retry_policy(scraper).status_forcelist) == set(config.RETRY_STATUS_CODES)


def test_retry_applies_to_get_only(scraper):
    assert retry_policy(scraper).allowed_methods == frozenset(["GET"])


def test_404_is_not_in_the_retry_list(scraper):
    """A 404 will not exist on a retry either, so retrying it wastes time."""
    assert 404 not in retry_policy(scraper).status_forcelist


def test_retry_policy_is_mounted_for_http_too(scraper):
    """Mounting only https:// would leave http:// URLs with no retries."""
    http_retry = scraper.session.get_adapter("http://books.toscrape.com/").max_retries
    assert http_retry.total == config.MAX_RETRIES


def test_backoff_schedule_is_zero_two_four(scraper):
    """urllib3 skips the first backoff, so 1.0 gives 0s, 2s, 4s - not 1, 2, 4."""
    policy = retry_policy(scraper)
    waits = []
    current = policy
    for _ in range(3):
        current = current.increment(method="GET", url="/x", error=Exception("boom"))
        waits.append(current.get_backoff_time())
    assert waits == [0, 2.0, 4.0]


# -------------------------------------------------- session configuration


def test_session_sends_the_configured_user_agent(scraper):
    assert scraper.session.headers["User-Agent"] == config.USER_AGENT


def test_user_agent_contains_no_personal_data(scraper):
    """plan.md rule 9: the User-Agent is sent to third parties, so no emails."""
    assert "@" not in scraper.session.headers["User-Agent"]


def test_timeout_defaults_to_config(scraper):
    assert BaseScraper().timeout == config.TIMEOUT


def test_delay_defaults_to_config(scraper):
    assert BaseScraper().delay == config.REQUEST_DELAY


def test_overrides_are_respected():
    custom = BaseScraper(delay=0.1, timeout=3, user_agent="test-agent/1.0")
    assert custom.delay == 0.1
    assert custom.timeout == 3
    assert custom.session.headers["User-Agent"] == "test-agent/1.0"


def test_fetch_passes_the_timeout(scraper):
    """A request with no timeout can hang forever, so it must always be set."""
    seen = {}

    def capture(url, timeout=None):
        seen["timeout"] = timeout
        return FakeResponse(b"<html></html>")

    scraper.session.get = capture
    scraper.fetch(URL)
    assert seen["timeout"] == scraper.timeout


# ------------------------------------------------------- politeness delay


def test_fetch_sleeps_after_a_successful_request(monkeypatch):
    slept = []
    monkeypatch.setattr("scrapers.base_scraper.time.sleep", lambda s: slept.append(s))

    polite = BaseScraper(delay=0.5)
    give_response(polite, FakeResponse(b"<html></html>"))
    polite.fetch(URL)

    assert slept == [0.5]


def test_fetch_sleeps_even_when_the_request_fails(monkeypatch):
    """The delay is in a finally block, so a failing server is not hammered."""
    slept = []
    monkeypatch.setattr("scrapers.base_scraper.time.sleep", lambda s: slept.append(s))

    polite = BaseScraper(delay=0.5)
    make_raise(polite, requests.ConnectionError("boom"))
    polite.fetch(URL)

    assert slept == [0.5]


def test_zero_delay_does_not_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr("scrapers.base_scraper.time.sleep", lambda s: slept.append(s))

    give_response(scraper_ := BaseScraper(delay=0), FakeResponse(b"<html></html>"))
    scraper_.fetch(URL)

    assert slept == []


# ------------------------------------------------------------- helpers


def test_select_text_and_attr_return_none_when_absent():
    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    assert select_text(soup, "p.missing") is None
    assert select_attr(soup, "a.missing", "href") is None


def test_select_text_treats_an_empty_element_as_empty():
    soup = BeautifulSoup("<html><p class='x'>   </p></html>", "lxml")
    assert select_text(soup, "p.x") is None


def test_select_attr_returns_none_for_a_list_valued_attribute():
    """class comes back as a list, which is not a usable string value."""
    soup = BeautifulSoup("<html><p class='a b'>x</p></html>", "lxml")
    assert select_attr(soup, "p", "class") is None


# ------------------------------------------------------- context manager


def test_works_as_a_context_manager():
    with BaseScraper(delay=0) as managed:
        give_response(managed, FakeResponse(b"<html></html>"))
        assert managed.fetch(URL) is not None
