"""Regressions found while reviewing the actual rendered wording."""
from test_explain import real_run, explanation_module, assert_checked
import pytest


def test_one_extra_confirmation_uses_singular_wording(make_trade, make_confirmation, engine_settings):
    trade = make_trade()
    run = real_run([trade], [make_confirmation(trade, identifier="C1"),
                             make_confirmation(trade, identifier="C2")], engine_settings)
    result = next(row for row in run["results"] if row["break_type"] == "DUPLICATE")
    item = explanation_module().explain_result(result, run)
    assert item["how_value_is_worked_out"] == "5,000 barrels x $80.00 per barrel = $400,000.00. This is the value of the one extra confirmation."
    assert len(item["displayed_operands"]) == 2
    assert_checked(item, result)


@pytest.mark.parametrize("defect", ["missing_price", "future_kind"])
def test_fallback_warning_identifies_records(make_trade, make_confirmation, engine_settings, caplog, defect):
    trade = make_trade()
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl="81")], engine_settings)
    result = run["results"][0]
    if defect == "missing_price":
        run["explanation_context"]["trades"]["T001"].pop("_price")
    else:
        result["break_type"] = "FUTURE_CODE"
    item = explanation_module().explain_result(result, run)
    assert not item["sum_shown"]
    assert "T001" in caplog.text and "C001" in caplog.text
    assert "checked sum" in caplog.text.lower()


def test_reading_help_avoids_implementation_jargon():
    help_text = explanation_module().reading_guide().lower()
    assert "canonical" not in help_text
    assert "operands" not in help_text


def test_unknown_type_blank_reference_draft_keeps_full_identity(make_trade, make_confirmation, engine_settings):
    trade = make_trade(trade_date="2026-10-14")
    run = real_run([trade], [make_confirmation(trade, trade_ref="", price_usd_bbl="81")], engine_settings)
    result = run["results"][0]
    result["break_type"] = "FUTURE_CODE"
    item = explanation_module().explain_result(result, run)
    for detail in ["14 Oct 2026", "Fictional Energy Ltd", "bought", "Dec 2026", "5 lots (5,000 barrels)", "$81.00"]:
        assert detail in item["draft_query"]
    assert "T001" in item["draft_query"] and "C001" in item["draft_query"]
    assert item["sum_shown"] is False


@pytest.mark.parametrize("defect", ["missing_context", "future_kind"])
def test_same_pair_closing_sentence_survives_manual_fallback(make_trade, make_confirmation, engine_settings, defect):
    trade = make_trade()
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl="81", side="SELL")], engine_settings)
    assert len(run["results"]) == 2
    if defect == "missing_context":
        run.pop("explanation_context")
    else:
        run["results"][0]["break_type"] = "FUTURE_CODE"
    items = explanation_module().explain_all(run)
    for item in items:
        assert item["what_happened"].endswith("This pair has 1 other difference, listed separately.")
