# Brent Trade Reconciliation Tool

**Built by Henry Cast**

A teaching demonstration for checking a desk's trade blotter against broker confirmations before settlement. **All supplied trades, people and firms are fictional.**

**Prices are simulated, anchored to published Brent spot prices.**[1]

## What is a break, and why check it before settlement?

A break is a disagreement between the desk's record and the broker's confirmation: for example, a different price, quantity, buy/sell direction or delivery month. A missing confirmation or an extra copy also needs attention.

Finding these differences before settlement gives operations time to ask the broker, correct the agreed record and check the intended position. This tool produces a review queue; it does not amend trades, contact a broker, settle anything or determine what money is owed.

## Try it

After starting the app using the instructions below, choose either:

- **Upload files:** use `sample_data/clean/blotter.csv` and `sample_data/clean/confirmations.csv`. This small pair contains ten clean trades and their ten confirmations. Click **Reconcile uploaded files**; the expected result is ten established pairs and no exceptions. Uploads do not have a known-answer scorecard, even when the files originally came from this generator.
- **Generate data:** leave the seed at **1** and click **Generate new dataset**. This creates a fictional example with deliberately planted disagreements and harmless differences. Use development seeds 1–5 when experimenting. A generated run offers a **Scorecard** page because the generator supplied known answers for that session.

The summary separates the number of distinct matched trades from the number of established pairs: duplicate confirmations can increase pairs without adding desk trades. The exceptions table starts with high-priority items, supports value sorting, and shows both original records with affected fields highlighted. Ambiguous groups retain all candidates; the tool does not invent a pairing.

## How the six matching rules work

The rules run in this order; no AI model is called during reconciliation.

1. **Put both records on the same basis.** Read dates, tidy spaces and capitals, map reviewed counterparty aliases, and convert lots to barrels. One Brent lot is 1,000 barrels. This prevents a different spelling or unit representation from looking like a different trade.
2. **Use the trade reference first.** If the broker quotes a desk trade ID that exists in the blotter, link the records. Linking is not agreement: the fields are still checked afterwards, and repeated confirmations are retained.
3. **Match unlinked records by their details.** Look for the same date, counterparty, buy/sell direction, delivery month, barrel volume and price. Prices within $0.01 per barrel count as equal; volume must agree exactly. A unique candidate can be linked. Equally plausible candidates go to review, not a guess.
4. **Look for a one-field near match.** For records still unlinked, keep the date and counterparty fixed and allow exactly one of direction, month, volume or price to differ. A unique candidate can be linked so the disagreement can be reported. Multiple plausible candidates go to review.
5. **Check each established pair.** Compare its fields under the stated tolerances and record the disagreements. Equivalent lots/barrels and price rounding within tolerance are not breaks.
6. **Report what remains and what is repeated.** A desk trade without a confirmation is missing; a confirmation without a desk trade is unknown. Multiple confirmations for one desk trade are reported as duplicates. Unresolved groups remain separate review items.

The shared tolerances and counterparty alias list are in `settings.json`; see `docs/SETTINGS.md`. Unsupported cases outside the written rules can stop with an error rather than receive an invented classification or valuation.

## Latest measured results — generated data only

These are the latest recorded scorecard measurements, not targets. The expiry-corrected evaluation was frozen on November 13, 2026. Each seeded file contains 200 desk trades and 202 confirmations; the clean control contains 200 of each.

| Latest evaluation split | Datasets | Positive cases found | Missed | False alarms | Wrongly labelled | Harmless planted cases correctly left quiet |
|---|---:|---:|---:|---:|---:|---:|
| Development: seeds 1–5 | 5 | 160 | 0 | 0 | 0 | 75 |
| Reserved: seeds 6–20 | 15 | 480 | 0 | 0 | 0 | 225 |
| Combined | 20 | 640 | 0 | 0 | 0 | 300 |

Every seeded dataset measured **32 of 32** positive cases found and **15** correctly quiet cases. “Positive” includes correctly identifying the two ambiguous review groups per dataset; it does not mean those groups were resolved. The separate clean control produced **200 established pairs and no exceptions**. Its precision and recall are undefined because it contains no labelled positive cases.

The measured tables are in `evidence/latest/`, including every seed, per-type scores, rule traces and the valuation breakdown.

> Correct against its specification on generated data with known answers. Not evidence of production readiness.

## Read the value of discrepancy carefully

The total value of discrepancy is mostly full-notional items, **not a loss or P&L**. For a missing, unknown or duplicate confirmation, and for a wrong delivery month, the specification assigns the whole trade's notional value. A side disagreement uses twice the notional; price and volume disagreements use different bases. Adding these figures does not produce an estimate of actual economic damage or money payable.

The app therefore shows counts and values by break type beside the total. Review items have a **blank value**, not zero, and are excluded from the total. The latest all-20-dataset breakdown is:

