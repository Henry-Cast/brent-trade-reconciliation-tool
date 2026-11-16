"""Create fictional Brent records from the locally supplied market-price CSV."""
from pathlib import Path
import argparse
import json
import random
import unicodedata
from decimal import Decimal, InvalidOperation
from itertools import combinations
from collections import Counter

BLOTTER_COLUMNS = ["trade_id", "trade_date", "trader", "counterparty", "broker", "side",
                   "contract_month", "quantity", "unit", "price_usd_bbl"]
CONFIRM_COLUMNS = ["confirm_id", "trade_ref"] + BLOTTER_COLUMNS[1:]
ANSWER_COLUMNS = ["case_id", "trade_id", "confirm_id", "case_type", "field_affected",
                  "blotter_value", "confirmation_value", "expected_outcome", "expected_matching_rule"]
COUNTERPARTIES = ["Kestrel Shoal Energy Ltd", "Amber Buoy Trading Ltd", "Silver Tern Fuels Ltd"]
SHORT_COUNTERPARTY_NAMES = {"Kestrel Shoal Energy Ltd": "KESTREL SHOAL",
                            "Amber Buoy Trading Ltd": "AMBER BUOY",
                            "Silver Tern Fuels Ltd": "SILVER TERN"}
TRADERS = ["A. Fenwick", "L. Merevale", "P. Ashcombe"]
BROKERS = ["Willow Quay Brokers", "Copper Gull Brokerage"]
CLIP_SIZES_LOTS = [5, 10, 25, 50, 100, 200]
NEAR_BREAK_COUNTS = {"PRICE": 2, "QUANTITY": 1, "SIDE": 1, "CONTRACT_MONTH": 1}

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class DatasetSafetyError(ValueError):
    """Reject a sampled dataset only because it violates an explicit fixture constraint."""


def load_prices(source):
    """Read the supplied market-price CSV without selecting months or writing source data."""
    try:
        prices = pd.read_csv(source, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        raise ValueError("The price CSV is empty.") from None
    if list(prices.columns) != ["trade_date", "spot_price_usd_bbl"]:
        raise ValueError("Expected price CSV columns: trade_date, spot_price_usd_bbl.")
    if prices.empty:
        raise ValueError("The price CSV is empty.")
    if not prices["trade_date"].str.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}").all():
        raise ValueError("Every trade_date must be a valid YYYY-MM-DD date.")
    try:
        prices["trade_date"] = pd.to_datetime(prices["trade_date"], format="%Y-%m-%d", errors="raise")
    except ValueError:
        raise ValueError("Every trade_date must be a valid YYYY-MM-DD date.") from None
    if prices["trade_date"].duplicated().any():
        raise ValueError("The price CSV contains duplicate trade_date values.")
    try:
        prices["spot_price_usd_bbl"] = prices["spot_price_usd_bbl"].map(Decimal)
    except InvalidOperation:
        raise ValueError("Every spot price must be a positive finite number.") from None
    if not all(value.is_finite() and value > 0 for value in prices["spot_price_usd_bbl"]):
        raise ValueError("Every spot price must be a positive finite number.")
    return prices.sort_values("trade_date").reset_index(drop=True)


def load_expiry_calendar():
    """Read the locally verified ICE dates; never fetch or invent exchange dates during generation."""
    return json.loads((ROOT / "data/ice_brent_expiry_calendar.json").read_text())


def tradable_contract_months(trade_date, calendar=None):
    """Return the front and next two months, assuming expiry-day trades occur before the cutoff."""
    calendar = load_expiry_calendar() if calendar is None else calendar
    day = pd.Timestamp(trade_date).date().isoformat()
    if not calendar["coverage_trade_date_start"] <= day <= calendar["coverage_trade_date_end"]:
        raise ValueError(f"No verified ICE expiry-calendar coverage for {day}. Extend the local calendar before generating this period.")
    expiries = {row["contract_month"]: row["last_trade_date"] for row in calendar["contracts"]}
    # Under ICE's second-preceding-month rule, earlier delivery months have already expired.
    front = pd.Period(day, freq="M") + 2
    while True:
        if str(front) not in expiries:
            raise ValueError(f"The verified ICE calendar is missing contract month {front}.")
        if day <= expiries[str(front)]:
            break
        front += 1
    months = [str(front + rank) for rank in range(3)]
    if any(month not in expiries or day > expiries[month] for month in months):
        raise ValueError(f"The verified ICE calendar does not contain three tradable contracts for {day}.")
    return months


