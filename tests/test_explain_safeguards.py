"""Arithmetic checks never override authoritative reported values or invent operands."""
import copy
from decimal import Decimal

import pytest
from test_explain import real_run, explanation_module, assert_checked


@pytest.mark.parametrize("kind,changes", [
    ("PRICE", {"price_usd_bbl": "81"}), ("QUANTITY", {"quantity": "6"}),
    ("UNIT_ERROR", {"unit": "BBL"}), ("SIDE", {"side": "SELL"}),
    ("CONTRACT_MONTH", {"contract_month": "2027-01"}),
    ("MISSING_CONFIRMATION", {}), ("UNKNOWN_CONFIRMATION", {}), ("DUPLICATE", {}),
])
def test_tampered_authoritative_value_suppresses_formula_and_logs(make_trade, make_confirmation, engine_settings,
                                                                 kind, changes, caplog):
    trade = make_trade()
    confirms = [make_confirmation(trade, **changes)]
    if kind == "MISSING_CONFIRMATION":
        confirms = []
    if kind == "DUPLICATE":
        confirms.append(make_confirmation(trade, identifier="C2"))
    run = real_run([] if kind == "UNKNOWN_CONFIRMATION" else [trade], confirms, engine_settings)
    result = next(r for r in run["results"] if r["break_type"] == kind)
    result["value_of_discrepancy_usd"] = "1.23"
    before = copy.deepcopy(run)
    item = explanation_module().explain_result(result, run)
    assert item["how_value_is_worked_out"] == "This tool reports a value of discrepancy of $1.23. A checked sum is not available for this item."
    assert item["sum_shown"] is False and item["sum_value"] == ""
    assert item["displayed_operands"] == []
    assert "checked sum" in caplog.text.lower()
    assert run == before


def test_duplicate_equal_notionals_with_different_factors_falls_back(make_trade, make_confirmation, engine_settings, caplog):
    trade = make_trade()
    confirmations = [make_confirmation(trade, identifier="C1"),
                     make_confirmation(trade, identifier="C2", quantity="10", price_usd_bbl="40")]
    run = real_run([trade], confirmations, engine_settings)
    result = next(r for r in run["results"] if r["break_type"] == "DUPLICATE")
    item = explanation_module().explain_result(result, run)
    assert item["sum_shown"] is False
    assert item["how_value_is_worked_out"] == "This tool reports a value of discrepancy of $400,000.00. A checked sum is not available for this item."
    assert item["displayed_operands"] == []
    assert "checked sum" in caplog.text.lower()


@pytest.mark.parametrize("defect", ["missing_context", "missing_price", "missing_record", "blank_amount"])
def test_absent_operands_never_crash_or_print_unchecked_sum(make_trade, make_confirmation, engine_settings, defect, caplog):
    trade = make_trade()
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl="81")], engine_settings)
    if defect == "missing_context":
        run.pop("explanation_context")
    elif defect == "missing_price":
        run["explanation_context"]["trades"]["T001"].pop("_price")
    elif defect == "missing_record":
        run["explanation_context"]["confirmations"].clear()
    else:
        run["results"][0]["value_of_discrepancy_usd"] = ""
    item = explanation_module().explain_result(run["results"][0], run)
    assert item["sum_shown"] is False and item["sum_value"] == ""
    assert item["displayed_operands"] == []
    assert "×" not in item["how_value_is_worked_out"]
    assert "checked sum" in caplog.text.lower()


@pytest.mark.parametrize("amount", ["123.45", ""])
def test_future_type_is_manual_review_without_reclassification(make_trade, make_confirmation, engine_settings, amount):
    trade = make_trade()
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl="81")], engine_settings)
    result = dict(run["results"][0], break_type="FUTURE_CODE", value_of_discrepancy_usd=amount)
    before = copy.deepcopy(result)
    item = explanation_module().explain_result(result, run)
    assert item["friendly_name"] == "Needs manual review"
    assert item["what_happened"] == "This item needs manual review."
    assert item["how_value_is_worked_out"] == ("This tool reports a value of discrepancy of $123.45. A checked sum is not available for this item." if amount else "No value is shown.")
    assert "original" in item["suggested_next_step"] and "procedure" in item["suggested_next_step"]
    assert "T001" in item["draft_query"] and "C001" in item["draft_query"]
    assert item["sum_shown"] is False
    assert result == before


@pytest.mark.parametrize("price,other,quantity", [
    ("80.1234567", "81.9876543", "1.23456789"),
    ("80.00001", "80.02002", "1000000"),
    ("0.005", "0.025", "1.25"),
])
def test_exact_fractional_cents_and_fractional_barrels_preserved(make_trade, make_confirmation, engine_settings,
                                                               price, other, quantity):
    trade = make_trade(price_usd_bbl=price, quantity=quantity, unit="BBL")
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl=other)], engine_settings)
    item = explanation_module().explain_result(run["results"][0], run)
    assert "$" + price in item["what_happened"]
    assert_checked(item, run["results"][0])
    printed = item["how_value_is_worked_out"].split(" = ")[0].replace(" per barrel", "").replace(" barrels", "")
    factors = [Decimal(part.replace("$", "").replace(",", "")) for part in printed.split(" × ")]
    assert factors == [abs(Decimal(price)-Decimal(other)), Decimal(quantity)]
