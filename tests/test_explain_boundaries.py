"""Boundary audits of canonical-only context and explicit result identity."""
import copy
import csv
import io
from decimal import Decimal

from test_explain import real_run, explanation_module, assert_checked


def test_canonical_context_not_raw_rows_or_live_settings(make_trade, make_confirmation, engine_settings):
    snapshot = copy.deepcopy(engine_settings)
    snapshot["barrels_per_lot"] = 42
    trade = make_trade(quantity=" 1.25 ", side=" sell ", unit=" lots ", price_usd_bbl=" 80.12345 ", trade_date="2026-10-14")
    confirmation = make_confirmation(trade, quantity="2.25")
    run = real_run([trade], [confirmation], snapshot)
    # Raw trace and original uploads are not a second interpretation authority.
    run["explanation_context"]["trades"]["T001"]["_raw"].update(quantity="999", price_usd_bbl="999", side="BUY")
    run["blotter"][0].update(quantity="999", price_usd_bbl="999", side="BUY")
    run["confirmations"][0].update(quantity="999", price_usd_bbl="999")
    item = explanation_module().explain_result(run["results"][0], run)
    assert "sold 1.25 lots (52.5 barrels)" in item["what_happened"]
    assert "$80.12345" in item["what_happened"]
    assert item["how_value_is_worked_out"] == "42 barrels × $80.12345 per barrel = $3,365.18."
    assert_checked(item, run["results"][0])


def test_duplicate_with_blank_refs_full_identification(make_trade, make_confirmation, engine_settings):
    trade = make_trade(trade_date="2026-10-14", side="SELL", unit="BBL", quantity="5000")
    confirmations = [make_confirmation(trade, identifier="C" + str(i), trade_ref="") for i in range(3)]
    run = real_run([trade], confirmations, engine_settings)
    assert len(run["results"]) == 1 and run["results"][0]["break_type"] == "DUPLICATE"
    item = explanation_module().explain_result(run["results"][0], run)
    for detail in ["14 Oct 2026", "Fictional Energy Ltd", "sold", "Dec 2026", "5,000 barrels", "$80.00"]:
        assert detail in item["draft_query"]
    assert_checked(item, run["results"][0])


def test_exact_review_does_not_claim_identical_or_blank_references(make_trade, make_confirmation, engine_settings):
    trades = [make_trade(identifier="T1"), make_trade(identifier="T2")]
    confirms = [make_confirmation(trades[0], identifier="C1", trade_ref="unrecognised-ref"),
                make_confirmation(trades[0], identifier="C2", trade_ref="another-ref")]
    run = real_run(trades, confirms, engine_settings)
    assert run["results"][0]["break_type"] == "AMBIGUOUS"
    item = explanation_module().explain_result(run["results"][0], run)
    for key in ["what_happened", "draft_query"]:
        assert "identical" not in item[key].lower()
        assert "blank" not in item[key].lower()
        assert "nothing disagrees" not in item[key].lower()


def test_more_than_three_results_summary_keeps_only_existing_first_three(make_trade, make_confirmation, engine_settings):
    trades = [make_trade(identifier="T" + str(i), counterparty="Entity " + str(i)) for i in range(5)]
    confirms = [make_confirmation(trade, identifier="C" + str(i), price_usd_bbl="81") for i, trade in enumerate(trades)]
    run = real_run(trades, confirms, engine_settings)
    ex = explanation_module()
    assert len(run["results"]) == 5
    first = ex.results_summary(run)["start_here"]
    assert len(first) == 3
    assert all(row["trade_id"] in text for row, text in zip(run["results"][:3], first))
    assert run["results"][3]["trade_id"] not in " ".join(first)


def test_csv_quotes_source_labels_and_original_detection_columns(make_trade, make_confirmation, engine_settings):
    trade = make_trade(counterparty='Example, "Quoted" Ltd', broker="Example, Broker")
    run = real_run([trade], [make_confirmation(trade, price_usd_bbl="81")], engine_settings)
    exported = list(csv.DictReader(io.StringIO(explanation_module().report_csv(run).decode())))
    assert len(exported) == 1
    assert 'Example, "Quoted" Ltd' in exported[0]["what_happened"]
    assert exported[0]["detection_rule"] == run["results"][0]["detection_rule"]


def test_protected_modules_stay_byte_identical():
    import hashlib
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads((root / "tests/fixtures/hash_references/stage3_frozen_before.json").read_text())
    protected = ["src/" + name + ".py" for name in ["normalise", "match", "compare", "reconcile", "scorecard"]]
    for name in protected:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == baseline[name], name
