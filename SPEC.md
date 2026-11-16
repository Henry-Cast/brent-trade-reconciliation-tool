# Brent Trade Reconciliation Tool — Build Spec (v1)

## 1. What this is

A tool that compares two files — a trading desk's own trade record (the "blotter") and the broker's confirmations — pairs up the trades, and reports every disagreement ("break"), ranked by the money involved.

All trades are fictional. Prices are anchored to real published Brent prices.

## 2. Rules for the AI agent building this

1. Build ONE stage at a time (see section 9). Stop at the end of each stage and wait for my go-ahead.
2. Before writing code for a stage, explain the plan in plain English and wait for my OK.
3. Use plain Python and pandas. No clever shortcuts. Comment each function in plain English.
4. After each stage, give me a short walkthrough of what each file does and three questions to test my understanding.
5. The reconciliation engine must contain NO AI/LLM calls. All matching and arithmetic is ordinary, deterministic Python. AI explanations are an optional add-on in Stage 4.
6. Everything random must use a seed, so the same seed always produces the same data.
7. Write tests with pytest as you go. Do not tell me something works unless a test shows it.
8. Never report target numbers as results. Only report what the scorecard actually measured.

## 3. Folder layout

```
brent-recon/
  SPEC.md
  data/
    brent_spot.csv          real daily Brent spot prices (downloaded from EIA)
    generated/              files the generator creates
  src/
    generate.py             makes blotter, confirmations and answer key
    normalise.py            cleans and standardises both files
    match.py                pairs trades with confirmations
    compare.py              finds and values breaks
    scorecard.py            checks results against the answer key
  tests/
  app.py                    Streamlit interface (Stage 3)
  README.md
```

## 4. The market being modelled

- Product: ICE Brent crude futures. 1 lot = 1,000 barrels.
- Period: one calendar month of trade dates. About 200 trades.
- Trade price = real Brent spot price for that date (from data/brent_spot.csv)
  + a small simulated offset for the contract month + small random noise.
- The EIA series is a SPOT price, not a futures price. The README and the app must say
  clearly: "Prices are simulated, anchored to published Brent spot prices."
- Counterparties, brokers and traders: invented names only. No real firms.

### Approved generator-only expiry-realism clarification

Use the verified local `data/ice_brent_expiry_calendar.json` to select the front
tradable ICE Brent month and its next two consecutive contract months. Fail
clearly outside verified calendar coverage; do not approximate exchange holidays
or fetch data during generation. For the selected published October 2026 dates,
these months are December 2026, January 2027 and February 2027. Unknown
confirmations use the same set. A planted CONTRACT_MONTH error must use another
month in that same still-tradable set.

Price = published spot + `contract_month_adjustment_usd_bbl` × zero-based rank
from the front month + independent seeded noise from -$0.10 to +$0.10/bbl.
The unchanged setting `"-0.15"` gives month components $0.00, -$0.15 and -$0.30/bbl
for ranks 0, 1 and 2. This remains simulated pricing, not an observed futures
curve. Date-only expiry-day trades are assumed before the designated cutoff;
there is no intraday verification. See `docs/EXPIRY_REALISM.md` for the ICE rule,
bounded calendar policy, evidence requirements and archive distinction.

This clarification changes no planted case counts, matching, valuation or scoring
rules. Keep all existing generator safety guards and the original 100-attempt
retry policy, recording actual attempt metadata. The five engine/scorer sources
remain frozen. The main interface and browser title are exactly
**Brent Trade Reconciliation Tool**. Stages 4 and 5 below remain unimplemented
roadmap items, not part of the expiry-correction approval.

## 5. The files

### blotter.csv (the desk's record)

| Column | Example | Notes |
|---|---|---|
| trade_id | T000123 | unique |
| trade_date | 2026-09-14 | |
| trader | A. Mercer | invented |
| counterparty | Northsea Energy Ltd | invented |
| broker | Harbour Brokers | invented |
| side | BUY / SELL | from the desk's point of view |
| contract_month | 2026-12 | |
| quantity | 50 | |
| unit | LOTS / BBL | |
| price_usd_bbl | 74.20 | |

### confirmations.csv (the broker's record)

Same columns, except:
- `confirm_id` (unique, e.g. C000456) instead of `trade_id`
- `trade_ref` — the desk's trade_id as quoted by the broker. Sometimes blank.
- `side` is stated from the desk's point of view, same as the blotter.

### answer_key.csv (created by the generator, never read by the engine)

One row per planted case: trade_id, confirm_id, case_type, field affected, blotter value, confirmation value, expected_outcome (BREAK / NO_BREAK / NEEDS_REVIEW).

## 6. What to plant in the data

### True breaks — the tool MUST flag these (30)

