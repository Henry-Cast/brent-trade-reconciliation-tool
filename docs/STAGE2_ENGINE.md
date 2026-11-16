# Stage 2 — command-line reconciliation engine

> This guide includes the engine stage's historical verification. `reports/`
> and `archive/` paths below describe private local records, not public
> dependencies. Retained measurement tables are in `evidence/latest/`. Follow
> the main README for installation, and install `requirements-dev.txt` before
> running tests.

**Prices are simulated, anchored to published Brent spot prices.**

A break is a disagreement between a desk trade and a broker confirmation. The
engine first decides which records belong together, then checks whether they
agree. It contains ordinary deterministic Python, not AI calls.

## Realism correction and evidence boundary

The five engine/scorer source files remain unchanged. The generator received the
expiry correction and now reads `data/brent_spot.csv` as its sole market-price
input: 22 published October 2026 observations, used read-only. The historical
source workbook is provenance, not a public or runtime dependency; no `xlrd` is
needed at runtime. Calendar JSON and settings remain required inputs. There is
no new engine expiry-validation rule.
`docs/EXPIRY_REALISM.md` describes the verified calendar, December 2026–February
2027 months for selected October dates, zero-based front-rank pricing and stop
rule. Earlier datasets and measured reports remain in the private historical
archive. The retained November 13, 2026 correction results are in
`evidence/latest/`: each of the 20 seeded datasets measured 32 correctly
found cases with no misses, false alarms or mislabels, and clean data established
200 pairs without exceptions. That correction's 254-test suite passed on both
local Python environments. These are preserved results, not a new all-20-seed
benchmark or test run for the CSV price-reader change. Fixture results do not
establish production readiness.

## Run the engine

From the project root:

```bash
.venv/bin/python src/reconcile.py \
  --blotter data/generated/seed_1/blotter.csv \
  --confirmations data/generated/seed_1/confirmations.csv \
  --results data/generated/seed_1/results.csv \
  --matches data/generated/seed_1/matches.csv
```

Repeat with development seeds `seed_2` through `seed_5`, or `clean`.
Seeds 6–20 are reserved for evaluation only after the correction freeze; they
were previously seen and must not be described as newly unseen. The engine receives explicit
file paths, not a folder to scan. It has no answer-key argument and does not
import the generator or scorecard. Its outputs cannot overwrite the supplied
inputs or settings; paths must stay inside this project. Stage 1 CSVs are not
changed by reconciliation. Tests install a Python file-open audit hook which
blocks every answer-key read, first prove that the hook catches a deliberate
probe, and then verify the engine makes zero attempts. Malformed, changed, and
absent answer keys produce identical engine results.

The command prints observed counts. The actual exceptions go to `results.csv`;
every established pair, including clean pairs, goes to `matches.csv`.

## The six rules, in order

### 1. Normalise: put both records into the same language

Keep the original values for explanation, but compare cleaned values. Trim
spaces; standardise side and unit capitals; parse ISO trade dates and contract
months; convert lots to barrels. For example, 5 LOTS and 5,000 BBL have the same
volume. Prices and quantities are parsed directly from strings into `Decimal`,
not through binary floating point. Bad dates, invalid units, non-positive or
non-finite numbers, and duplicate record IDs stop the command rather than being
guessed into a different meaning. IDs retain their case and are trimmed; their
literal token is not otherwise rewritten.

Counterparty resolution tries general rules first: Unicode text standardisation,
capitals, punctuation replaced by spaces, repeated spaces collapsed, and a final
`LIMITED` converted to `LTD`. Thus `Fictional Energy Ltd` and
` FICTIONAL  ENERGY, LIMITED. ` become the same name without an alias.

If general names still disagree, compare their explicitly configured alias
forms. No fuzzy similarity score or invented company mapping is used. In real
use, **the alias table must be maintained by hand**, with business review of
which names really represent the same counterparty.

The hardened generator creates two planted variants with
`.upper().replace(" LTD", " LIMITED")` and two with explicit shortened trading
names which require the configured manual aliases. The scorecard, not the engine, identifies
which pairs were planted variants and counts `GENERAL_RULES`, `ALIAS_TABLE`, and
`UNRESOLVED` outcomes using the pair audit. Redundant identity aliases in the
Stage 1 settings are not needed to resolve Ltd/Limited.
The retained name reports in `evidence/latest/` measured two
GENERAL_RULES and two ALIAS_TABLE resolutions per seeded dataset: 40 of each
across the 20 datasets, with none unresolved. These counts are read from actual
traces, not inferred from planted intent. Earlier measured name counts
and hardening reports are historical, under
`archive/pre_expiry_realism_correction/`. The retained
`reports/stage2_hardening/freeze.json` is only a protected-source hash reference.

### 2. Reference: start with the desk trade number

If a confirmation quotes an existing `trade_id`, pair it to that trade even if
price, volume, side, or month disagrees. Those differences are checked later.
An absent or nonexistent reference does not identify a trade, so that record
continues to attribute matching. Retain every confirmation referencing a trade:
never drop a repeated reference or label one confirmation as the original.

`matches.csv` records this as `RULE_2_REFERENCE`.

### 3. Attributes: use the identifying details when the reference cannot help