def general_counterparty_name(name):
    """Apply the specified general name rules independently of the frozen engine."""
    text = unicodedata.normalize("NFKC", str(name)).upper()
    text = "".join(" " if unicodedata.category(character).startswith("P") else character
                   for character in text)
    words = text.split()
    if words and words[-1] == "LIMITED":
        words[-1] = "LTD"
    return " ".join(words)


def trade_signature(trade, barrels_per_lot, aliases=None):
    """Identify a trade by all six matching attributes, with volume in barrels."""
    volume = Decimal(str(trade["quantity"]))
    if trade["unit"].strip().upper() == "LOTS":
        volume *= barrels_per_lot
    counterparty = general_counterparty_name(trade["counterparty"])
    if aliases is not None:
        canonical_aliases = {general_counterparty_name(source): general_counterparty_name(target)
                             for source, target in aliases.items()}
        counterparty = canonical_aliases.get(counterparty, counterparty)
    return (pd.Timestamp(trade["trade_date"]).date().isoformat(), counterparty,
            trade["side"].strip().upper(), trade["contract_month"].strip(),
            volume, Decimal(str(trade["price_usd_bbl"])))


def draw_unique_trade(index, prices, rng, seen_signatures, settings):
    """Draw a whole candidate again only if its complete matching combination already exists."""
    adjustment_cents = int(Decimal(settings["contract_month_adjustment_usd_bbl"]) * 100)
    calendar = settings.get("_expiry_calendar") or load_expiry_calendar()
    while True:
        day = prices.iloc[rng.randrange(len(prices))]
        month_rank = rng.randint(0, 2)
        spot_cents = int(Decimal(str(day["spot_price_usd_bbl"])) * 100)
        price_cents = spot_cents + adjustment_cents * month_rank + rng.randint(-10, 10)
        contract = tradable_contract_months(day["trade_date"], calendar)[month_rank]
        trade = {
            "trade_id": f"T{index + 1:06d}",
            "trade_date": day["trade_date"].strftime("%Y-%m-%d"),
            "trader": rng.choice(TRADERS),
            "counterparty": rng.choice(COUNTERPARTIES),
            "broker": rng.choice(BROKERS),
            "side": rng.choice(["BUY", "SELL"]),
            "contract_month": str(contract),
            "quantity": rng.choice(CLIP_SIZES_LOTS),
            "unit": "LOTS",
            "price_usd_bbl": format(Decimal(price_cents) / 100, ".2f"),
        }
        signature = trade_signature(trade, settings["barrels_per_lot"], settings["counterparty_aliases"])
        collision = False
        for existing in seen_signatures:
            if signature[:5] == existing[:5] and abs(signature[5] - existing[5]) <= Decimal(settings["price_tolerance_usd_bbl"]):
                collision = True
                break
        if not collision:
            seen_signatures.add(signature)
            return trade


def draw_unknown_confirmations(prices, rng, trades, confirmations, first_confirm, settings):
    """Draw fresh orphan records with varied fields and no exact or one-field desk candidate."""
    aliases = settings["counterparty_aliases"]
    barrels_per_lot = settings["barrels_per_lot"]
    tolerance = Decimal(settings["price_tolerance_usd_bbl"])
    blotter_signatures = [trade_signature(row, barrels_per_lot, aliases) for row in trades]
    existing_signatures = {trade_signature(row, barrels_per_lot, aliases)
                           for row in trades + confirmations}
    # Redraw the group if its fresh samples do not cover the requested variety.
    for group_attempt in range(1000):
        seen = set(existing_signatures)
        unknowns = []
        for index in range(3):
            for candidate_attempt in range(1000):
                candidate = draw_unique_trade(900000 + index, prices, rng, seen, settings)
                signature = trade_signature(candidate, barrels_per_lot, aliases)
                could_pair = False
                for existing in blotter_signatures:
                    if signature[:2] != existing[:2]:
                        continue
                    differences = sum(signature[field] != existing[field] for field in [2, 3, 4])
                    differences += int(abs(signature[5] - existing[5]) > tolerance)
                    if differences <= 1:
                        could_pair = True
                        break
                if not could_pair:
                    candidate["trade_ref"] = candidate.pop("trade_id")
                    if index == 0:
                        candidate["trade_ref"] = ""
                    candidate["confirm_id"] = f"C{first_confirm + index:06d}"
                    unknowns.append(candidate)
                    break
                seen.discard(signature)
            else:
                raise RuntimeError("Could not draw an unknown without a desk candidate.")
        distinct_fields = ["trade_date", "counterparty", "contract_month", "price_usd_bbl"]
        distinct = all(len({row[field] for row in unknowns}) == 3 for field in distinct_fields)
        both_sides = len({row["side"] for row in unknowns}) == 2
        different_brokers = len({row["broker"] for row in unknowns}) >= 2
        if distinct and both_sides and different_brokers:
            return unknowns
    raise RuntimeError("Could not draw three sufficiently varied unknown confirmations.")