| Type | Count | Description |
|---|---|---|
| PRICE | 6 | prices differ by $0.05/bbl or more |
| QUANTITY | 5 | volumes differ after converting to barrels |
| SIDE | 3 | buy on one file, sell on the other |
| CONTRACT_MONTH | 4 | different delivery months |
| UNIT_ERROR | 2 | e.g. 50 LOTS on one file, 50 BBL on the other |
| MISSING_CONFIRMATION | 4 | trade in blotter, nothing from broker |
| UNKNOWN_CONFIRMATION | 3 | confirmation with no trade in blotter |
| DUPLICATE | 3 | broker confirmed the same trade twice |

### Traps — the tool must NOT flag these (15)

| Type | Count | Description |
|---|---|---|
| Equivalent units | 5 | 50 LOTS vs 50,000 BBL — same trade |
| Counterparty name variant | 4 | "Northsea Energy Ltd" vs "NORTHSEA ENERGY LIMITED" |
| Rounding | 3 | prices differ by $0.01/bbl or less |
| Missing trade_ref | 3 | reference blank but every other field identical |

### Ambiguous cases — the tool must say NEEDS_REVIEW (2)

Two identical trades on the same day (same counterparty, side, month, volume, price) where the confirmations have blank trade_ref. The tool cannot know which confirmation belongs to which trade, so it must not guess.

Everything else (~150 trades) is clean and must produce no alert.

## 7. Matching rules (in this order)

1. **Normalise both files.** Convert every quantity to barrels. Trim spaces, standardise capitals, map counterparty name variants to one name using an alias table. Parse dates.
2. **Match on reference.** Pair confirmations to trades where trade_ref = trade_id.
3. **Match leftovers on attributes.** For anything unpaired, look for a trade with the same date, counterparty, side, contract month, volume (bbl) and price (within tolerance).
   - Exactly one candidate → pair them.
   - More than one equally good candidate → NEEDS_REVIEW. Do not guess.
4. **Near matches.** For anything still unpaired, allow exactly ONE of side / contract month / volume / price to differ. Exactly one candidate → pair them (the differing field becomes a break). More than one → NEEDS_REVIEW.
5. **Compare fields** on every pair and record breaks.
6. **Leftovers.** Unpaired trade → MISSING_CONFIRMATION. Unpaired confirmation → UNKNOWN_CONFIRMATION. Two confirmations for one trade → DUPLICATE.

Tolerances (held in one settings file, not scattered in code):
- Price: differences of $0.01/bbl or less are ignored.
- Volume: zero tolerance after conversion to barrels.

## 8. Valuing a break

Call this "value of discrepancy". It is NOT a realised loss or P&L, and the app must never label it as one.

| Break | Value shown |
|---|---|
| PRICE | price difference × volume in barrels |
| QUANTITY / UNIT_ERROR | volume difference in barrels × trade price |
| SIDE | 2 × volume × price (position is wrong by twice the trade) |
| MISSING / UNKNOWN / DUPLICATE | volume × price (full notional of the trade) |
| CONTRACT_MONTH | full notional, shown as "wrong delivery month" |

Priority: SIDE, MISSING_CONFIRMATION, UNKNOWN_CONFIRMATION and DUPLICATE are always HIGH. Everything else is ranked by value.

## 9. Build stages

### Stage 1 — Data generator
- `generate.py --seed 1` creates blotter.csv, confirmations.csv and answer_key.csv in data/generated/.
- A `--clean` option creates a dataset with no breaks at all.
- Done when: files open in Excel, counts match section 6, same seed gives identical files.

### Stage 2 — Engine and scorecard (command line only)
- normalise → match → compare → results.csv (one row per break or review item).
- `scorecard.py` compares results.csv with answer_key.csv and prints, per case type:
  found, missed, false alarms, precision, recall.
- Run across seeds 1–5 plus one clean dataset. Report the actual numbers.
- Done when: tests pass and I can explain every matching rule without looking.

### Stage 3 — Streamlit interface
- Upload two files or click "Generate new dataset".
- Summary: trades processed, matched, breaks by type, total value of discrepancy.
- Table of exceptions, sortable, with a detail view showing both records side by side.
- Scorecard page showing measured results (only available for generated data).

### Stage 4 — Optional AI explanations and export
- For each break, an LLM writes a two-sentence plain-English explanation and a draft query to the broker, using ONLY figures already calculated by the engine.
- The app works fully with this switched off.
- Export exceptions report to Excel.

### Stage 5 — Publish
- README in desk language: what a break is, why it matters before settlement, how matching works, measured scorecard, limitations.
- GitHub repository, Streamlit Community Cloud deployment, 60-second demo video.

## 10. Out of scope for v1

Live or licensed market data. Other products. Tonnes conversions. Currencies other than USD. Fees and commissions. Logins or user accounts. Anything that predicts prices or suggests trades.
