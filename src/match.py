"""Rules 2–4: establish record identity without consulting generated labels."""
from decimal import Decimal

from src.normalise import counterparty_resolution


def attribute_difference_count(trade, confirmation, settings):
    """Keep date and counterparty fixed, then count the four permitted differing fields."""
    if trade["_date"] != confirmation["_date"]:
        return None
    if counterparty_resolution(trade, confirmation) == "UNRESOLVED":
        return None
    differences = int(trade["side"] != confirmation["side"])
    differences += int(trade["contract_month"] != confirmation["contract_month"])
    differences += int(trade["_volume_bbl"] != confirmation["_volume_bbl"])
    differences += int(abs(trade["_price"] - confirmation["_price"]) > Decimal(settings["price_tolerance_usd_bbl"]))
    return differences


def apply_attribute_rule(trades, confirmations, settings, differing_fields, rule, pairs, reviews):
    """Pair unique candidates in deterministic rounds, then retain unresolved connected groups."""
    remaining_trades = dict(trades)
    remaining_confirmations = dict(confirmations)
    while True:
        candidates = {}
        for confirm_id, confirmation in sorted(remaining_confirmations.items()):
            candidates[confirm_id] = [trade_id for trade_id, trade in sorted(remaining_trades.items())
                                      if attribute_difference_count(trade, confirmation, settings) == differing_fields]
        unique = {confirm_id: ids[0] for confirm_id, ids in candidates.items() if len(ids) == 1}
        if not unique:
            break
        # All references to the same unique trade are retained; no original is selected.
        used_trades = set()
        for confirm_id, trade_id in sorted(unique.items()):
            pairs.append({"trade": remaining_trades[trade_id],
                          "confirmation": remaining_confirmations.pop(confirm_id),
                          "matching_rule": rule})
            used_trades.add(trade_id)
        for trade_id in used_trades:
            remaining_trades.pop(trade_id)
    active = {identifier: set(ids) for identifier, ids in candidates.items() if ids}
    while active:
        first = min(active)
        group_confirms = {first}
        group_trades = set(active[first])
        changed = True
        while changed:
            changed = False
            for confirm_id, trade_ids in sorted(active.items()):
                if trade_ids & group_trades:
                    before = (len(group_confirms), len(group_trades))
                    group_confirms.add(confirm_id)
                    group_trades.update(trade_ids)
                    changed = changed or before != (len(group_confirms), len(group_trades))
        reviews.append({"trades": [remaining_trades[identifier] for identifier in sorted(group_trades)],
                        "confirmations": [remaining_confirmations[identifier] for identifier in sorted(group_confirms)],
                        "matching_rule": rule})
        for identifier in group_confirms:
            active.pop(identifier)
            remaining_confirmations.pop(identifier)
        for identifier in group_trades:
            remaining_trades.pop(identifier)
    return remaining_trades, remaining_confirmations


def match_records(trades, confirmations, settings):
    """Use references first, exact attributes second, and one-field near matches third."""
    trade_map = {row["trade_id"]: row for row in trades}
    remaining_confirmations = {}
    pairs = []
    used_trades = set()
    reviews = []
    for confirmation in sorted(confirmations, key=lambda row: row["confirm_id"]):
        reference = confirmation["trade_ref"]
        if reference and reference in trade_map:
            pairs.append({"trade": trade_map[reference], "confirmation": confirmation,
                          "matching_rule": "RULE_2_REFERENCE"})
            used_trades.add(reference)
        else:
            remaining_confirmations[confirmation["confirm_id"]] = confirmation
    remaining_trades = {identifier: row for identifier, row in trade_map.items() if identifier not in used_trades}
    remaining_trades, remaining_confirmations = apply_attribute_rule(
        remaining_trades, remaining_confirmations, settings, 0, "RULE_3_ATTRIBUTES", pairs, reviews)
    remaining_trades, remaining_confirmations = apply_attribute_rule(
        remaining_trades, remaining_confirmations, settings, 1, "RULE_4_NEAR_MATCH", pairs, reviews)
    return {"pairs": sorted(pairs, key=lambda pair: (pair["trade"]["trade_id"], pair["confirmation"]["confirm_id"])),
            "reviews": reviews,
            "unmatched_trades": [row for identifier, row in sorted(remaining_trades.items())],
            "unmatched_confirmations": [row for identifier, row in sorted(remaining_confirmations.items())]}
