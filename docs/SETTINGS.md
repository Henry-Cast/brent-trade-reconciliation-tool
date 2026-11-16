# Settings in plain English

`settings.json` is ordinary JSON: it has no comments. Explanations belong here.
Changing a shared setting can affect generated fixtures or reconciliation;
do not change it to improve a reserved evaluation score.

| Key | Current value | Meaning |
|---|---|---|
| `price_tolerance_usd_bbl` | `"0.01"` | Price differences of $0.01/bbl or less are ignored. |
| `volume_tolerance_bbl` | `0` | No volume difference is allowed after conversion to barrels. |
| `barrels_per_lot` | `1000` | One lot represents 1,000 barrels. |
| `contract_month_adjustment_usd_bbl` | `"-0.15"` | Generator-only simulated slope per month rank after the front still-tradable contract. |
| `counterparty_aliases` | Explicit invented-name mappings | Fallback mappings after general name rules; review and maintain by hand in real use. |

## Month adjustment: start counting at zero

The expiry calendar determines the front still-tradable contract for a trade
date. Its rank is 0, the next month's rank is 1 and the third month's rank is 2.
The unchanged `"-0.15"` value therefore adds **$0.00, -$0.15 and -$0.30/bbl**,
respectively, to published spot before independent seeded noise in
[-$0.10, +$0.10/bbl]. It is not multiplied by months after the trade's calendar
month. For the selected October 2026 dates those ranks mean December 2026,
January 2027 and February 2027.

The front-month spot anchor does not assert that spot equals a real futures
price. **Prices are simulated, anchored to published Brent spot prices.**
No observed futures curve is used. The `"-0.15"` setting is not itself changed by
the expiry-realism correction; its basis is clarified as zero-based front rank.

## Calendar and settings are separate inputs

Verified expiry dates and bounded coverage live in
`data/ice_brent_expiry_calendar.json`, not in the aliases or price adjustment.
Generation makes no network calls and must fail clearly outside coverage rather
than guessing holidays. Date-only records on expiry day are assumed before the
cutoff; they are not intraday-verified. See `EXPIRY_REALISM.md` for the full
approved policy, source, evaluation boundary and stop rule.

The sole market-price input is the read-only `data/brent_spot.csv`, containing
22 published October 2026 observations. The app copies that CSV, settings and
calendar JSON into each private generation workspace for its subprocess. It
does not copy or parse a workbook, regenerate the shared CSV or require `xlrd`
at runtime. The original workbook is historical source provenance only. Do not
place comments in the JSON or share writable generation inputs between sessions.
