"""Additional boundaries and ordering checks before looking at any scorecard."""
from decimal import Decimal

import pytest


def test_near_match_ambiguity_is_one_review_group(make_trade, make_confirmation, engine_settings):
    """Two one-field candidates must not be ranked by arbitrary row order or error size."""
    from src.normalise import normalise_records
    from src.match import match_records
    from src.compare import compare_matches

    trades = [make_trade("T001", price_usd_bbl="80.00"), make_trade("T002", price_usd_bbl="82.00")]
    confirm = make_confirmation(trades[0], trade_ref="", price_usd_bbl="81.00")
    matched = match_records(normalise_records(trades, "blotter", engine_settings),
                            normalise_records([confirm], "confirmations", engine_settings), engine_settings)
    results, audit = compare_matches(matched, engine_settings)
    assert len(results) == 1 and not audit
    assert results[0]["matching_rule"] == "RULE_4_NEAR_MATCH"
    assert results[0]["trade_id"] == "T001;T002"
    assert results[0]["priority"] == "REVIEW"


def test_exact_attribute_stage_finishes_before_near_matching(make_trade, make_confirmation, engine_settings):
    """An exact pair is reserved before another confirmation considers its near-match candidates."""
    from src.normalise import normalise_records
    from src.match import match_records

    trades = [make_trade("T001", quantity="5"), make_trade("T002", quantity="10")]
    confirmations = [make_confirmation(trades[0], "C001", trade_ref=""),
                     make_confirmation(trades[1], "C002", trade_ref="", price_usd_bbl="81.00")]
    result = match_records(normalise_records(trades, "blotter", engine_settings),
                           normalise_records(confirmations[::-1], "confirmations", engine_settings), engine_settings)
    assert [(p["trade"]["trade_id"], p["confirmation"]["confirm_id"], p["matching_rule"])
            for p in result["pairs"]] == [("T001", "C001", "RULE_3_ATTRIBUTES"),
                                         ("T002", "C002", "RULE_4_NEAR_MATCH")]


def test_engine_outputs_are_identical_after_input_row_permutations(make_trade, make_confirmation, engine_settings):
    """A mixed dataset must produce byte-serialisable identical rows in every input order."""
    from src.normalise import normalise_records
    from src.match import match_records
    from src.compare import compare_matches

    trades = [make_trade("T001"), make_trade("T002", quantity="10"),
              make_trade("T003", quantity="10"), make_trade("T004", quantity="25")]
    confirmations = [make_confirmation(trades[0], "C002"), make_confirmation(trades[0], "C001"),
                     make_confirmation(trades[1], "C003", trade_ref=""),
                     make_confirmation(trades[2], "C004", trade_ref="")]
    outputs = []
    for left, right in [(trades, confirmations), (trades[::-1], confirmations[::-1])]:
        matched = match_records(normalise_records(left, "blotter", engine_settings),
                                normalise_records(right, "confirmations", engine_settings), engine_settings)
        outputs.append(compare_matches(matched, engine_settings))
    assert outputs[0] == outputs[1]
    assert [row["priority"] for row in outputs[0][0]] == ["HIGH", "HIGH", "REVIEW"]


def test_quantity_error_is_not_double_reported_as_unit_error(make_trade, make_confirmation, engine_settings):
    """Changed numeric quantity and changed unit are QUANTITY unless the approved unit-error pattern holds."""
    from src.normalise import normalise_records
    from src.match import match_records
    from src.compare import compare_matches

    trade = make_trade()
    confirm = make_confirmation(trade, quantity="4000", unit="BBL")
    matched = match_records(normalise_records([trade], "blotter", engine_settings),
                            normalise_records([confirm], "confirmations", engine_settings), engine_settings)
    results, audit = compare_matches(matched, engine_settings)
    assert len(results) == 1 and results[0]["break_type"] == "QUANTITY"
    assert results[0]["value_of_discrepancy_usd"] == "80000.00"


def test_final_money_rounding_is_exact_half_up():
    """Rounding occurs on the final dollar display, not on matching tolerances or intermediate values."""
    from src.compare import dollars

    assert dollars(Decimal("100.005")) == "100.01"
    assert dollars(Decimal("100.004")) == "100.00"


@pytest.mark.parametrize("field,value", [("trade_date", "2026-10-02"),
                                         ("counterparty", "Unrelated Fuels Ltd"),
                                         ("trader", "Different Trader"), ("broker", "Different Broker")])
def test_undefined_discrepancies_stop_instead_of_being_ignored(make_trade, make_confirmation, engine_settings, field, value):
    """The spec supplies no break type/value for these reference-linked disagreements."""
    from src.normalise import normalise_records
    from src.match import match_records
    from src.compare import compare_matches, SpecAmbiguityError

    trade = make_trade()
    confirm = make_confirmation(trade, **{field: value})
    matched = match_records(normalise_records([trade], "blotter", engine_settings),
                            normalise_records([confirm], "confirmations", engine_settings), engine_settings)
    with pytest.raises(SpecAmbiguityError, match="Stop for clarification"):
        compare_matches(matched, engine_settings)


def test_different_duplicate_notionals_stop_without_selecting_an_original(make_trade, make_confirmation, engine_settings):
    """Unequal duplicate notionals cannot silently choose which confirmation was extra."""
    from src.normalise import normalise_records
    from src.match import match_records
    from src.compare import compare_matches, SpecAmbiguityError

    trade = make_trade()
    confirms = [make_confirmation(trade, "C001"), make_confirmation(trade, "C002", quantity="10")]
    matched = match_records(normalise_records([trade], "blotter", engine_settings),
                            normalise_records(confirms, "confirmations", engine_settings), engine_settings)
    with pytest.raises(SpecAmbiguityError, match="choosing an original"):
        compare_matches(matched, engine_settings)
