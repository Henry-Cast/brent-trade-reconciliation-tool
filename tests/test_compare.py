"""Exact discrepancy values, grouping, and priority conventions approved for Stage 2."""
from decimal import Decimal

import pytest


def compare_example(trades, confirmations, settings):
    """Run the three engine stages on small hand-written inputs without an answer key."""
    from src.normalise import normalise_records
    from src.match import match_records
    from src.compare import compare_matches

    matched = match_records(normalise_records(trades, "blotter", settings),
                            normalise_records(confirmations, "confirmations", settings), settings)
    return compare_matches(matched, settings)


@pytest.mark.parametrize("changes,kind,value", [
    ({"price_usd_bbl": "80.05"}, "PRICE", "250.00"),
    ({"quantity": "10"}, "QUANTITY", "400000.00"),
    ({"unit": "BBL"}, "UNIT_ERROR", "399600.00"),
    ({"side": "SELL"}, "SIDE", "800000.00"),
    ({"contract_month": "2027-01"}, "CONTRACT_MONTH", "400000.00"),
])
def test_each_valued_field_uses_the_spec_formula(make_trade, make_confirmation, engine_settings, changes, kind, value):
    """Check each financial formula using independently stated exact expected dollars."""
    trade = make_trade()
    confirm = make_confirmation(trade, **changes)
    results, matches = compare_example([trade], [confirm], engine_settings)
    assert len(results) == len(matches) == 1
    row = results[0]
    assert row["break_type"] == kind
    assert row["value_of_discrepancy_usd"] == value
    assert row["matching_rule"] == "RULE_2_REFERENCE"
    assert row["priority"] == ("HIGH" if kind == "SIDE" else "STANDARD")
    assert row["blotter_value"] and row["confirmation_value"]


def test_price_and_equivalent_units_tolerances_do_not_raise_alerts(make_trade, make_confirmation, engine_settings):
    """One-cent price differences and equivalent barrel quantities must both be harmless."""
    trade = make_trade()
    confirm = make_confirmation(trade, unit="BBL", quantity="5000", price_usd_bbl="80.01")
    results, matches = compare_example([trade], [confirm], engine_settings)
    assert results == [] and len(matches) == 1


def test_multiple_differing_fields_produce_separate_rows(make_trade, make_confirmation, engine_settings):
    """A valid reference can carry more than one genuine break, one result row per field."""
    trade = make_trade()
    confirm = make_confirmation(trade, side="SELL", price_usd_bbl="80.05", quantity="10")
    results, matches = compare_example([trade], [confirm], engine_settings)
    assert {row["break_type"] for row in results} == {"SIDE", "PRICE", "QUANTITY"}
    assert all(row["trade_id"] == "T001" and row["confirm_id"] == "C001" for row in results)
    assert results[0]["priority"] == "HIGH"
    standard = [Decimal(row["value_of_discrepancy_usd"]) for row in results if row["priority"] == "STANDARD"]
    assert standard == sorted(standard, reverse=True)


def test_duplicate_group_keeps_all_ids_and_values_two_extras(make_trade, make_confirmation, engine_settings):
    """Three confirmations for one trade mean one duplicate group and two extra notionals."""
    trade = make_trade()
    confirms = [make_confirmation(trade, identifier) for identifier in ["C003", "C001", "C002"]]
    results, matches = compare_example([trade], confirms, engine_settings)
    assert len(results) == 1 and len(matches) == 3
    duplicate = results[0]
    assert duplicate["break_type"] == "DUPLICATE"
    assert duplicate["trade_id"] == "T001" and duplicate["confirm_id"] == "C001;C002;C003"
    assert duplicate["value_of_discrepancy_usd"] == "800000.00"
    assert duplicate["priority"] == "HIGH" and duplicate["group_id"]
    assert len({row["group_id"] for row in matches}) == 1
    assert not any("original" in key.lower() for key in duplicate)


def test_one_review_row_lists_all_candidates_without_a_value(make_trade, make_confirmation, engine_settings):
    """One ambiguous group is one exception, not guessed pairs or missing/unknown side effects."""
    trades = [make_trade("T002"), make_trade("T001")]
    confirms = [make_confirmation(trades[0], "C002", trade_ref=""),
                make_confirmation(trades[1], "C001", trade_ref="")]
    results, matches = compare_example(trades, confirms, engine_settings)
    assert matches == [] and len(results) == 1
    review = results[0]
    assert review["break_type"] == "AMBIGUOUS" and review["outcome"] == "NEEDS_REVIEW"
    assert review["trade_id"] == review["candidate_trade_ids"] == "T001;T002"
    assert review["confirm_id"] == review["candidate_confirm_ids"] == "C001;C002"
    assert review["value_of_discrepancy_usd"] == "" and review["priority"] == "REVIEW"


def test_unpaired_records_use_their_own_notionals(make_trade, make_confirmation, engine_settings):
    """A missing trade and unrelated unknown confirmation are two distinct HIGH items."""
    trade = make_trade()
    other = make_trade("T999", trade_date="2026-10-02", quantity="10", price_usd_bbl="81.00")
    confirm = make_confirmation(other, "C999", trade_ref="")
    results, matches = compare_example([trade], [confirm], engine_settings)
    assert not matches
    by_type = {row["break_type"]: row for row in results}
    assert by_type["MISSING_CONFIRMATION"]["value_of_discrepancy_usd"] == "400000.00"
    assert by_type["UNKNOWN_CONFIRMATION"]["value_of_discrepancy_usd"] == "810000.00"
    assert all(row["matching_rule"] == "RULE_6_LEFTOVER" and row["priority"] == "HIGH" for row in results)
