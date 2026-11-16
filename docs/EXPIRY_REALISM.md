# Approved Brent expiry-realism policy

> This records the approved correction and its historical evidence. Raw
> `reports/` and the superseded `archive/` remain private and are not required
> by a public checkout. Retained measurement tables are in `evidence/latest/`.
> The hash checker reads portable, immutable references from
> `tests/fixtures/hash_references/` and creates its ignored output directory
> automatically. No deployment has been performed.

**Prices are simulated, anchored to published Brent spot prices.**

This is a generator-only teaching-data correction, not a new matching rule,
futures-pricing model or live-market feed. The five engine/scorer sources stay
unchanged. The exact main and browser title is **Brent Trade Reconciliation Tool**.

## Exchange rule and verified local dates

ICE product 219 specifies that trading ends at the end of the designated
settlement period on the last ICE Business Day of the second month before the
contract month. If that would be the Business Day immediately before Christmas
Day or New Year's Day, use the preceding Business Day instead.[1]

Private local records retain the saved product text, retrieval hashes and
calendar verification materials under `reports/expiry_realism/sources/`.
They document historical verification, not public runtime dependencies.

The generator uses `data/ice_brent_expiry_calendar.json`, a locally saved,
verified calendar. No package is added to the app and no network lookup occurs
at generation time. Do not replace the calendar with a generic weekday check,
a guessed holiday rule or a silent fallback. Fail clearly if the trade date,
front month or its next two months cannot be resolved inside verified coverage.

The approved calendar scope is trade dates **2026-09-01 through 2026-12-31**,
with expiry rows for contract months **November 2026 through May 2027**. The
calendar file and its saved verification evidence, not this prose, are the
authority for individual dates. Extending coverage requires verified new data
and tests before use; it must not happen automatically during generation.

Trade records contain a date only. On an expiry date, assume a generated trade
occurs before the designated cutoff and allow the expiring month. Roll the front
month after its expiry date. This assumption is not verification of an actual
intraday trade time. The engine does not gain a new expiry-validation rule.

## Allowed months

Find the front still-tradable contract using that calendar, then take its next
two consecutive contract months. For the selected published October 2026 trade
dates the set is **December 2026, January 2027 and February 2027**. Base trades
and unknown confirmations both use that set. A planted CONTRACT_MONTH error
changes to another month in the same set, not an expired or arbitrary month.

## Simulated price basis

For each normally drawn trade or unknown confirmation:

```text
simulated price = published spot for the trade date
                + configured month adjustment × zero-based rank from front
                + independent seeded noise
```

| Month rank | Meaning | Month component at setting -0.15 USD/bbl |
|---:|---|---:|
| 0 | Front still-tradable contract | $0.00/bbl |
| 1 | Next contract month | -$0.15/bbl |
| 2 | Third contract month | -$0.30/bbl |

Noise ranges from -$0.10 to +$0.10/bbl and is sampled independently of month
selection. Rank is **not** the number of months after the trade's calendar month.
The configured value remains `"contract_month_adjustment_usd_bbl": "-0.15"`.
Exact cents/Decimal arithmetic remains in use. Independent noise can obscure
ordering between individual noisy trade prices. Planted breaks and harmless
rounding traps then make their specified record changes; do not misread a
modified confirmation as a new observed futures quote.

This slope is a teaching assumption, not measured backwardation, fair value,
an observed futures curve or a price forecast. The published anchor remains EIA
Brent spot; source observations are not invented, filled or replaced. The current
generator reads the 22 published October 2026 observations in
`data/brent_spot.csv` as its sole market-price input, without rewriting that CSV.
The original source workbook is retained privately as historical provenance,
not distributed or parsed during generation; no `xlrd` is needed at runtime.
Calendar JSON and settings remain required alongside the price CSV.

## Preserved fixture and retry rules

Keep all specified case counts, unique identifiers, Decimal comparisons,
tolerance-aware collision guards, orphan safety, five unique blank-reference
near-match cases and name-alias guards. Unknown confirmations remain independent
draws screened against the entire blotter, not against only missing trades.

Keep the original maximum of 100 full sampling attempts. Reject unsafe samples
before engine/scorer execution, record actual rejection reasons and accepted
attempt counts in `generation_metadata.json`, and stop clearly if exhausted.
Do not choose a dataset by its engine score. An old seed's exact retry count is
historical and is not promised for corrected sampling. Test retry behavior with
controlled failure injection, not a reserved evaluation seed.

