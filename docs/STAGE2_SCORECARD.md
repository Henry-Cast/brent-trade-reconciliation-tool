# Stage 2 scorecard

> This guide retains the scoring stage's historical context. References to
> `reports/` and `archive/` mean private local records, not public dependencies.
> Retained measurement tables are in `evidence/latest/`. Install
> `requirements-dev.txt` before using pytest. To run the scorer on seed 1,
> first run `python src/generate.py --seed 1` to create its ignored answer key.

`src/scorecard.py` measures supplied exceptions independently of the engine. It
imports no generator, matching, normalisation, comparison or reconciliation code,
and makes no AI calls. It does not run the engine or change input CSVs.

## Current evidence versus requirements

The scorer remains one of the five unchanged engine/scorer sources; neither the
expiry correction nor the approved CSV price-reader change alters scoring rules.
See `docs/EXPIRY_REALISM.md`. Read the retained November 13, 2026 evaluation in
`evidence/latest/`. Its provenance records original evaluation inputs, not a
freeze of the current generator. Private `reports/` and `archive/` records
describe historical checks and are not required to use or score the tool.

A seeded fixture is required to have 32 positive cases, including two unresolved
review groups, plus 15 harmless cases. That is an acceptance target, not a
measurement. Stop on a failed target; do not retune on benchmark scores. Actual
found/missed/false-alarm/mislabelled/quiet counts must come from supplied engine
outputs and the independent scorer. The November 13, 2026 correction CSVs measured 640 found,
zero missed, zero false alarms, zero mislabelled and 300 correctly quiet across
the 20 seeded datasets. Clean data produced no exceptions and no labelled quiet
cases. Undefined denominators remain `N/A`; fixture success is not production
readiness. The original correction's full test output records 254 passes on each
tested interpreter; that is not a new test run of the CSV price-reader change.

Seeds 1–5 are for development; seeds 6–20 are reserved for evaluation after code,
calendar, settings and tests are frozen, not newly unseen seeds. Do not generate
them in development tests.

## Python interface

```python
summary, details = score_records(results, answers, confirmations)
names = name_resolution_report(answers, matches)
```

Each argument is a list of dictionaries, normally read from its CSV. Each return
value is a pandas DataFrame. `score_records` returns a **two-item tuple**, not a
single table. Every function has a plain-English docstring.

The summary columns are:

`case_type,found,missed,false_alarms,mislabelled,precision,recall,correctly_quiet`

The table always includes the nine expected positive types and four harmless
case types, even when the dataset is empty. Any additional answer or predicted
types remain visible rather than being discarded.

## Exact case identity

- Answer rows sharing `case_id` form one case. Their trade IDs and confirmation
  IDs are unioned independently. Conflicting labels or expected outcomes within
  a case raise `ValueError` rather than selecting the first answer arbitrarily.
- A result's trade set is the union of `trade_id` and `candidate_trade_ids`;
  its confirmation set is the union of `confirm_id` and
  `candidate_confirm_ids`. ID lists use semicolons. Order is irrelevant and
  diagnostic ID lists are sorted. Blank, None and actual NaN values mean empty
  sets. Nonempty identifiers are not case-folded or fuzzy-matched.
- `group_id` is an engine trace label, not a substitute for record IDs. Changing
  it cannot turn partial or incorrect records into a detection.
- **DUPLICATE:** the answer key identifies the extra confirmation, not an
  arbitrarily chosen original. The scorecard expands the expected set to every
  raw confirmation whose trimmed `trade_ref` identifies the expected trade. It requires
  at least two raw confirmation IDs and requires the answer-key confirmation
  to be present in that raw group; otherwise it raises `ValueError`. All of the
  raw IDs must appear in one predicted DUPLICATE row.
- **AMBIGUOUS:** all key rows for the case must be represented in a single
  predicted AMBIGUOUS row. One pair, half a group, extra IDs, or two separately
  emitted pairs do not satisfy the case. AMBIGUOUS is the canonical type;
  NEEDS_REVIEW is its engine outcome, not an alternate break type.
- A detection requires **both exact ID sets and the exact type**. This scorecard
  measures detection identity and classification; it does not certify amount,
  priority, matching rule, field values, or outcome-field correctness. Those
  are engine test responsibilities.

## Metric conventions

- `found`: positive cases satisfied by an exact result. A result can satisfy at
  most one case; duplicate prediction rows are additional false alarms.
