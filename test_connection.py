"""Throwaway Phase 1 check: confirm both sites respond and that every selector
in plan.md Section 6 actually finds what we expect. Not part of the final pipeline.

Run with:  python test_connection.py
"""

import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config

MISSING = "MISSING"


def fetch(url):
    """GET a URL with our settings and return a parsed soup plus the status code."""
    response = requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.TIMEOUT,
    )
    # The sites declare the wrong charset, so force UTF-8 before touching .text
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "lxml")
    return soup, response.status_code


def text_of(node, selector):
    """Return the stripped text of the first match, or MISSING if there is none."""
    found = node.select_one(selector)
    return found.get_text(strip=True) if found else MISSING


def attr_of(node, selector, attribute):
    """Return one attribute of the first match, or MISSING if absent."""
    found = node.select_one(selector)
    if not found or not found.has_attr(attribute):
        return MISSING
    return found[attribute]


def absolute_next(soup, current_url):
    """Build the absolute 'next page' URL, or MISSING on the last page."""
    href = attr_of(soup, "li.next > a", "href")
    if href is MISSING:
        return MISSING
    # Join against the CURRENT page URL, not the site root (see notes below)
    return urljoin(current_url, href)


def check_books_listing():
    """Books home page: counts, first record's fields, next-page link."""
    print("\n=== BOOKS LISTING ===")
    url = config.BOOKS_BASE_URL
    soup, status = fetch(url)
    print(f"url            : {url}")
    print(f"status_code    : {status}")

    pods = soup.select("article.product_pod")
    print(f"product_pod    : {len(pods)}")
    if not pods:
        print("no books found - selectors need rechecking")
        return MISSING

    first = pods[0]
    print(f"full title     : {attr_of(first, 'h3 > a', 'title')}")
    print(f"visible title  : {text_of(first, 'h3 > a')}")
    print(f"raw price      : {text_of(first, 'p.price_color')}")

    stars = first.select_one("p.star-rating")
    print(f"rating class   : {stars['class'] if stars else MISSING}")

    detail_href = attr_of(first, "h3 > a", "href")
    detail_url = MISSING if detail_href is MISSING else urljoin(url, detail_href)
    print(f"raw detail href: {detail_href}")
    print(f"detail url     : {detail_url}")
    print(f"next page url  : {absolute_next(soup, url)}")
    return detail_url


def check_book_detail(detail_url):
    """Book detail page: breadcrumb category, description presence, availability."""
    print("\n=== BOOK DETAIL ===")
    if detail_url is MISSING:
        print("skipped - no detail url from the listing")
        return

    soup, status = fetch(detail_url)
    print(f"url            : {detail_url}")
    print(f"status_code    : {status}")
    print(f"category       : {text_of(soup, 'ul.breadcrumb li:nth-of-type(3) a')}")

    description = soup.select_one("#product_description + p")
    print(f"has description: {description is not None}")
    if description:
        snippet = description.get_text(strip=True)[:80]
        print(f"description[80]: {snippet}...")

    print(f"availability   : {text_of(soup, 'p.availability')}")


def check_quotes_listing():
    """Quotes home page: counts, first record's fields, next-page link."""
    print("\n=== QUOTES LISTING ===")
    url = config.QUOTES_BASE_URL
    soup, status = fetch(url)
    print(f"url            : {url}")
    print(f"status_code    : {status}")

    quotes = soup.select("div.quote")
    print(f"div.quote      : {len(quotes)}")
    if not quotes:
        print("no quotes found - selectors need rechecking")
        return

    first = quotes[0]
    print(f"quote text     : {text_of(first, 'span.text')}")
    print(f"author         : {text_of(first, 'small.author')}")

    author_href = attr_of(first, 'a[href^="/author/"]', "href")
    author_url = MISSING if author_href is MISSING else urljoin(url, author_href)
    print(f"author url     : {author_url}")

    tags = [tag.get_text(strip=True) for tag in first.select("a.tag")]
    print(f"tags           : {tags if tags else MISSING}")
    print(f"next page url  : {absolute_next(soup, url)}")


def main():
    """Run every check, pausing politely between requests."""
    detail_url = check_books_listing()

    time.sleep(config.REQUEST_DELAY)
    check_book_detail(detail_url)

    time.sleep(config.REQUEST_DELAY)
    check_quotes_listing()

    print("\nconnection check finished")


if __name__ == "__main__":
    main()
