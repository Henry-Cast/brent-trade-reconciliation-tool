"""Whole-record exceptions and duplicate groups retain their reported identities."""


def test_near_match_review_lists_each_candidate_without_pairing(make_trade, make_confirmation, engine_settings):
    trades = [make_trade(identifier="T1", trade_date="2026-10-14"),
              make_trade(identifier="T2", trade_date="2026-10-14", price_usd_bbl="82")]
    confirmations = [make_confirmation(trades[0], identifier="C1", price_usd_bbl="81", trade_ref=""),
                     make_confirmation(trades[0], identifier="C2", price_usd_bbl="83", trade_ref="")]
    run = real_run(trades, confirmations, engine_settings)
    assert len(run["results"]) == 1
    result = run["results"][0]
    assert result["matching_rule"] == "RULE_4_NEAR_MATCH"
    ex = explanation_module()
    item = ex.explain_result(result, run)
    assert item["friendly_name"] == "Needs manual review"
    assert item["what_happened"] == "This tool cannot choose one pairing between trades T1, T2 and confirmations C1, C2. It has not guessed."
    assert item["how_value_is_worked_out"] == "No value is shown because the pairing is unresolved. The trade details may still need checking."
    assert item["suggested_next_step"] == "Ask the broker which confirmation belongs to each trade. Use the original execution record, including times if available. Do not choose a pairing from these records alone."
    expected_details = (
        "Trade T1: bought 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 on 14 Oct 2026 with Fictional Energy Ltd; "
        "Trade T2: bought 5 lots (5,000 barrels) of Dec 2026 Brent at $82.00 on 14 Oct 2026 with Fictional Energy Ltd; "
        "Confirmation C1: bought 5 lots (5,000 barrels) of Dec 2026 Brent at $81.00 on 14 Oct 2026 with Fictional Energy Ltd; "
        "Confirmation C2: bought 5 lots (5,000 barrels) of Dec 2026 Brent at $83.00 on 14 Oct 2026 with Fictional Energy Ltd")
    assert item["draft_query"] == ("Your confirmations C1, C2 could relate to more than one of our trades (T1, T2). "
        "Please tell us which confirmation relates to which trade. Details: " + expected_details + ".")
    assert item["sum_shown"] is False and item["sum_value"] == ""
    assert item["displayed_operands"] == []

import pytest
from test_explain import real_run, explanation_module, assert_checked


@pytest.mark.parametrize("missing", [True, False], ids=["missing", "unknown"])
def test_unilateral_template_full_identity(make_trade, make_confirmation, engine_settings, missing):
    trade = make_trade(trade_date="2026-10-14", side="SELL")
    confirmation = make_confirmation(trade, trade_ref="")
    run = real_run([trade] if missing else [], [] if missing else [confirmation], engine_settings)
    result = run["results"][0]
    ex = explanation_module()
    item = ex.explain_result(result, run)
    if missing:
        assert item["friendly_name"] == "Missing confirmation"
        assert item["what_happened"] == ("The desk booked trade T001: sold 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 "
            "with Fictional Energy Ltd via Example Broker on 14 Oct 2026. No matching confirmation was found in these files.")
        guidance = "First check whether a confirmation in this report quotes a different trade reference but matches this trade's details. Ask the broker to send the confirmation. If the broker has no record of the trade, check with the trader that it was executed and booked with the right broker and counterparty. Also check the unknown confirmations in this report: one may be this trade with more than one detail different."
        draft = "We have not been able to match a confirmation to our trade T001: sold 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 on 14 Oct 2026 with Fictional Energy Ltd. Please send your confirmation or tell us if you have no record of this trade."
        suffix = "This is the full value of the unconfirmed trade."
    else:
        assert item["friendly_name"] == "Unknown confirmation"
        assert item["what_happened"] == ("Confirmation C001 records the desk as having sold 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 "
            "with Fictional Energy Ltd on 14 Oct 2026. No matching trade was found in the desk's blotter.")
        guidance = "Ask the trader whether this trade was done but not booked. If confirmed, book it following the desk's procedure. If the desk does not recognise it, ask the broker whether it belongs to another client. Also check the missing confirmations: this may be one of those trades with more than one detail different."
        draft = "We cannot find a trade matching your confirmation C001: the desk sold 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 on 14 Oct 2026 with Fictional Energy Ltd. Please confirm the details and who gave the order while we check on our side."
        suffix = "This is the full value of the confirmed trade."
    assert item["how_value_is_worked_out"] == "5,000 barrels × $80.00 per barrel = $400,000.00. " + suffix
    assert item["suggested_next_step"] == guidance
    assert item["draft_query"] == draft
    assert_checked(item, result)


def test_three_duplicate_confirmations_use_confirmation_factors(make_trade, make_confirmation, engine_settings):
    trade = make_trade(trade_date="2026-10-14")
    confirmations = [make_confirmation(trade, identifier="C" + str(n), price_usd_bbl="81") for n in range(1, 4)]
    run = real_run([trade], confirmations, engine_settings)
    result = next(r for r in run["results"] if r["break_type"] == "DUPLICATE")
    ex = explanation_module()
    item = ex.explain_result(result, run)
    assert item["friendly_name"] == "Duplicate confirmation"
    assert item["what_happened"] == "The broker has confirmed trade T001 3 times: C1, C2, C3. The desk has it booked once."
    assert item["how_value_is_worked_out"] == "2 × 5,000 barrels × $81.00 per barrel = $810,000.00. This tool counts 2 confirmations beyond the one expected."
    assert item["suggested_next_step"] == ("Check how many trades were actually done. If only one, ask the broker to cancel the extra confirmations. "
        "If more than one, check whether trades are missing from the blotter before booking anything.")
    assert item["draft_query"] == ("We received 3 confirmations (C1, C2, C3) for our trade T001: bought 5 lots (5,000 barrels) of Dec 2026 Brent "
        "at $80.00 on 14 Oct 2026 with Fictional Energy Ltd. We have it booked once. Please confirm whether these are duplicate copies or separate trades, "
        "and cancel any extra copies.")
    assert_checked(item, result)