- `missed`: positive cases without an exact result.
- `false_alarms`: result rows not used by an exact detection, attributed once to
  the **predicted** type. Unexpected labels are included.
- `mislabelled`: diagnostic subset of missed positive cases with exact IDs but
  another predicted type. All correct field results are reserved first, so a
  legitimate PRICE result is not incorrectly called a mislabelled QUANTITY result
  on a pair with multiple expected fields. A genuinely unmatched wrong-type row
  remains one false alarm on its predicted type. If it has the exact record sets
  of multiple missed cases, each affected case can carry the diagnostic; the
  false-alarm event is still counted only once. The diagnostic is not an additional
  false alarm.
- `precision = found / (found + false_alarms)`.
- `recall = found / (found + missed)`.
- A zero denominator is the literal string `N/A`, in the console and CSV, not
  zero or an invented perfect score. Other precision and recall values are
  fractions between zero and one.
- `NO_BREAK` cases never increase found or missed. `correctly_quiet` counts
  those for which **no result touches any expected trade or confirmation ID**.
  An alert on the wrong counterpart still spoils quietness if either ID
  overlaps. Quietness failures do not add false alarms to the expected trap
  type: the emitted event is already counted once under its predicted type.
- An empty clean answer key provides no labelled quiet cases; correctly_quiet
  is zero, not a count of all unlabelled clean records. Its precision and recall
  denominators are zero. Unexpected alerts on that dataset still count as
  false alarms.

## Error details

The details columns are:

`status,case_id,expected_type,predicted_type,result_index,trade_ids,confirm_ids,reason`

Statuses are FOUND, MISSED, CORRECTLY_QUIET, INCORRECTLY_ALERTED and FALSE_ALARM.
`result_index` is the zero-based result-list position (first CSV data row = 0).
A missing case without an exact wrong-label prediction shows its expected IDs;
a linked result or false alarm shows the predicted IDs. Thus a partial group
has a MISSED row with the complete expected sets and a FALSE_ALARM row with
what was actually emitted.

Details are a diagnostic log, **not** an additive metric ledger: a wrong-label
result appears in its expected miss and its single false-alarm row. An alert
spoiling quietness appears in both the quiet-case diagnostic and its single
false-alarm row. Summary counts, not detail row totals, define the metrics.

## Counterparty-name resolution

`name_resolution_report` returns columns `counterparty_resolution,count`, with
rows GENERAL_RULES, ALIAS_TABLE and UNRESOLVED. It filters the answer key to
planted COUNTERPARTY_VARIANT cases and looks for their **actual exact trade and
confirmation pair** in matches. It does not count methods across all matched
trades, infer a method from candidate lists, or recompute name normalisation.
Repeated identical traces count once per planted case. No matching pair,
missing/unrecognised method, or contradictory method traces count as UNRESOLVED.
A dataset without planted variants has three zero counts.

The generator policy plants two variants using
`trade[field].upper().replace(" LTD", " LIMITED")` and two shortened trading names
requiring configured aliases. This report does not assume
whether general rules or the alias table resolves them: it reports the supplied
matches trace.

## Command line

All seven paths are required. Output parent directories must already exist.
Header-only inputs are supported, but required schema columns must be present.
The command rejects output paths that resolve to an input or another output.
It writes summary, details and name counts, and prints both summary tables.

```bash
.venv/bin/python src/scorecard.py \
  --results path/to/results.csv \
  --answer-key path/to/answer_key.csv \
  --confirmations path/to/confirmations.csv \
  --matches path/to/matches.csv \
  --output path/to/scorecard.csv \
  --details path/to/scorecard_details.csv \
  --name-report path/to/name_resolution.csv
```

Minimum CSV columns used by the command:

- results: `trade_id,confirm_id,break_type` (candidate ID columns optional).
- answer key: `case_id,trade_id,confirm_id,case_type,expected_outcome`.
- raw confirmations: `trade_ref,confirm_id`.
- matches: `trade_id,confirm_id,counterparty_resolution`.

Extra engine columns are accepted and do not alter scoring.

## Independent verification

```bash
TMPDIR="$PWD/.cache" PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest tests/test_scorecard.py -q \
  --basetemp=.cache/pytest-scorecard \
  -o cache_dir=.cache/pytest_cache_scorecard
```

The tests use synthetic adversarial records and command-line fixtures under the
project-local pytest temporary directory. They never run the engine, regenerate
Stage 1 data, or treat fixture scores as measured engine performance.
