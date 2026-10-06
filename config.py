"""Central settings for the scraping pipeline. Values only, no logic."""

from pathlib import Path

# --- Project root: the folder this file lives in, so all paths work from anywhere ---
BASE_DIR = Path(__file__).resolve().parent

# --- Source sites ---
BOOKS_BASE_URL = "https://books.toscrape.com/"      # Books listing entry point (page 1)
QUOTES_BASE_URL = "https://quotes.toscrape.com/"    # Quotes listing entry point (page 1)

# --- Politeness and reliability ---
REQUEST_DELAY = 0.5                                 # Seconds to wait between requests
TIMEOUT = 10                                        # Seconds before a request is abandoned
MAX_RETRIES = 3                                     # Extra attempts after the first failure
BACKOFF_FACTOR = 1.0                                # Retry waits: 0s, 2s, 4s (urllib3 skips the first backoff)
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]      # Server-side codes worth retrying

# --- Identify ourselves honestly to the servers (no personal data: this header is public) ---
USER_AGENT = "scraping-assignment/1.0 (educational take-home project; Python requests)"

# --- Directories for generated files ---
OUTPUT_DIR = BASE_DIR / "output"                    # Where CSV and JSON results are written
LOG_DIR = BASE_DIR / "logs"                         # Where the run log is written

# --- Generated files ---
FINAL_CSV = OUTPUT_DIR / "final_dataset.csv"        # Consolidated, validated dataset
REJECTED_CSV = OUTPUT_DIR / "rejected_records.csv"  # Records that failed validation, with reasons
SUMMARY_JSON = OUTPUT_DIR / "summary_report.json"   # Run statistics and data-quality counts
LOG_FILE = LOG_DIR / "scraper.log"                  # Full run log (INFO / WARNING / ERROR)
