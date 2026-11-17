"""Only explicit singleton result identifiers can link already-reported differences."""
import copy

from test_explain import real_run, explanation_module, assert_checked


def test_multiple_exceptions_on_exact_same_explicit_pair(make_trade, make_confirmation, engine_settings):
    first = make_trade(identifier="T1")
    second = make_trade(identifier="T2", counterparty="Other Entity")
    confirmations = [make_confirmation(first, identifier="C1", price_usd_bbl="81", side="SELL", contract_month="2027-01"),
                     make_confirmation(second, identifier="C2", price_usd_bbl="81", quantity="6")]
    run = real_run([first, second], confirmations, engine_settings)
    before = copy.deepcopy(run)
    ex = explanation_module()
    for result in run["results"]:
        item = ex.explain_result(dict(result), run)
        number, noun = (2, "differences") if result["trade_id"] == "T1" else (1, "difference")
        assert item["what_happened"].endswith(f"This pair has {number} other {noun}, listed separately.")
        assert item["what_happened"].count("This pair has") == 1
        assert "Everything else agrees" not in item["what_happened"]
        assert_checked(item, result)
    assert run == before


def test_different_confirmations_and_group_rows_are_not_same_pair(make_trade, make_confirmation, engine_settings):
    trade = make_trade()
    confirmations = [make_confirmation(trade, identifier="C1", price_usd_bbl="81"),
                     make_confirmation(trade, identifier="C2", price_usd_bbl="81")]
    run = real_run([trade], confirmations, engine_settings)
    assert len(run["results"]) == 3
    for result in run["results"]:
        item = explanation_module().explain_result(result, run)
        assert "This pair has" not in item["what_happened"]
