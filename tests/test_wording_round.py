"""Wording-only regressions; actual protected calculations remain authoritative."""
from copy import deepcopy
from decimal import Decimal

import pytest

import app_support as support
from src import explain
from test_explain import real_run, assert_checked
from test_app_ui import app_test, uploaded_values
from test_explanation_context import csv_bytes


@pytest.mark.parametrize("count,noun", [(0, "trades"), (1, "trade"), (2, "trades")])
def test_clean_summary_trade_count_grammar(make_trade, make_confirmation, engine_settings, count, noun):
    trades = [make_trade(identifier=f"T{i}") for i in range(count)]
    confirms = [make_confirmation(trade, identifier=f"C{i}") for i, trade in enumerate(trades)]
    run = real_run(trades, confirms, engine_settings)
    all_trades = "" if count == 1 else "All "
    assert explain.results_summary(run)["text"] == (
        f"No exceptions found. {all_trades}{count} {noun} matched on trade date, counterparty, buy/sell, "
        "delivery month, volume and price (within $0.01 per barrel).")


@pytest.mark.parametrize("count,opening", [(1, "1 item needs attention:"), (2, "2 items need attention:")])
def test_exception_summary_item_count_grammar(make_trade, engine_settings, count, opening):
    run = real_run([make_trade(identifier=f"T{i}") for i in range(count)], [], engine_settings)
    assert explain.results_summary(run)["text"] == f"{opening} {count} high priority, 0 standard, 0 for manual review."


@pytest.mark.parametrize("count,case,alarm,difference", [
    (0, "cases", "alarms", "differences"),
    (1, "case", "alarm", "difference"),
    (2, "cases", "alarms", "differences"),
])
def test_scorecard_count_grammar_preserves_measured_numbers(count, case, alarm, difference):
    measured = {"scores": [{"found": 0, "missed": count, "mislabelled": 0,
                            "false_alarms": count, "correctly_quiet": count}]}
    before = deepcopy(measured)
    assert support.scorecard_headline(measured) == (
        f"Found 0 of {count} planted {case}. {count} missed, {count} false {alarm}. "
        f"{count} harmless {difference} correctly left alone.")
    assert measured == before


@pytest.mark.parametrize("unit,quantity,volume", [("BBL", "1", "1 barrel"), ("LOTS", "1", "1 lot (1,000 barrels)"), ("BBL", "2", "2 barrels")])
def test_volume_nouns_follow_exact_existing_amount(make_trade, make_confirmation, engine_settings, unit, quantity, volume):
    trade = make_trade(unit=unit, quantity=quantity)
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl="81")], engine_settings)
    item = explain.explain_all(run)[0]
    assert "bought " + volume + " of" in item["what_happened"]
    assert "1 barrels" not in item["how_value_is_worked_out"]
    assert_checked(item, run["results"][0])


@pytest.mark.parametrize("count", [2, 3])
def test_duplicate_formulas_use_multiplication_symbol(make_trade, make_confirmation, engine_settings, count):
    trade = make_trade(quantity="1", unit="BBL")
    run = real_run([trade], [make_confirmation(trade, identifier=f"C{i}") for i in range(count)], engine_settings)
    row = next(row for row in run["results"] if row["break_type"] == "DUPLICATE")
    item = explain.explain_result(row, run)
    assert "1 barrel × $80.00 per barrel" in item["how_value_is_worked_out"]
    assert " x " not in item["how_value_is_worked_out"]
    assert f"{count} confirmations" in item["draft_query"]
    assert_checked(item, row)


def test_one_trade_upload_uses_singular_metric_labels(app_test, monkeypatch, make_trade, make_confirmation):
    trade = make_trade()
    uploaded_values(monkeypatch, csv_bytes([trade]), csv_bytes([make_confirmation(trade)]))
    at = app_test.run()
    at.button(key="upload_own").click().run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception and not at.error
    assert {metric.label for metric in at.metric} >= {"Trade processed", "Matched trade", "Established pair", "Review groups"}


def test_review_with_one_confirmation_uses_singular_labels(app_test, monkeypatch, make_trade, make_confirmation):
    first = make_trade(identifier="T1")
    second = make_trade(identifier="T2")
    confirmation = make_confirmation(first, identifier="C1", trade_ref="")
    uploaded_values(monkeypatch, csv_bytes([first, second]), csv_bytes([confirmation]))
    at = app_test.run()
    at.button(key="upload_own").click().run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception and not at.error
    run = at.session_state["run"]
    assert len(run["results"]) == 1 and run["results"][0]["break_type"] == "AMBIGUOUS"
    item = explain.explain_all(run)[0]
    assert "and confirmation C1." in item["what_happened"]
    assert item["draft_query"].startswith("Your confirmation C1 could relate")
    assert at.selectbox(key="exception_index").options == ["Needs manual review — trades T1;T2; confirmation C1"]
    assert "Review group" in {metric.label for metric in at.metric}
