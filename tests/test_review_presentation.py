"""Independent-review regressions using real app records and reconciliation."""
from copy import deepcopy
import csv
import io

import pytest

import app_support as support
from src import explain
from test_app_ui import ROOT, app_test, uploaded_values


def test_duplicate_supporting_records_have_no_field_highlight(app_test):
    at = app_test.run()
    at.button(key="see_example").click().run()
    run = at.session_state["run"]
    index = next(i for i, row in enumerate(run["results"])
                 if row["break_type"] == "DUPLICATE" and row["trade_id"] == "T000005")
    row = run["results"][index]
    detail = support.exception_details(run, row)
    assert detail["highlight_fields"] == []
    assert len(detail["confirmations"]) == 2
    at.selectbox(key="exception_index").set_value(index).run()
    assert not at.exception
    assert "2 confirmations are linked to desk trade T000005." in [item.value for item in at.caption]
    assert not any(item.value.startswith("Differs:") for item in at.caption)
    assert "All confirmations are shown; this tool has not chosen an original." in [item.value for item in at.markdown]


def upload_pair(case):
    folder = ROOT / "sample_data/clean"
    trades = list(csv.DictReader(io.StringIO((folder / "blotter.csv").read_text())))
    confirms = list(csv.DictReader(io.StringIO((folder / "confirmations.csv").read_text())))
    if case in {"matched", "unknown"}:
        confirms[0]["trade_ref"] = "NOT_IN_BLOTTER"
    if case == "unknown":
        confirms[0]["side"] = "SELL" if confirms[0]["side"] == "BUY" else "BUY"
        confirms[0]["price_usd_bbl"] = "999"
    if case == "extra":
        trades[0]["commission_usd"] = "25"
        for row in trades[1:]:
            row["commission_usd"] = "0"
        for row in confirms:
            row["settlement_terms"] = "T+2"
    def encode(rows):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return out.getvalue().encode()
    return encode(trades), encode(confirms), confirms[0]["confirm_id"]


@pytest.mark.parametrize("case", ["clean", "extra", "matched", "unknown"])
def test_clean_summary_and_upload_warnings_above_results(app_test, monkeypatch, case):
    blotter, confirmations, confirm_id = upload_pair(case)
    uploaded_values(monkeypatch, blotter, confirmations)
    at = app_test.run()
    at.button(key="upload_own").click().run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception and not at.error
    run = at.session_state["run"]
    expected = []
    if case == "extra":
        expected = ["Not checked: commission_usd, settlement_terms."]
    elif case in {"matched", "unknown"}:
        ending = ("It was matched on its details instead; check the reference with the broker."
                  if case == "matched" else "It could not be matched and is listed as an unknown confirmation; check the reference with the broker.")
        expected = [f"Confirmation {confirm_id} quotes trade reference NOT_IN_BLOTTER, which is not in the blotter. " + ending]
    assert support.input_warnings(run) == expected
    assert [item.value for item in at.warning] == expected
    if case != "unknown":
        assert explain.results_summary(run)["text"] == (
            "No exceptions found. All 10 trades matched on trade date, counterparty, buy/sell, "
            "delivery month, volume and price (within $0.01 per barrel).")
    else:
        assert {row["break_type"] for row in run["results"]} == {"MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION"}
    nodes = list(at.main)
    if expected:
        assert next(i for i, node in enumerate(nodes) if node.type == "warning") < next(i for i, node in enumerate(nodes) if node.type == "metric")


