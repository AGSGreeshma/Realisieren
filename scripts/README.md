# scripts/

Development and verification tools, not part of the pipeline. `main.py` does
not import anything from here, and nothing here is needed to run the project.

Run them from the **project root**, not from inside this folder:

| Script | What it does |
|---|---|
| `python scripts/verify_output.py` | Re-reads `output/final_dataset.csv` with the stdlib `csv` module and re-derives every count, type and range independently of the pipeline's own code, then re-fetches 5 rows from the live sites and compares them field by field. Add `--no-spot-check` to run fully offline. |
| `python scripts/try_failure.py` | Monkeypatches the scrapers at runtime to force four failure modes (a 404 listing page, a scraper that raises, both sources failing, and the only selected source failing) and shows that the run is logged, recorded in the summary, and exits with the right code. |
| `python scripts/try_books.py` | Scrapes two pages of Books against the live site, prints the raw records and stats, exercises three broken-URL cases, and projects how long a full run takes from the measured request rate. |
| `python scripts/build_zip.py` | Builds the submission archive into the folder above the project. Includes everything except `venv/`, `.git/`, `data/`, `__pycache__/`, `.pytest_cache/`, IDE folders and `*.pyc`, so a newly added source file is picked up automatically rather than forgotten. |

## Warning

`try_failure.py` **overwrites `output/` and `logs/scraper.log`**, because it runs
the real pipeline four times. The files currently in `output/` are the final
results of a complete run; regenerating them means re-running
`python main.py` (about 19 minutes).

`verify_output.py` and `try_books.py` only read, so both are safe to run.
