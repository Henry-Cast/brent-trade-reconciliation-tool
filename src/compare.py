"""Rules 5–6: deterministic exceptions and exact values, never realised loss or P&L."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import json

from src.normalise import counterparty_resolution

RESULT_COLUMNS = ["trade_id", "confirm_id", "break_type", "blotter_value", "confirmation_value",
                  "value_of_discrepancy_usd", "priority", "matching_rule", "group_id",
                  "candidate_trade_ids", "candidate_confirm_ids", "outcome", "field_affected", "detection_rule"]
MATCH_COLUMNS = ["trade_id", "confirm_id", "matching_rule", "group_id", "counterparty_resolution",
                 "blotter_volume_bbl", "confirmation_volume_bbl", "blotter_price_usd_bbl", "confirmation_price_usd_bbl"]
HIGH_TYPES = {"SIDE", "MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION", "DUPLICATE"}


class SpecAmbiguityError(ValueError):
    """Stop rather than invent a classification or valuation absent from the approved rules."""


def dollars(amount):
    """Round only the final USD display to cents, using decimal half-up rounding."""
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def result_row(trade_ids, confirm_ids, kind, left, right, amount, rule, field, group_id=""):
    """Build the agreed result schema, with no monetary placeholder for unresolved groups."""
    return {"trade_id": ";".join(sorted(trade_ids)), "confirm_id": ";".join(sorted(confirm_ids)),
            "break_type": kind, "blotter_value": str(left), "confirmation_value": str(right),
            "value_of_discrepancy_usd": "" if amount is None else dollars(amount),
            "priority": "REVIEW" if kind == "AMBIGUOUS" else ("HIGH" if kind in HIGH_TYPES else "STANDARD"),
            "matching_rule": rule, "group_id": group_id,
            "candidate_trade_ids": ";".join(sorted(trade_ids)) if kind == "AMBIGUOUS" else "",
            "candidate_confirm_ids": ";".join(sorted(confirm_ids)) if kind == "AMBIGUOUS" else "",
            "outcome": "NEEDS_REVIEW" if kind == "AMBIGUOUS" else "BREAK", "field_affected": field,
            "detection_rule": "RULE_6_DUPLICATE" if kind == "DUPLICATE" else
                              ("RULE_6_LEFTOVER" if kind in {"MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION"}
                               else (rule if kind == "AMBIGUOUS" else "RULE_5_COMPARE"))}


def compare_pair(pair, settings):
    """Compare each financial field after identity has been established and value each difference."""
    trade, confirmation = pair["trade"], pair["confirmation"]
    if trade["_date"] != confirmation["_date"] or counterparty_resolution(trade, confirmation) == "UNRESOLVED":
        raise SpecAmbiguityError("A referenced pair differs in date/counterparty; SPEC provides no break valuation. Stop for clarification.")
    for field in ["trader", "broker"]:
        if " ".join(trade[field].upper().split()) != " ".join(confirmation[field].upper().split()):
            raise SpecAmbiguityError(f"A paired record differs in {field}; SPEC provides no break valuation. Stop for clarification.")
    results = []
    trade_ids, confirm_ids = [trade["trade_id"]], [confirmation["confirm_id"]]
    rule = pair["matching_rule"]
    volume = trade["_volume_bbl"]
    price = trade["_price"]
    if abs(price - confirmation["_price"]) > Decimal(settings["price_tolerance_usd_bbl"]):
        results.append(result_row(trade_ids, confirm_ids, "PRICE", trade["_raw"]["price_usd_bbl"],
                                  confirmation["_raw"]["price_usd_bbl"],
                                  abs(price - confirmation["_price"]) * volume, rule, "price_usd_bbl"))
    if volume != confirmation["_volume_bbl"]:
        unit_error = trade["_quantity"] == confirmation["_quantity"] and trade["unit"] != confirmation["unit"]
        kind = "UNIT_ERROR" if unit_error else "QUANTITY"
        left = f"{trade['quantity']} {trade['unit']} ({volume} BBL)"
        right = f"{confirmation['quantity']} {confirmation['unit']} ({confirmation['_volume_bbl']} BBL)"
        results.append(result_row(trade_ids, confirm_ids, kind, left, right,
                                  abs(volume - confirmation["_volume_bbl"]) * price, rule, "volume_bbl"))
    if trade["side"] != confirmation["side"]:
        results.append(result_row(trade_ids, confirm_ids, "SIDE", trade["_raw"]["side"],
                                  confirmation["_raw"]["side"], Decimal(2) * volume * price, rule, "side"))
    if trade["contract_month"] != confirmation["contract_month"]:
        results.append(result_row(trade_ids, confirm_ids, "CONTRACT_MONTH", trade["contract_month"],
                                  confirmation["contract_month"], volume * price, rule, "contract_month"))
    return results


def compare_matches(matched, settings):
    """Compare pairs first, then classify duplicate groups and leftovers without guessing originals."""
    results = []
    audit = []
    groups = defaultdict(list)
    for pair in matched["pairs"]:
        results.extend(compare_pair(pair, settings))
        groups[pair["trade"]["trade_id"]].append(pair)
    for trade_id, pairs in sorted(groups.items()):
        duplicate_group = "DUPLICATE:" + trade_id if len(pairs) > 1 else ""
        for pair in pairs:
            trade, confirmation = pair["trade"], pair["confirmation"]
            audit.append({"trade_id": trade_id, "confirm_id": confirmation["confirm_id"],
                          "matching_rule": pair["matching_rule"], "group_id": duplicate_group,
                          "counterparty_resolution": counterparty_resolution(trade, confirmation),
                          "blotter_volume_bbl": str(trade["_volume_bbl"]),
                          "confirmation_volume_bbl": str(confirmation["_volume_bbl"]),
                          "blotter_price_usd_bbl": str(trade["_price"]),
                          "confirmation_price_usd_bbl": str(confirmation["_price"])})
        if len(pairs) > 1:
            notionals = {pair["confirmation"]["_volume_bbl"] * pair["confirmation"]["_price"] for pair in pairs}
            if len(notionals) != 1:
                raise SpecAmbiguityError("Duplicate confirmations have different notionals; identifying extra notional would require choosing an original. Stop for clarification.")
            extra_notional = next(iter(notionals)) * Decimal(len(pairs) - 1)
            rules = ";".join(sorted({pair["matching_rule"] for pair in pairs}))
            results.append(result_row([trade_id], [pair["confirmation"]["confirm_id"] for pair in pairs],
                                      "DUPLICATE", "1 expected confirmation", f"{len(pairs)} confirmations",
                                      extra_notional, rules, "confirmation_count", duplicate_group))
    for index, group in enumerate(matched["reviews"], start=1):
        trades = {row["trade_id"]: row["_raw"] for row in group["trades"]}
        confirms = {row["confirm_id"]: row["_raw"] for row in group["confirmations"]}
        results.append(result_row(list(trades), list(confirms), "AMBIGUOUS",
                                  json.dumps(trades, sort_keys=True), json.dumps(confirms, sort_keys=True),
                                  None, group["matching_rule"], "pairing", f"REVIEW:{index:04d}"))
    for trade in matched["unmatched_trades"]:
        results.append(result_row([trade["trade_id"]], [], "MISSING_CONFIRMATION",
                                  json.dumps(trade["_raw"], sort_keys=True), "ABSENT",
                                  trade["_volume_bbl"] * trade["_price"], "RULE_6_LEFTOVER", "record"))
    for confirmation in matched["unmatched_confirmations"]:
        results.append(result_row([], [confirmation["confirm_id"]], "UNKNOWN_CONFIRMATION", "ABSENT",
                                  json.dumps(confirmation["_raw"], sort_keys=True),
                                  confirmation["_volume_bbl"] * confirmation["_price"], "RULE_6_LEFTOVER", "record"))
    priorities = {"HIGH": 0, "STANDARD": 1, "REVIEW": 2}
    results.sort(key=lambda row: (priorities[row["priority"]],
                                 -Decimal(row["value_of_discrepancy_usd"] or "0"),
                                 row["trade_id"], row["confirm_id"], row["break_type"]))
    audit.sort(key=lambda row: (row["trade_id"], row["confirm_id"]))
    return results, audit
