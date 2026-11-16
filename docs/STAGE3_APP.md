# Brent Trade Reconciliation Tool — interface guide

> Verification paragraphs below describe the original interface and
> expiry-correction stages. Raw `reports/` and `archive/` are private records,
> not public dependencies. See `evidence/latest/` for retained November 13, 2026
> scores, not a new benchmark of the CSV price-reader change. No hosted
> deployment is claimed.

**Prices are simulated, anchored to published Brent spot prices.**

The main interface and browser title are both **Brent Trade Reconciliation Tool**.
The approved generator correction is explained in `docs/EXPIRY_REALISM.md` and
`docs/SETTINGS.md`: selected October 2026 dates use December 2026, January 2027
and February 2027, with zero-based front-rank month components $0.00, -$0.15
and -$0.30/bbl before independent noise. Unknown confirmations and planted
CONTRACT_MONTH alternatives stay within the same three tradable months.
Date-only expiry-day trades are assumed before the cutoff, not intraday-verified.
The five protected engine/scorer sources are unchanged; the generator is not
part of that five-file freeze.

## Start and stop

From a fresh project copy, follow the main README to create a Python 3.14
virtual environment and install `requirements.txt`, then activate it and run:

```bash
streamlit run app.py
```

Open the local address printed by Streamlit and stop the foreground server with
Ctrl+C. No custom launcher is required. The optional `scripts/start_app.sh`
still uses `.venv`, binds locally and redirects caches inside the project;
it is not the clean-start proof. Streamlit remains pinned to 1.50.0.

## Two input routes

- **Upload files:** select blotter and confirmations CSVs, then click
  **Reconcile uploaded files**. CSVs must be UTF-8 (a BOM is allowed), have the
  specified columns, and contain data. Invalid dates, numbers, quantities, units,
  sides or identifiers get a message naming the file role, row and column.
  Row 1 is the header; row 2 is the first record. Missing columns, empty files and
  wrong file types are also rejected. Fix the file and upload it again.
- **Generate data:** enter a non-negative integer seed and click **Generate new
  dataset**. The CSV-reading generator and unchanged engine run. Use development
  seeds 1–5. The same seed, settings, read-only `data/brent_spot.csv`, verified
  calendar, code and environment give the same dataset. Unsupported
  calendar dates fail clearly rather than using guessed holidays. Seeds 6–20
  are reserved until code/calendar/settings/tests freeze; they were previously
  seen, not newly unseen data.

Changing the route, uploaded inputs or seed clears prior results and score access.
A failed run does not leave a previous run's summary on screen after rerender.

## Read the results

- **Trades processed:** number of blotter records.
- **Matched trades:** number of distinct trade IDs in the engine's established
  matches. A duplicate confirmation must not count a desk trade twice.
- **Established pairs:** number of match-audit rows, including extra confirmations.
- **Review groups:** unresolved groups, not guessed pairings.

The total **value of discrepancy** is accompanied by a count-and-value table by
break type. The engine uses different valuation bases for different types;
read the breakdown rather than treating the total as a standalone conclusion.
The adapter sums only amounts already emitted by the engine, using Decimal.
Review items have blank values and are excluded. A genuinely clean run has zero.

The exception table initially orders HIGH, then STANDARD by descending value,
then REVIEW. Use **Sort exceptions** for exact numeric value sorting. Table
headers also sort displayed columns; a formatted currency-text header is not a
substitute for the exact-value sort control.

Choose **Exception to inspect** to see original records side by side. Highlighted
fields come from the engine's affected-field metadata, not a second comparison
algorithm. Volume differences highlight quantity and unit. Wrong contract months
are labelled **Wrong delivery month**. Duplicate groups show all confirmations;
reviews show every candidate and explicitly avoid choosing a pairing.

## Scorecard restrictions

The **Scorecard** page appears only for a dataset generated in the current app
session. Uploading previously generated CSVs still counts as an upload and does
not grant scorecard access. Only the existing scorer reads the generated answer
key. Results are measured once for the current run, then cached in session memory.
The required caveat is shown verbatim:

> Correct against its specification on generated data with known answers. Not evidence of production readiness.

## Temporary storage and collisions

