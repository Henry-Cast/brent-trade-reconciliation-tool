"""Presentation-only contracts, with real reconciliation of the included sample."""
from copy import deepcopy
from pathlib import Path

import pytest

import app_support as app
from src.explain import FRIENDLY_NAMES


ROOT = Path(__file__).resolve().parents[1]
# Measured ordinary-seed rows reviewed against seed1_before.json; no generation.
ORDINARY_SCORECARD = {
    "scores": [dict(case_type=code, found=str(found), missed="0", false_alarms="0",
                    mislabelled="0", precision="1" if found else "N/A",
                    recall="1" if found else "N/A", correctly_quiet=str(quiet))
               for code, found, quiet in [
                   ("PRICE", 6, 0), ("QUANTITY", 5, 0), ("SIDE", 3, 0),
                   ("CONTRACT_MONTH", 4, 0), ("UNIT_ERROR", 2, 0),
                   ("MISSING_CONFIRMATION", 4, 0), ("UNKNOWN_CONFIRMATION", 3, 0),
                   ("DUPLICATE", 3, 0), ("AMBIGUOUS", 2, 0),
                   ("EQUIVALENT_UNITS", 0, 5), ("COUNTERPARTY_VARIANT", 0, 4),
                   ("ROUNDING", 0, 3), ("MISSING_TRADE_REF", 0, 3)]],
    "names": [{"counterparty_resolution": code, "count": count}
              for code, count in [("GENERAL_RULES", "2"), ("ALIAS_TABLE", "2"), ("UNRESOLVED", "0")]],
}


def test_field_labels_are_plain_english_without_changing_keys():
    assert app.FIELD_LABELS == {
        "trade_id": "Trade ID", "confirm_id": "Confirmation ID",
        "trade_ref": "Desk trade reference", "trade_date": "Trade date",
        "trader": "Trader", "counterparty": "Counterparty", "broker": "Broker",
        "side": "Buy/sell", "contract_month": "Delivery month",
        "quantity": "Volume", "unit": "Unit", "price_usd_bbl": "Price in USD per barrel",
    }
    expected = {"price_usd_bbl": "Price", "quantity": "Volume", "unit": "Unit",
                "volume_bbl": "Volume/Unit", "side": "Buy/sell",
                "contract_month": "Delivery month", "confirmation_count": "Confirmations",
                "pairing": "Pairing", "record": "Record"}
    assert all(app.FIELD_DIFF_LABELS[key] == label for key, label in expected.items())


@pytest.mark.parametrize("code,label", list(FRIENDLY_NAMES.items()) + [
    ("EQUIVALENT_UNITS", "Equivalent volumes in different units"),
    ("COUNTERPARTY_VARIANT", "Counterparty name variation"),
    ("ROUNDING", "Harmless rounding difference"),
    ("MISSING_TRADE_REF", "Missing desk trade reference"),
    ("FUTURE_CASE", "Future case"),
])
def test_pretty_case_name_uses_reviewed_names_and_friendly_quiet_cases(code, label):
    assert app.pretty_case_name(code) == label


@pytest.mark.parametrize("measured,expected", [
    (deepcopy(ORDINARY_SCORECARD),
     "Found 32 of 32 planted cases. 0 missed, 0 false alarms. "
     "15 harmless differences correctly left alone."),
    ({"scores": [{"found": "2", "missed": "3", "mislabelled": "4",
                  "false_alarms": "5", "correctly_quiet": "6"},
                 {"found": 7, "missed": 8, "mislabelled": 9,
                  "false_alarms": 10, "correctly_quiet": 11}]},
     "Found 9 of 33 planted cases. 11 missed, 15 false alarms, 13 incorrectly labelled. "
     "17 harmless differences correctly left alone."),
    ({"scores": []}, "Found 0 of 0 planted cases. 0 missed, 0 false alarms. "
     "0 harmless differences correctly left alone."),
], ids=["archived-ordinary-seed", "all-counts-from-rows", "empty"])
def test_scorecard_headline_uses_only_measured_counts(measured, expected):
    original = deepcopy(measured)
    assert app.scorecard_headline(measured) == expected
    assert measured == original


