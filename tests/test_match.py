"""Rule-order and deterministic matching tests on hand-written fictional records."""
import pytest


def test_reference_pairs_before_attributes_and_keeps_repeated_references(make_trade, make_confirmation, engine_settings):
    """References establish identity even when a compared field differs; no duplicate is discarded."""
    from src.normalise import normalise_records
    from src.match import match_records

    trade = make_trade()
    other = make_trade("T002", price_usd_bbl="81.00")
    confirmations = [make_confirmation(trade, "C002", price_usd_bbl="81.00"),
                     make_confirmation(trade, "C001")]
    result = match_records(normalise_records([trade, other], "blotter", engine_settings),
                           normalise_records(confirmations, "confirmations", engine_settings), engine_settings)
    assert {(p["trade"]["trade_id"], p["confirmation"]["confirm_id"], p["matching_rule"])
            for p in result["pairs"]} == {("T001", "C001", "RULE_2_REFERENCE"),
                                         ("T001", "C002", "RULE_2_REFERENCE")}
    assert [t["trade_id"] for t in result["unmatched_trades"]] == ["T002"]


def test_exact_attribute_match_uses_normalised_units_and_tolerance(make_trade, make_confirmation, engine_settings):
    """Rule 3 can pair an invalid or absent reference using actual normalised attributes."""
    from src.normalise import normalise_records
    from src.match import match_records

    trade = make_trade()
    confirm = make_confirmation(trade, trade_ref="", quantity="5000", unit="BBL", price_usd_bbl="80.01")
    result = match_records(normalise_records([trade], "blotter", engine_settings),
                           normalise_records([confirm], "confirmations", engine_settings), engine_settings)
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["matching_rule"] == "RULE_3_ATTRIBUTES"
    assert not result["reviews"]


@pytest.mark.parametrize("field,value", [("side", "SELL"), ("contract_month", "2027-01"),
                                         ("quantity", "10"), ("price_usd_bbl", "80.02")])
def test_exactly_one_specified_difference_can_pair_under_rule_4(make_trade, make_confirmation, engine_settings, field, value):
    """Each of the four permitted near-match fields is exercised independently."""
    from src.normalise import normalise_records
    from src.match import match_records

    trade = make_trade()
    confirm = make_confirmation(trade, trade_ref="", **{field: value})
    result = match_records(normalise_records([trade], "blotter", engine_settings),
                           normalise_records([confirm], "confirmations", engine_settings), engine_settings)
    assert result["pairs"][0]["matching_rule"] == "RULE_4_NEAR_MATCH"


def test_two_differences_or_a_different_date_cannot_be_near_matches(make_trade, make_confirmation, engine_settings):
    """Rule 4 cannot quietly relax date/counterparty or allow two changed fields."""
    from src.normalise import normalise_records
    from src.match import match_records

    for changes in [{"side": "SELL", "price_usd_bbl": "81.00"},
                    {"trade_date": "2026-10-02"}, {"counterparty": "Other Fuels Ltd"}]:
        trade = make_trade()
        confirm = make_confirmation(trade, trade_ref="", **changes)
        result = match_records(normalise_records([trade], "blotter", engine_settings),
                               normalise_records([confirm], "confirmations", engine_settings), engine_settings)
        assert not result["pairs"] and not result["reviews"]
        assert len(result["unmatched_trades"]) == len(result["unmatched_confirmations"]) == 1


def test_identical_trades_become_one_review_group_without_guessed_pairs(make_trade, make_confirmation, engine_settings):
    """Two equally plausible trades and confirmations stay unresolved as one connected group."""
    from src.normalise import normalise_records
    from src.match import match_records

    trades = [make_trade("T001"), make_trade("T002")]
    confirms = [make_confirmation(trades[0], "C001", trade_ref=""),
                make_confirmation(trades[1], "C002", trade_ref="")]
    for ordered_trades, ordered_confirms in [(trades, confirms), (trades[::-1], confirms[::-1])]:
        result = match_records(normalise_records(ordered_trades, "blotter", engine_settings),
                               normalise_records(ordered_confirms, "confirmations", engine_settings), engine_settings)
        assert not result["pairs"]
        assert len(result["reviews"]) == 1
        group = result["reviews"][0]
        assert {t["trade_id"] for t in group["trades"]} == {"T001", "T002"}
        assert {c["confirm_id"] for c in group["confirmations"]} == {"C001", "C002"}
        assert group["matching_rule"] == "RULE_3_ATTRIBUTES"
        assert not result["unmatched_trades"] and not result["unmatched_confirmations"]
