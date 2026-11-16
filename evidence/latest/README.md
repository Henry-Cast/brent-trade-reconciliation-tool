# Latest scored evaluation

These six CSV tables are byte-identical copies of the latest expiry-corrected evaluation frozen on November 13, 2026. They are not a new unseen benchmark or a fresh scoring run performed for publication. The original raw commands, logs and superseded archive stay private.

- `run_summary.csv`: every seed and clean control, including split and actual retries.
- `totals.csv`: measured split totals, ratios and emitted value of discrepancy.
- `scorecards.csv`: per-dataset, per-case-type scoring.
- `value_by_break_type.csv`: count and value by type; review amounts remain blank.
- `matching_rules.csv`: established-pair rule counts.
- `name_resolution.csv`: observed general-rule and alias-table resolution counts.
- `provenance.json`: original table digests, evaluation date and `evaluation_inputs` hashes for the original evaluated inputs and generator. These are historical evaluation hashes, not a freeze of the current generator or a list of current runtime dependencies.
- `market_basis.json`: separately researched October spot-versus-fixed-contract chart comparison, including its measurement-basis limitation and official source URLs.

The five engine/scorer modules remain unchanged. The approved generator price-reader plumbing now uses the read-only `data/brent_spot.csv` (22 October 2026 observations) as its sole market-price input, with calendar JSON and settings still required. The app subprocess receives private copies of those three inputs. The original source workbook is retained privately as provenance, not distributed or read at runtime; `xlrd` is not a runtime dependency.

These preserved scores belong to the original November 13, 2026 expiry-corrected evaluation, not a new all-20-seed benchmark of the CSV price-reader change. Local verification reports are private records, not public dependencies. Read the measurement tables in this directory; they have not been rewritten to imply a new evaluation.

Correct against its specification on generated data with known answers. Not evidence of production readiness.