def candidate_trade_ids(confirmation, trades, settings):
    """Independently count exact and one-field candidates without calling the engine."""
    aliases = settings["counterparty_aliases"]
    barrels = settings["barrels_per_lot"]
    tolerance = Decimal(settings["price_tolerance_usd_bbl"])
    first = trade_signature(confirmation, barrels, aliases)
    candidates = {"exact": [], "near": []}
    for trade in trades:
        second = trade_signature(trade, barrels, aliases)
        if first[:2] != second[:2]:
            continue
        differences = sum(first[field] != second[field] for field in [2, 3, 4])
        differences += int(abs(first[5] - second[5]) > tolerance)
        if differences == 0:
            candidates["exact"].append(trade["trade_id"])
        elif differences == 1:
            candidates["near"].append(trade["trade_id"])
    return candidates


def plant_near_match_references(trades, confirmations, answers, rng, settings):
    """Remove five references only when each intended trade is its sole near candidate."""
    by_id = {row["confirm_id"]: row for row in confirmations}
    for answer in answers:
        if answer["case_type"] in {"MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION", "AMBIGUOUS"}:
            answer["expected_matching_rule"] = ""
        elif answer["case_type"] == "MISSING_TRADE_REF":
            answer["expected_matching_rule"] = "RULE_3_ATTRIBUTES"
        else:
            answer["expected_matching_rule"] = "RULE_2_REFERENCE"
    for kind, required in NEAR_BREAK_COUNTS.items():
        eligible = []
        for answer in answers:
            if answer["case_type"] != kind:
                continue
            candidates = candidate_trade_ids(by_id[answer["confirm_id"]], trades, settings)
            if not candidates["exact"] and candidates["near"] == [answer["trade_id"]]:
                eligible.append(answer)
        if len(eligible) < required:
            raise DatasetSafetyError(f"Not enough uniquely identifiable {kind} near cases.")
        for answer in rng.sample(eligible, required):
            by_id[answer["confirm_id"]]["trade_ref"] = ""
            answer["expected_matching_rule"] = "RULE_4_NEAR_MATCH"