def test_friendly_scorecard_frames_keep_authoritative_values_and_input_untouched():
    measured = deepcopy(ORDINARY_SCORECARD)
    original = deepcopy(measured)
    assert set(app.SCORE_COLUMN_LABELS) == set(measured["scores"][0])
    assert set(app.NAME_COLUMN_LABELS) == {"counterparty_resolution", "count"}
    assert all("_" not in label for label in
               list(app.SCORE_COLUMN_LABELS.values()) + list(app.NAME_COLUMN_LABELS.values()))
    scores = app.friendly_scorecard_frame(measured["scores"])
    names = app.friendly_scorecard_frame(measured["names"])
    expected_scores = [dict(row, case_type=app.pretty_case_name(row["case_type"]))
                       for row in original["scores"]]
    assert scores.to_dict("records") == expected_scores
    assert names.to_dict("records") == [
        {"counterparty_resolution": "Standard name rules", "count": "2"},
        {"counterparty_resolution": "Saved name aliases", "count": "2"},
        {"counterparty_resolution": "Not resolved", "count": "0"},
    ]
    scores.loc[0, "found"] = "999"
    names.loc[0, "count"] = "999"
    assert measured == original


def test_friendly_scorecard_frame_handles_empty_and_future_rows_without_losing_data():
    assert app.friendly_scorecard_frame([]).empty
    rows = [{"case_type": "FUTURE_CASE", "counterparty_resolution": "FUTURE_METHOD", "count": "7"}]
    assert app.friendly_scorecard_frame(rows).to_dict("records") == [
        {"case_type": "Future case", "counterparty_resolution": "Future method", "count": "7"}]


@pytest.mark.parametrize("affected,note,highlight", [
    ("price_usd_bbl", "The differing fields are marked below.", ["price_usd_bbl"]),
    ("volume_bbl", "The differing fields are marked below.", ["quantity", "unit"]),
    ("confirmation_count", "All confirmations are shown; this tool has not chosen an original.", ["trade_ref"]),
    ("pairing", "These records need manual pairing; this tool has not chosen a pair.", []),
    ("record", "The available records are shown below.", ["trade_id", "confirm_id", "trade_ref", "quantity"]),
], ids=["price", "volume", "group", "review", "whole-record"])
def test_exception_notes_change_only_words_not_raw_records_or_highlights(affected, note, highlight):
    run = {"blotter": [{"trade_id": " T1 ", "quantity": " 5.000 "},
                       {"trade_id": "T2", "quantity": "6"}],
           "confirmations": [{"confirm_id": "C1", "trade_ref": " T1 ", "quantity": "5000"},
                             {"confirm_id": "C2", "trade_ref": "T2", "quantity": "6000"}]}
    original = deepcopy(run)
    row = {"trade_id": "T1;T2", "confirm_id": "C1;C2", "field_affected": affected}
    details = app.exception_details(run, row)
    assert details == {"blotter": run["blotter"], "confirmations": run["confirmations"],
                       "highlight_fields": highlight, "note": note}
    details["blotter"][0]["quantity"] = "999"
    assert run == original


def test_run_sample_reconciles_included_files_as_uploads_deterministically(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("The included sample must not generate data or load a scorecard")

    monkeypatch.setattr(app.subprocess, "run", forbidden)
    monkeypatch.setattr(app, "load_scorecard", forbidden)
    calls = []
    uploads = app.run_uploads

    def observed_uploads(*args):
        calls.append(args)
        return uploads(*args)

    monkeypatch.setattr(app, "run_uploads", observed_uploads)
    first = app.run_sample(tmp_path)
    second = app.run_sample(tmp_path)
    source = ROOT / "sample_data/with_breaks"
    assert calls == [(tmp_path, "blotter.csv", (source / "blotter.csv").read_bytes(),
                      "confirmations.csv", (source / "confirmations.csv").read_bytes())] * 2
    assert first["origin"] == second["origin"] == "uploaded"
    assert first["seed"] is first["generation_metadata"] is None
    assert "scorecard" not in first
    assert {row["break_type"] for row in first["results"]} == {"PRICE", "SIDE", "MISSING_CONFIRMATION"}
    assert first["results"] == second["results"]
    assert first["matches"] == second["matches"]
    for filename in ("results.csv", "matches.csv"):
        assert (Path(first["folder"]) / filename).read_bytes() == (Path(second["folder"]) / filename).read_bytes()
    for filename in ("blotter.csv", "confirmations.csv"):
        assert (Path(first["folder"]) / filename).read_bytes() == (source / filename).read_bytes()


def test_missing_sample_file_has_plain_error_without_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ROOT", tmp_path)
    with pytest.raises(app.AppInputError) as caught:
        app.run_sample(tmp_path / "runs")
    assert str(caught.value) == "The included sample files are unavailable. Restore the sample files and try again."
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("message", [
    "This tool stopped before a safe dataset was available.",
    "This tool returned no usable dataset. Generate again.",
], ids=["creation-stopped", "no-usable-data"])
def test_dataset_creation_errors_use_this_tool_without_running_generation(message):
    import ast
    import inspect

    literals = {node.value for node in ast.walk(ast.parse(inspect.getsource(app.run_generated)))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert message in literals
    assert not any("The generator" in text or "The engine" in text for text in literals)