| Break type | Count | Value of discrepancy (USD) |
|---|---:|---:|
| Ambiguous groups for review | 40 |  |
| Wrong delivery month | 80 | $695,718,150.00 |
| Duplicate confirmations | 60 | $483,708,200.00 |
| Missing confirmations | 80 | $653,262,300.00 |
| Price | 120 | $3,748,750.00 |
| Quantity | 100 | $1,015,756,200.00 |
| Buy/sell direction | 60 | $769,265,000.00 |
| Unit error | 40 | $259,599,890.25 |
| Unknown confirmations | 60 | $525,665,000.00 |
| **Total, excluding blank review values** | | **$4,406,723,490.25** |

These figures describe fictional examples only. A large total can reflect the valuation convention rather than a large difference in prices.

## Limitations

- **All supplied and measured trades are generated.** This has not been validated against a trading desk's real blotter or broker confirmations. Uploaded files are not independently known-answer tests.
- **Spot prices are not futures prices.** Across the same 22 October 2026 dates, EIA spot averaged $123.93/bbl versus $104.73/bbl in ICE’s public historical chart for the fixed January 2027 Brent contract: a monthly-mean gap of $19.20/bbl, roughly $20 higher.[2][3] This is a fixed-contract, date-matched chart comparison—not verified official settlements or a rolling front-month series—and it does not imply a $20 gap on every day. The generator uses the EIA spot observation for each date, then small simulated month adjustments and noise; it is not calibrated to ICE futures.
- **The same AI coding agent wrote the generator and the engine.** Their assumptions and mistakes can overlap. A separate scorer and stage reviews reduce some risks but do not make the generated benchmark independent evidence of real-world correctness.
- **Seeds 6–20 are a reserved set, not an unseen benchmark.** They have been used earlier in this project. Passing another seed from the same constrained generator does not demonstrate generalisation to real trading data.
- **Records have dates but no times.** The generator assumes expiry-day trades occur before the expiry cutoff. It cannot establish intraday order, timing or whether a particular real trade preceded expiry.
- **Scope is narrow.** Brent examples use USD, lots/barrels, specified tolerances and a manually maintained alias list. Fees, commissions, other products, tonnes and unspecified economic disagreements are outside the rules. There is no account system, production security assessment, live feed or settlement connection. Do not upload confidential desk data to an unassessed host.

For October 2026 the generator uses the tradable December 2026, January 2027 and February 2027 contracts. Its simulated month components are $0.00, −$0.15 and −$0.30 per barrel, with independent noise of up to $0.10 either way. Expiry dates come from a bounded local calendar, not a live holiday service; unsupported dates fail clearly. See `docs/EXPIRY_REALISM.md`.

## How it was built

Henry Cast specified, directed and tested this tool; the code was written with an AI coding agent, and each stage was independently reviewed before the next began. These were project-stage reviews, not production certification. The generator, reconciliation engine and independent scoring step were built in stages; the interface calls the existing engine rather than implementing a second matcher. Reconciliation uses ordinary deterministic Python and exact decimal arithmetic, not AI/LLM calls.

Five engine/scorer files remain protected by their original hashes. Automated tests cover input validation, matching, discrepancy values, generated known-answer cases and the interface.

## Run it locally

Use **Python 3.14**. The app is tested locally on macOS; other operating systems have not been separately validated.

Open a terminal in the project folder. On macOS/Linux:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Open the local address printed by Streamlit. Stop it with **Ctrl+C**. Linux uses the same commands but has not been separately exercised; Windows needs its platform's virtual-environment activation command and has not been tested.

No custom startup script or API key is required. Runtime packages are pinned in `requirements.txt`; test tools are separate:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python scripts/check_stage3_hashes.py
```

The app creates private per-session temporary folders under ignored `.app_sessions/`. Files are not durable storage; sessions may disappear when the process or host stops. Generated examples read the included `data/brent_spot.csv`, expiry-calendar JSON and settings. No Excel workbook or price download is needed.

## Data credit and licence

Included: **22 daily EIA Brent spot prices for October 2026**, in USD per barrel, stored in `data/brent_spot.csv`.

Source: U.S. Energy Information Administration (Nov 2026).[1]

EIA credits Refinitiv as the underlying spot-price source.[4]

The expiry calendar cites ICE's Brent contract specification and expiry listing.[5][6] Calendar facts do not turn the simulated prices into observed futures settlements.

The project's own code is available under the **MIT licence** in `LICENSE`. Copyright (c) 2026 Henry Cast. Third-party data and reference materials retain their own applicable terms; this project does not relicense them as MIT.

## Sources

[1] https://www.eia.gov/dnav/pet/hist/RBRTEd.htm — EIA — Europe Brent Spot Price FOB: daily observations
[2] https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RBRTE&f=M — EIA — Europe Brent Spot Price FOB: monthly averages
[3] https://www.ice.com/products/219/Brent-Crude-Futures/data — ICE — Brent Crude Futures: public prices and charts
[4] https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm — EIA — Petroleum spot prices and Refinitiv source credit
[5] https://www.ice.com/products/219/Brent-Crude-Futures — ICE — Brent Crude Futures: contract specification
[6] https://www.ice.com/products/219/Brent-Crude-Futures/expiry — ICE — Brent Crude Futures: expiry dates