Each browser session owns a `TemporaryDirectory` under ignored
`.app_sessions/session-.../`. Each run gets another uniquely named folder.
The session holds that resource alive; **Clear session** explicitly removes it.
Garbage collection or host shutdown can also remove temporary resources. They
are not an archive, and browser-disconnect cleanup timing is framework-managed.
If the workspace disappears while the app is open, the next rerender clears the
old run and asks for fresh inputs. A new session recreates its workspace.

The generator's sole market-price input is the read-only `data/brent_spot.csv`,
with 22 published October 2026 observations. The adapter copies that CSV,
settings **and `data/ice_brent_expiry_calendar.json`** into the private run folder
and starts a separate Python process. That process redirects only its own
generator ROOT to the private folder; it does not prepare or rewrite shared
prices. It runs the corrected expiry/month and zero-based pricing logic, with
preserved safety guards and the original retry policy. No shared ROOT mutation
happens in Streamlit threads. The historical source workbook is not copied or
read at runtime, and `xlrd` is not required. Calendar lookup is local, with no
generation-time network call.

A collision rejects the sampled dataset before reconciliation. Accepted runs
retain the original `generation_metadata.json`; retries are visible in the app.
Do not assume a particular seed needs a particular number of attempts: the
old seed-12 retry history is historical only. Exhausting 100 attempts gives a
clear message asking for another seed. A child-process
timeout also gives a clear message. The app does not regenerate based on scores.

This uses ephemeral writable runtime storage. The original expiry-correction
adapter and AppTest checks passed for concurrent private generation,
temporary-workspace removal and retry errors; their logs remain private local
records. Those historical checks do not verify the later CSV price-reader
change. No Community Cloud deployment or future-hosting compatibility is claimed.

## File walkthrough

| File | What it does |
|---|---|
| `app.py` | Streamlit controls, navigation, summaries, tables and highlighted record views. |
| `app_support.py` | Validates uploads, owns temporary workspaces, calls the unchanged engine entrypoint and scorer, aggregates emitted values and prepares display metadata. |
| `scripts/generate_for_app.py` | Isolates the corrected generator's file paths in a separate process. |
| `scripts/start_app.sh` | Starts the app with project-local caches and the unchanged project interpreter. |
| `scripts/check_stage3_hashes.py` | Checks only the five protected engine/scorer hashes; writes `reports/expiry_realism/hash_check.txt`. |
| `tests/test_app_support.py` | Nonvisual validation, actual engine calls, private-calendar generation and forced error-path tests using development seeds. |
| `tests/test_app_ui.py` | AppTest coverage for rendered flows, the exact main/browser-title configuration and UI error boundaries. |
| `tests/test_expiry_realism.py` | Independent calendar, front-based pricing, delivered-month and protected-hash-command regressions. |
| `.streamlit/config.toml` | Disables telemetry and detailed error displays, sets headless mode and the upload limit. |
| `requirements.txt`, `.gitignore` | Pin Streamlit; exclude private sessions, environments and caches. |
| `evidence/latest/` | Retained November 13, 2026 evaluation tables and original evaluation provenance. |

## Verification and limits

The original expiry-correction suite passed 254 cases on both the existing Python
3.9.6 and separate Python 3.14.9 environments. This is not a new suite run for
the CSV price-reader change. No Python upgrade was performed. AppTest verified
the exact visible heading and page-title configuration. Full logs, named changes
and matching five-file hashes remain private in `reports/expiry_realism/`;
published score tables are in `evidence/latest/`.
The earlier 226-case suite, old 20-file Stage 3 snapshot, browser logs and
screenshots remain historical under `archive/pre_expiry_realism_correction/`.

AppTest upload tests inject bytes only at the widget boundary, then exercise
actual validation, engine calls and rendered errors. Historical browser checks
used native file inputs; no new native-browser check was performed for this
correction. Neither those old screenshots nor AppTest are a claim of human
acceptance testing, broad device coverage or hosted deployment. The native
Streamlit grid CSV toolbar remains unchanged; there is no Excel-report export.

```bash
python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv-modern/bin/python -m pytest
.venv/bin/python scripts/check_stage3_hashes.py
.venv/bin/python -m pip check
```

## Three understanding questions

1. Why can extra duplicate confirmations increase established pairs without
   increasing the number of distinct matched trades?
2. Why should you read the break-type count-and-value table beside the total,
   and why is a review item's value blank rather than zero?
3. What happens when a generated sample collides, and why can't an uploaded pair
   of files show the same known-answer scorecard?

The interface has no AI explanations or Excel-report export. This guide does
not claim a hosted deployment.