def plant_cases(trades, confirmations, rng, prices, settings):
    """Change separate records for each case and keep a labelled answer key."""
    answers = []
    price_tolerance = Decimal(settings["price_tolerance_usd_bbl"])
    indexes = list(range(len(trades)))
    rng.shuffle(indexes)
    position = 0
    case_number = 0
    next_confirm = len(confirmations) + 1
    counts = [
        ("PRICE", 6), ("QUANTITY", 5), ("SIDE", 3), ("CONTRACT_MONTH", 4),
        ("UNIT_ERROR", 2), ("MISSING_CONFIRMATION", 4), ("DUPLICATE", 3),
        ("EQUIVALENT_UNITS", 5), ("COUNTERPARTY_VARIANT", 4),
        ("ROUNDING", 3), ("MISSING_TRADE_REF", 3),
    ]
    harmless = {"EQUIVALENT_UNITS", "COUNTERPARTY_VARIANT", "ROUNDING", "MISSING_TRADE_REF"}
    # Keep one exact tolerance-boundary example and choose five different larger differences.
    price_differences_cents = [5] + rng.sample(range(6, 101), 5)
    for kind, count in counts:
        for case_index in range(count):
            index = indexes[position]
            position += 1
            case_number += 1
            trade = trades[index]
            confirm = confirmations[index]
            field = ""
            left = ""
            right = ""
            confirm_id = confirm["confirm_id"]
            if kind == "PRICE":
                field = "price_usd_bbl"
                difference = Decimal(price_differences_cents[case_index]) / 100
                confirm[field] = format(Decimal(trade[field]) + difference, ".2f")
            elif kind == "QUANTITY":
                field = "quantity"
                other_sizes = [size for size in CLIP_SIZES_LOTS if size != trade[field]]
                confirm[field] = rng.choice(other_sizes)
            elif kind == "SIDE":
                field = "side"
                confirm[field] = "SELL" if trade[field] == "BUY" else "BUY"
            elif kind == "CONTRACT_MONTH":
                field = "contract_month"
                months = tradable_contract_months(trade["trade_date"], settings.get("_expiry_calendar"))
                # Rotate within the same verified three-month universe without another random draw.
                confirm[field] = months[(months.index(trade[field]) + 1) % len(months)]
            elif kind == "UNIT_ERROR":
                field = "unit"
                confirm[field] = "BBL"
            elif kind == "MISSING_CONFIRMATION":
                field = "record"
                left, right = "PRESENT", "ABSENT"
                confirm_id = ""
                confirm["_remove"] = True
            elif kind == "DUPLICATE":
                field = "confirmation_count"
                left, right = 1, 2
                extra = dict(confirm)
                extra["confirm_id"] = f"C{next_confirm:06d}"
                next_confirm += 1
                confirmations.append(extra)
                confirm_id = extra["confirm_id"]
            elif kind == "EQUIVALENT_UNITS":
                field = "quantity_and_unit"
                left = f"{trade['quantity']} LOTS"
                confirm["quantity"] *= settings["barrels_per_lot"]
                confirm["unit"] = "BBL"
                right = f"{confirm['quantity']} BBL"
            elif kind == "COUNTERPARTY_VARIANT":
                field = "counterparty"
                if case_index < 2:
                    confirm[field] = trade[field].upper().replace(" LTD", " LIMITED")
                else:
                    confirm[field] = SHORT_COUNTERPARTY_NAMES[trade[field]]
            elif kind == "ROUNDING":
                field = "price_usd_bbl"
                confirm[field] = format(Decimal(trade[field]) + price_tolerance, ".2f")
            elif kind == "MISSING_TRADE_REF":
                field = "trade_ref"
                left, right = trade["trade_id"], ""
                confirm[field] = ""
            if field in trade:
                left, right = trade[field], confirm[field]
            answers.append({
                "case_id": f"CASE{case_number:03d}", "trade_id": trade["trade_id"],
                "confirm_id": confirm_id, "case_type": kind, "field_affected": field,
                "blotter_value": left, "confirmation_value": right,
                "expected_outcome": "NO_BREAK" if kind in harmless else "BREAK",
            })
    unknowns = draw_unknown_confirmations(prices, rng, trades, confirmations, next_confirm, settings)
    for extra in unknowns:
        case_number += 1
        confirmations.append(extra)
        answers.append({
            "case_id": f"CASE{case_number:03d}", "trade_id": "",
            "confirm_id": extra["confirm_id"], "case_type": "UNKNOWN_CONFIRMATION",
            "field_affected": "record", "blotter_value": "ABSENT",
            "confirmation_value": "PRESENT", "expected_outcome": "BREAK",
        })
    for unused in range(2):
        case_number += 1
        first, second = indexes[position:position + 2]
        position += 2
        # Keep separate IDs but make all other trade fields identical within the pair.
        for field in BLOTTER_COLUMNS[1:]:
            trades[second][field] = trades[first][field]
        for index in [first, second]:
            for field in BLOTTER_COLUMNS[1:]:
                confirmations[index][field] = trades[index][field]
            confirmations[index]["trade_ref"] = ""
            answers.append({
                "case_id": f"CASE{case_number:03d}", "trade_id": trades[index]["trade_id"],
                "confirm_id": confirmations[index]["confirm_id"], "case_type": "AMBIGUOUS",
                "field_affected": "trade_ref", "blotter_value": trades[index]["trade_id"],
                "confirmation_value": "", "expected_outcome": "NEEDS_REVIEW",
            })
    confirmations = [confirm for confirm in confirmations if not confirm.get("_remove", False)]
    plant_near_match_references(trades, confirmations, answers, rng, settings)
    rng.shuffle(confirmations)
    return confirmations, answers