The app's isolated generator receives private copies of the price CSV, settings
**and calendar JSON** in each run workspace. It does not copy a workbook or
prepare shared price output. Streamlit threads must not mutate shared generator
paths.

## Evaluation boundary and stop rule

`evidence/latest/` contains the retained November 13, 2026 correction evaluation.
Original raw logs in private `reports/expiry_realism/` record source hashes,
test changes, collected totals, runs on Python 3.9.6 and Python 3.14.9,
regenerated-file checks, independent scorecards and generation metadata.
Before-run captures there describe the old state, not successful after-run
results. These historical records are not public dependencies or a new
evaluation of the approved CSV price-reader change. No Python upgrade or new
hosting claim is part of the correction.

Seeds 1–5 are development seeds. Freeze code, calendar, settings and tests before
evaluating seeds 6–20. Do not generate seeds 6–20 in development tests. These
seeds were seen in the earlier project; reserved evaluation does not make them
newly unseen data.

The acceptance requirement per seeded dataset is 32 correctly found positive
cases (30 breaks and two unresolved review groups), zero missed, zero false
alarms, zero mislabelled and 15 correctly quiet traps. Clean data must produce
no exceptions. These are required targets, not reported measurements. If fresh
results fail these requirements, **stop and report the failure; do not retune on
the benchmark**. Undefined precision/recall remain `N/A`.

## One historical archive

`archive/pre_expiry_realism_correction/` holds all pre-correction datasets,
reports, manual copies and source/documentation snapshots. The entire tree is
historical and obsolete for interpreting current data, including documents that
still describe the earlier month basis, price components or retry history.
The one retained `reports/stage2_hardening/freeze.json` is a protected-engine
hash reference, not an active dataset report.

The current hash checker checks only `normalise.py`, `match.py`, `compare.py`,
`reconcile.py` and `scorecard.py` under `src/`, and writes
`reports/expiry_realism/hash_check.txt`. The archived 20-file Stage 3 snapshot
must not freeze the generator against this approved correction.

## Completed correction measurements

In the original evaluation frozen on November 13, 2026, all 20 generated seeded
datasets were independently scored: each found
32 of 32 positive cases with no misses, false alarms or mislabels and 15
correctly quiet traps. The measured development totals are 160 found and 75
quiet; reserved-evaluation totals are 480 found and 225 quiet. Combined totals
are 640 found, 300 quiet, 4,000 blotter records and 4,040 confirmations.
The clean control established 200 pairs with no exceptions; its scorecard ratios
are N/A because it has no labelled positive cases.

All seeded blotter contract months were December 2026 (1,348), January 2027
(1,384) or February 2027 (1,268). Both full delivered sides passed the independent
expiry checks. First-pass hashes for all 21 datasets still matched after final
regression runs. The five protected engine/scorer hashes match both original
references; settings are byte-identical to the archived settings.

That correction's final suite passed 254 cases on Python 3.9.6 in 77.49s and on Python 3.14.9
in 49.85s. `test_change_inventory.md` names all changed and renamed existing
tests, plus additions and the collection-count reconciliation. No historical
manifest was rewritten. All 335 recorded archived-file hashes were verified.

Raw per-seed outputs, generation retries and 63 executed CLI commands are under
`reports/expiry_realism/commands/`; aggregate CSVs and complete final test logs
are beside them. The aggregate value of discrepancy is accompanied by
`value_by_break_type.csv`, since these types use different valuation bases and
review amounts remain blank. The unchanged engine also verified the refreshed
manual clean exercise as 200 pairs and no exceptions.

The preserved CSV tables and `provenance.json` in `evidence/latest/` describe
that original evaluation. The provenance's `evaluation_inputs` hashes record
its original generator and inputs, including historical workbook provenance;
they are not a freeze of the current generator or current runtime dependencies.
The approved CSV price-reader plumbing changes the generator, not the five
unchanged engine/scorer sources. No new all-20-seed benchmark is claimed here.

These are measured synthetic-fixture results, not evidence of production
readiness or a fresh unseen-data benchmark. No hosted deployment or new native
browser check was performed. AppTest verifies the exact heading and page-title
configuration, private-calendar generation and error boundaries.

## Sources

[1] https://www.ice.com/products/219/Brent-Crude-Futures — ICE Brent Crude Futures product 219