def test_missing_confirmation_uses_cautious_wording(app_test):
    at = app_test.run()
    at.button(key="load_sample").click().run()
    run = at.session_state["run"]
    row = next(row for row in run["results"] if row["break_type"] == "MISSING_CONFIRMATION")
    item = explain.explain_result(row, run)
    assert item["what_happened"].endswith("No matching confirmation was found in these files.")
    assert item["draft_query"].startswith(f"We have not been able to match a confirmation to our trade {row['trade_id']}:")
    assert item["suggested_next_step"].startswith("First check whether a confirmation in this report quotes a different trade reference but matches this trade's details. ")


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_report_csv_escapes_text_without_changing_numeric_values(app_test, monkeypatch, prefix):
    at = app_test.run()
    at.button(key="load_sample").click().run()
    run = deepcopy(at.session_state["run"])
    run["results"] = [next(row for row in run["results"] if row["break_type"] == "PRICE")]
    row = run["results"][0]
    for column in ["matching_rule", "group_id", "candidate_trade_ids", "candidate_confirm_ids", "outcome", "field_affected", "detection_rule"]:
        row[column] = prefix + "external text"
    row["blotter_value"] = "-123.45"
    row["confirmation_value"] = prefix + "external text"
    monkeypatch.setitem(explain.FRIENDLY_NAMES, "PRICE", prefix + "friendly name")
    before = deepcopy(run)
    exported = list(csv.DictReader(io.StringIO(explain.report_csv(run).decode())))[0]
    for column in ["matching_rule", "group_id", "candidate_trade_ids", "candidate_confirm_ids", "outcome", "field_affected", "detection_rule", "confirmation_value"]:
        assert exported[column] == "'" + row[column]
    assert exported["friendly_name"] == "'" + prefix + "friendly name"
    assert exported["blotter_value"] == "-123.45"
    assert exported["value_of_discrepancy_usd"] == row["value_of_discrepancy_usd"]
    assert run == before


def test_export_button_has_investigation_caption(app_test):
    at = app_test.run()
    at.button(key="load_sample").click().run()
    assert "Values are measures for investigation, not a loss, P&L or money owed. Values for different break types use different bases and should not be added together." in [item.value for item in at.caption]


def test_extra_column_warning_survives_exceptions(app_test, monkeypatch):
    blotter, confirmations, _ = upload_pair("extra")
    from test_app_ui import changed_csv
    confirmations = changed_csv(confirmations, "price_usd_bbl", "999")
    uploaded_values(monkeypatch, blotter, confirmations)
    at = app_test.run()
    at.button(key="upload_own").click().run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception and not at.error
    assert at.session_state["run"]["results"]
    assert "Not checked: commission_usd, settlement_terms." in [item.value for item in at.warning]


def test_dangling_reference_in_review_is_not_falsely_called_unknown(tmp_path):
    blotter, confirmations, _ = upload_pair("matched")
    trade_rows = list(csv.DictReader(io.StringIO(blotter.decode())))[:1]
    confirm_rows = list(csv.DictReader(io.StringIO(confirmations.decode())))[:1]
    trade_rows.append(dict(trade_rows[0], trade_id="T_REVIEW"))
    confirm_rows.append(dict(confirm_rows[0], confirm_id="C_REVIEW"))
    def encode(rows):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return out.getvalue().encode()
    run = support.run_uploads(tmp_path, "blotter.csv", encode(trade_rows), "confirmations.csv", encode(confirm_rows))
    assert len(run["results"]) == 1 and run["results"][0]["break_type"] == "AMBIGUOUS"
    warnings = support.input_warnings(run)
    assert len(warnings) == 2
    assert all("Its pairing needs manual review" in warning for warning in warnings)
    assert all("unknown confirmation" not in warning and "matched on its details" not in warning for warning in warnings)


@pytest.mark.parametrize("value", ["plain text", "'already escaped", "", "12.34"])
def test_csv_safe_text_is_unchanged(value):
    assert explain._spreadsheet_cell("trade_id", value) == value


def test_one_real_mislabelled_case_has_planted_total_one():
    from src import scorecard
    scores, _ = scorecard.score_records(
        [{"trade_id": "T1", "confirm_id": "C1", "break_type": "SIDE"}],
        [{"case_id": "CASE1", "trade_id": "T1", "confirm_id": "C1", "case_type": "PRICE", "expected_outcome": "BREAK"}], [])
    assert int(scores["missed"].sum()) == 1
    assert int(scores["mislabelled"].sum()) == 1
    assert support.scorecard_headline({"scores": scores.to_dict("records")}).startswith("Found 0 of 1 planted cases.")