def validate_dataset_safety(trades, confirmations, answers, settings):
    """Refuse to write files with unlabelled collisions, untradable months, or a pairing orphan."""
    calendar = settings.get("_expiry_calendar") or load_expiry_calendar()
    for record in trades + confirmations:
        months = tradable_contract_months(record["trade_date"], calendar)
        if record["contract_month"] not in months:
            identifier = record.get("trade_id", record.get("confirm_id"))
            raise DatasetSafetyError(f"Contract month {record['contract_month']} is outside the three tradable months on {record['trade_date']}: {identifier}")
    aliases = settings["counterparty_aliases"]
    barrels_per_lot = settings["barrels_per_lot"]
    tolerance = Decimal(settings["price_tolerance_usd_bbl"])
    allowed = set()
    ambiguous_groups = {}
    for answer in answers:
        if answer["case_type"] == "DUPLICATE":
            originals = [row for row in confirmations
                         if row["trade_ref"] == answer["trade_id"]
                         and row["confirm_id"] != answer["confirm_id"]]
            if len(originals) != 1:
                raise DatasetSafetyError("A planted duplicate must have exactly one original confirmation.")
            allowed.add(tuple(sorted([originals[0]["confirm_id"], answer["confirm_id"]])))
        elif answer["case_type"] == "AMBIGUOUS":
            ambiguous_groups.setdefault(answer["case_id"], []).append(answer["confirm_id"])
    for identifiers in ambiguous_groups.values():
        if len(identifiers) != 2:
            raise DatasetSafetyError("A planted ambiguous case must identify two confirmations.")
        allowed.add(tuple(sorted(identifiers)))
    signatures = {row["confirm_id"]: trade_signature(row, barrels_per_lot, aliases)
                  for row in confirmations}
    actual = set()
    for left, right in combinations(confirmations, 2):
        first = signatures[left["confirm_id"]]
        second = signatures[right["confirm_id"]]
        if first[:5] == second[:5] and abs(first[5] - second[5]) <= tolerance:
            pair = tuple(sorted([left["confirm_id"], right["confirm_id"]]))
            if pair not in allowed:
                raise DatasetSafetyError(f"Unexpected confirmation collision: {pair}")
            actual.add(pair)
    if actual != allowed:
        raise DatasetSafetyError("A labelled duplicate or ambiguous pair is not present in the records.")
    variants = [row for row in answers if row["case_type"] == "COUNTERPARTY_VARIANT"]
    if variants:
        trade_map = {row["trade_id"]: row for row in trades}
        confirmation_map = {row["confirm_id"]: row for row in confirmations}
        resolved_by = Counter()
        for answer in variants:
            trade = trade_map[answer["trade_id"]]
            confirmation = confirmation_map[answer["confirm_id"]]
            general_left = general_counterparty_name(trade["counterparty"])
            general_right = general_counterparty_name(confirmation["counterparty"])
            if general_left == general_right:
                resolved_by["GENERAL_RULES"] += 1
            elif trade_signature(trade, barrels_per_lot, aliases)[1] == trade_signature(confirmation, barrels_per_lot, aliases)[1]:
                resolved_by["ALIAS_TABLE"] += 1
            else:
                raise DatasetSafetyError(f"Unresolved name variant: {answer['case_id']}")
        if resolved_by != {"GENERAL_RULES": 2, "ALIAS_TABLE": 2}:
            raise DatasetSafetyError("The name variants must split two general and two alias resolutions.")
    if any("expected_matching_rule" in row for row in answers):
        near_answers = [row for row in answers if row.get("expected_matching_rule") == "RULE_4_NEAR_MATCH"]
        if Counter(row["case_type"] for row in near_answers) != NEAR_BREAK_COUNTS:
            raise DatasetSafetyError("The required near-case counts are incorrect.")
        by_id = {row["confirm_id"]: row for row in confirmations}
        for answer in near_answers:
            confirmation = by_id[answer["confirm_id"]]
            candidates = candidate_trade_ids(confirmation, trades, settings)
            if confirmation["trade_ref"] or candidates["exact"] or candidates["near"] != [answer["trade_id"]]:
                raise DatasetSafetyError(f"Invalid unique near-case constraint: {answer['case_id']}")
    unknown_ids = {row["confirm_id"] for row in answers if row["case_type"] == "UNKNOWN_CONFIRMATION"}
    unknowns = [row for row in confirmations if row["confirm_id"] in unknown_ids]
    if unknowns and sum(row["trade_ref"] == "" for row in unknowns) != 1:
        raise DatasetSafetyError("Exactly one unknown confirmation must have a blank reference.")
    blotter_ids = {row["trade_id"] for row in trades}
    blotter_signatures = [trade_signature(row, barrels_per_lot, aliases) for row in trades]
    for orphan in unknowns:
        if orphan["trade_ref"] in blotter_ids:
            raise DatasetSafetyError("An unknown confirmation cannot have an existing desk reference.")
        first = signatures[orphan["confirm_id"]]
        for second in blotter_signatures:
            if first[:2] != second[:2]:
                continue
            differences = sum(first[field] != second[field] for field in [2, 3, 4])
            differences += int(abs(first[5] - second[5]) > tolerance)
            if differences <= 1:
                raise DatasetSafetyError(f"An unknown confirmation has a desk candidate: {orphan['confirm_id']}")


