"""Approved explanations exercised with the unchanged canonical reconciliation path."""
import copy
import importlib
import importlib.util
from decimal import Decimal, ROUND_HALF_UP

import pytest


PAIR_CASES = [
    ("QUANTITY", {"quantity": "6"}, "Volume difference",
     "The broker's confirmation C001 shows 6 lots (6,000 barrels).",
     "1,000 barrels × $80.00 per barrel = $80,000.00.",
     "Check the agreed volume against the original execution record. The recorded volumes differ by 1,000 barrels. Amend the blotter or ask the broker for a corrected confirmation, whichever is wrong.",
     "Your confirmation C001 shows 6 lots (6,000 barrels). Please check your record and confirm the correct volume."),
    ("UNIT_ERROR", {"unit": "BBL"}, "Unit mismatch",
     "Confirmation C001 shows the same number 5, but the desk uses lots and the broker uses barrels. That is 5,000 barrels against 5 barrels.",
     "4,995 barrels × $80.00 per barrel = $399,600.00.",
     "The same number with different units can mean a unit was entered wrongly. Confirm the intended volume against the original execution record, then correct whichever record has the wrong unit.",
     "Your confirmation C001 shows 5 barrels. Please confirm whether the agreed volume is in lots or barrels and send a corrected confirmation if needed."),
    ("SIDE", {"side": "SELL"}, "Buy/sell mismatch",
     "The broker's confirmation C001 shows the desk as having sold.",
     "2 × 5,000 barrels × $80.00 per barrel = $800,000.00. The value is doubled because a trade booked the wrong way round would leave the position out by twice its volume.",
     "Treat this as urgent and tell the trader now. Check whether the desk bought or sold against the original execution record. Then amend the blotter or ask the broker for a corrected confirmation, whichever is wrong.",
     "Your confirmation C001 shows that we sold. Please check urgently and confirm the correct direction."),
    ("CONTRACT_MONTH", {"contract_month": "2027-01"}, "Wrong delivery month",
     "The broker's confirmation C001 shows Jan 2027.",
     "5,000 barrels × $80.00 per barrel = $400,000.00. The full trade value is shown because the whole trade may sit in the wrong delivery month.",
     "Check the delivery month against the original execution record. Until this is resolved, the desk may hold its position in a different month from the one it expects. Amend the blotter or ask the broker for a corrected confirmation, whichever is wrong.",
     "Your confirmation C001 shows Jan 2027. Please check your record and confirm the correct delivery month."),
]

from src.normalise import normalise_records
from src.match import match_records
from src.compare import compare_matches


def explanation_module():
    assert importlib.util.find_spec("src.explain") is not None, "Approved explanation API is missing"
    return importlib.import_module("src.explain")


def real_run(trades, confirmations, settings):
    """Use actual protected matching/comparison, never invented result classifications."""
    left = normalise_records(trades, "blotter", settings)
    right = normalise_records(confirmations, "confirmations", settings)
    results, matches = compare_matches(match_records(left, right, settings), settings)
    return {"results": results, "matches": matches, "blotter": trades, "confirmations": confirmations,
            "explanation_context": {"trades": {r["trade_id"]: r for r in left},
                                    "confirmations": {r["confirm_id"]: r for r in right},
                                    "settings": copy.deepcopy(settings)}}


def assert_checked(explanation, result):
    assert explanation["sum_shown"] is True
    assert explanation["sum_value"] == result["value_of_discrepancy_usd"]
    factors = explanation["displayed_operands"]
    product = Decimal(1)
    for operand in factors:
        product *= Decimal(operand["value"])
        assert operand["text"] in explanation["how_value_is_worked_out"]
    assert format(product.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f") == result["value_of_discrepancy_usd"]


def test_price_end_to_end_wording_and_checked_operands(make_trade, make_confirmation, engine_settings):
    trade = make_trade(trade_date="2026-10-14")
    confirmation = make_confirmation(trade, price_usd_bbl="81", trade_ref="")
    run = real_run([trade], [confirmation], engine_settings)
    before = copy.deepcopy(run)
    explain = explanation_module()
    result = run["results"][0]
    item = explain.explain_result(result, run)
    assert item["friendly_name"] == "Price difference"
    assert item["what_happened"] == ("The desk booked trade T001: bought 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 "
        "with Fictional Energy Ltd via Example Broker on 14 Oct 2026. The broker's confirmation C001 shows $81.00.")
    assert item["how_value_is_worked_out"] == "$1.00 per barrel × 5,000 barrels = $5,000.00."
    assert item["suggested_next_step"] == ("Check the price against the original execution record (a recorded call, chat or deal ticket) before changing either record. "
        "If the desk's booking is wrong, amend the blotter. If the confirmation is wrong, ask the broker for a corrected confirmation.")
    assert item["draft_query"] == ("Our trade T001: we bought 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 on 14 Oct 2026 with Fictional Energy Ltd. "
        "Your confirmation C001 shows $81.00. Please check your record and confirm the correct price.")
    assert_checked(item, result)
    assert run == before


@pytest.mark.parametrize("kind,changes,friendly,ending,sum_text,guidance,draft_ending", PAIR_CASES)
def test_paired_templates_stand_alone(make_trade, make_confirmation, engine_settings,
                                      kind, changes, friendly, ending, sum_text, guidance, draft_ending):
    trade = make_trade(trade_date="2026-10-14")
    run = real_run([trade], [make_confirmation(trade, trade_ref="", **changes)], engine_settings)
    result = run["results"][0]
    assert result["break_type"] == kind
    explain = explanation_module()
    item = explain.explain_result(result, run)
    assert item["friendly_name"] == friendly
    assert item["what_happened"] == ("The desk booked trade T001: bought 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 "
        "with Fictional Energy Ltd via Example Broker on 14 Oct 2026. " + ending)
    assert item["how_value_is_worked_out"] == sum_text
    assert item["suggested_next_step"] == guidance
    identity = "Our trade T001: " + ("our record shows we " if kind == "SIDE" else "we ")
    identity += "bought 5 lots (5,000 barrels) of Dec 2026 Brent at $80.00 on 14 Oct 2026 with Fictional Energy Ltd. "
    assert item["draft_query"] == identity + draft_ending
    assert_checked(item, result)
