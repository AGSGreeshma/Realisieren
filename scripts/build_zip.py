"""Build the submission ZIP from the project folder.

Run with:  python scripts/build_zip.py

Writes <NAME>_scraping_assignment.zip into the folder ABOVE the project, so the
archive is never inside the tree it is archiving. Everything goes under a single
top-level folder so extracting it does not scatter files.

The include rule is "everything except the exclusions below", which keeps it
honest: a new source file is included automatically rather than being forgotten.
"""

# Running this as "python scripts/build_zip.py" puts scripts/ on the import
# path, not the project root, so "import config" would fail. Add the root.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import zipfile

SUBMITTER = "AGSGreeshma"

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = PROJECT_ROOT.name  # top-level folder inside the ZIP
ZIP_PATH = PROJECT_ROOT.parent / f"{SUBMITTER}_scraping_assignment.zip"

# Directory names skipped anywhere in the tree
EXCLUDE_DIRS = {
    "venv",
    ".venv",
    ".git",
    "data",              # development-only raw scrape cache
    "__pycache__",
    ".pytest_cache",
    ".vscode",
    ".idea",
}

# File suffixes skipped anywhere in the tree
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}

# Exact filenames skipped
EXCLUDE_NAMES = {".env", ".DS_Store", "Thumbs.db"}


def should_include(path: pathlib.Path) -> bool:
    """True if this file belongs in the submission."""
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDE_DIRS for part in relative.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    return True


def collect() -> list[pathlib.Path]:
    """Every file to include, sorted for a stable archive order."""
    return sorted(
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file() and should_include(path)
    )


def main() -> int:
    files = collect()
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            arcname = pathlib.PurePosixPath(ARCHIVE_ROOT) / path.relative_to(
                PROJECT_ROOT
            ).as_posix()
            archive.write(path, str(arcname))

    total_raw = sum(path.stat().st_size for path in files)
    print(f"wrote {ZIP_PATH}")
    print(f"  files      : {len(files)}")
    print(f"  uncompressed: {total_raw:,} bytes ({total_raw / 1024 / 1024:.2f} MB)")
    print(f"  zip size   : {ZIP_PATH.stat().st_size:,} bytes "
          f"({ZIP_PATH.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