def generate_dataset(seed=1, clean=False, output_root=None):
    """Make 200 desk trades and write a separate folder for this run's seed or clean mode."""
    prices = load_prices(ROOT / "data/brent_spot.csv")
    rng = random.Random(seed)
    settings = json.loads((ROOT / "settings.json").read_text())
    settings["_expiry_calendar"] = load_expiry_calendar()
    safety_rejections = []
    for attempt in range(1, 101):
        seen_signatures = set()
        trades = []
        confirmations = []
        for index in range(200):
            trade = draw_unique_trade(index, prices, rng, seen_signatures, settings)
            trades.append(trade)
            confirmation = dict(trade)
            confirmation["trade_ref"] = confirmation.pop("trade_id")
            confirmation["confirm_id"] = f"C{index + 1:06d}"
            confirmations.append(confirmation)
        answers = []
        try:
            if not clean:
                confirmations, answers = plant_cases(trades, confirmations, rng, prices, settings)
            validate_dataset_safety(trades, confirmations, answers, settings)
        except DatasetSafetyError as error:
            safety_rejections.append({"attempt": attempt, "reason": str(error)})
            continue
        break
    else:
        raise RuntimeError("No safe dataset was produced after 100 seeded sampling attempts.")
    output_root = Path(output_root) if output_root is not None else ROOT / "data/generated"
    folder = output_root / ("clean" if clean else f"seed_{seed}")
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades, columns=BLOTTER_COLUMNS).to_csv(folder / "blotter.csv", index=False)
    pd.DataFrame(confirmations, columns=CONFIRM_COLUMNS).to_csv(folder / "confirmations.csv", index=False)
    pd.DataFrame(answers, columns=ANSWER_COLUMNS).to_csv(folder / "answer_key.csv", index=False)
    metadata = {"seed": seed, "clean": clean, "generation_attempts": attempt,
                "safety_rejections": safety_rejections}
    (folder / "generation_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return folder


def main():
    """Accept the seed and clean option, then print counts read from the written CSVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1, help="Seed for repeatable random choices (default: 1).")
    parser.add_argument("--clean", action="store_true", help="Write exact matches to data/generated/clean/.")
    args = parser.parse_args()
    folder = generate_dataset(seed=args.seed, clean=args.clean)
    blotter = pd.read_csv(folder / "blotter.csv")
    confirmations = pd.read_csv(folder / "confirmations.csv")
    answers = pd.read_csv(folder / "answer_key.csv")
    prices = pd.read_csv(ROOT / "data/brent_spot.csv")
    counts = answers.drop_duplicates("case_id")["case_type"].value_counts()
    report = {
        "folder": str(folder.relative_to(ROOT)), "seed": args.seed, "clean": args.clean,
        "price_month": prices["trade_date"].iloc[0][:7], "published_price_days": len(prices),
        "blotter_rows": len(blotter), "confirmation_rows": len(confirmations),
        "answer_key_rows": len(answers), "planted_cases": answers["case_id"].nunique(),
        "case_counts": {kind: int(count) for kind, count in counts.items()},
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