For leftover records require equal date, resolved counterparty, side, contract
month, barrel volume, and price within $0.01/bbl. Exactly one candidate establishes
a pair. Price distances inside tolerance are treated equally; no undocumented
closest-price tie-break is used.

Unique candidates are processed in deterministic rounds rather than file order.
Any remaining connected set of equally plausible alternatives becomes one review
group; all its candidate IDs are retained. Those records are not later reported
again as missing or unknown. For two identical trades and two identical blank-ref
confirmations, the engine reports one unresolved group, not two guessed pairs.

Established pairs or unresolved candidate groups record `RULE_3_ATTRIBUTES`.
A rule on a review row describes the candidate search, not an established pairing.

### 4. Near matches: allow just one financial attribute to disagree

Only leftover records are considered. Date and resolved counterparty must still
agree. Exactly one of side, contract month, volume, or price outside tolerance
may differ. For example, a blank-ref confirmation with matching attributes except
BUY versus SELL can pair uniquely, then produce a SIDE break.

One candidate establishes a pair; equally plausible alternatives need review.
Two changed financial attributes do not qualify. Price differences of exactly
$0.01 remain inside tolerance; $0.02 is outside. The rule is
`RULE_4_NEAR_MATCH`. Generated-data performance does not prove every rule branch;
independent fictional tests specifically exercise each permitted near-match field,
multiple candidates, rejected two-field matches, and input-order invariance.

### 5. Compare: pairing does not mean agreement

Compare each established pair. Price differences over tolerance produce PRICE;
unequal barrel volumes produce QUANTITY, except equal numeric quantities with
different units and unequal volumes produce UNIT_ERROR instead. Equivalent units
produce neither. Different side or delivery month produces its corresponding
break. More than one differing financial field means one row per field.

The result retains the original pairing rule and separately records
`RULE_5_COMPARE` as its detection rule. Every value follows SPEC section 8 using
the desk's volume and price where specified. USD display is rounded only at the
end, to cents with decimal half-up rounding. Do not call discrepancy value a
realised loss or P&L, and do not assume separate overlapping field values can be
added into a loss estimate.

### 6. Account for leftovers and repeated confirmations

An unpaired desk trade is MISSING_CONFIRMATION; an unpaired confirmation is
UNKNOWN_CONFIRMATION. Their value is their own full notional. A review group's
reserved records are not leftovers.

Multiple confirmations established for one trade produce **one DUPLICATE row**
listing every involved ID, separated by semicolons. With identical notionals,
three confirmations mean two extra notionals. No original confirmation is chosen.
The pair audit still contains all individual established pair relationships.

Leftovers record `RULE_6_LEFTOVER`. Duplicate results preserve the pairing rule(s)
and separately record `RULE_6_DUPLICATE` as the detection rule.

## Result conventions

`results.csv` has the requested IDs, break type, both values, discrepancy USD,
priority, and pairing rule, plus group/candidate IDs, outcome, affected field,
and detection rule. DUPLICATE and AMBIGUOUS group rows contain all trade IDs and
all confirmation IDs as sorted semicolon lists. Review rows use type AMBIGUOUS,
outcome NEEDS_REVIEW, a blank monetary value, priority REVIEW, and no guessed pair.
Original source records for reviews and leftovers are retained as JSON text inside
the appropriate CSV value cells.

Rows sort HIGH first, STANDARD next by descending monetary value, REVIEW last.
HIGH rows also sort by descending monetary value; IDs/type provide stable ties.
SIDE, MISSING_CONFIRMATION, UNKNOWN_CONFIRMATION, and DUPLICATE are always HIGH.
Other valued financial breaks are STANDARD. Clean data still produces headers.

## Stop rather than silently extend the specification

The command refuses unsupported reference-linked date/counterparty disagreements
and paired trader/broker disagreements because the approved spec supplies no
break type and value for them. It also refuses a duplicate group with unequal
confirmation notionals: valuing which confirmation was extra would require a
choice of original which the user explicitly forbids. These conditions raise a
clear stop-for-clarification error before outputs are written. Synthetic negative
tests prove the stop paths. They are not silently reclassified as a known break.

## Files

- `src/normalise.py`: input validation, exact numbers, general names, alias fallback.
- `src/match.py`: reference matching, attribute matching, and unresolved groups.
- `src/compare.py`: field differences, group/leftover exceptions, valuation, priority.
- `src/reconcile.py`: explicit-path command-line entry point and CSV writing.
- `tests/test_normalise.py`: normalisation and manual-alias examples.
- `tests/test_match.py`: matching order, candidates, references, and ambiguity.
- `tests/test_compare.py`: financial formulas, grouping, and output conventions.
- `tests/test_engine_boundaries.py`: additional ordering, tolerance, and stop cases.
- `tests/test_reconcile.py`: real CLI and answer-key isolation audit.
- `tests/conftest.py`: hand-written fictional test records, not generated labels.

## Three understanding questions

1. Why can a reference establish a pair even when its side or volume disagrees,
   and why must that pair still be compared?
2. What distinguishes an exact attribute match, a permitted one-field near match,
   and a group the engine must leave unresolved?
3. Why must the engine retain every duplicate ID, and why is a review's blank
   discrepancy value different from a measured discrepancy of zero?
