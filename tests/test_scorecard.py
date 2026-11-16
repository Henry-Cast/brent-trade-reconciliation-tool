"""Check strict scoring with small, independent synthetic examples."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pandas as pd
from decimal import Decimal
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_scorecard():
    """Load only the scorecard so these tests never run the engine."""
    spec = importlib.util.spec_from_file_location("scorecard", ROOT / "src/scorecard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer(kind="PRICE", trade="T1", confirm="C1", case="K1", outcome="BREAK"):
    """Make one answer-key row without depending on the generator."""
    return {"case_id": case, "case_type": kind, "trade_id": trade,
            "confirm_id": confirm, "expected_outcome": outcome}


def prediction(kind="PRICE", trade="T1", confirm="C1", **extra):
    """Make one exception row with optional group identifiers."""
    return {"break_type": kind, "trade_id": trade, "confirm_id": confirm, **extra}


def row(table, kind):
    """Select one case type from the scorecard table."""
    return table.set_index("case_type").loc[kind]


def test_exact_ids_and_type_are_required_for_a_detection():
    """A same-type result on different records is a miss and false alarm."""
    scorecard = load_scorecard()
    good, good_details = scorecard.score_records([prediction()], [answer()], [])
    assert row(good, "PRICE")["found"] == 1
    assert row(good, "PRICE")["precision"] == 1.0
    assert row(good, "PRICE")["recall"] == 1.0
    assert good_details["status"].tolist() == ["FOUND"]
    bad, details = scorecard.score_records([prediction(trade="T2")], [answer()], [])
    assert row(bad, "PRICE")[["found", "missed", "false_alarms"]].tolist() == [0, 1, 1]
    assert set(details["status"]) == {"MISSED", "FALSE_ALARM"}


def test_wrong_label_is_a_miss_and_a_predicted_type_false_alarm():
    """Correct records with the wrong label do not count as detections."""
    table, details = load_scorecard().score_records([prediction("QUANTITY")], [answer()], [])
    assert row(table, "PRICE")[["found", "missed", "mislabelled", "false_alarms"]].tolist() == [0, 1, 1, 0]
    assert row(table, "QUANTITY")[["found", "false_alarms"]].tolist() == [0, 1]
    missed = details[details["status"] == "MISSED"].iloc[0]
    assert missed["predicted_type"] == "QUANTITY"
    assert "mislabelled" in missed["reason"].lower()


def test_extra_prediction_is_a_false_alarm_not_a_second_detection():
    """Only one exact exception row can satisfy a planted case."""
    table, details = load_scorecard().score_records([prediction(), prediction()], [answer()], [])
    assert row(table, "PRICE")[["found", "missed", "false_alarms"]].tolist() == [1, 0, 1]
    assert row(table, "PRICE")["precision"] == 0.5
    assert details["status"].tolist() == ["FOUND", "FALSE_ALARM"]


def test_missing_prediction_is_a_miss_with_undefined_precision():
    """Absent detections have zero recall and no precision denominator."""
    table, _ = load_scorecard().score_records([], [answer()], [])
    assert row(table, "PRICE")[["missed", "precision", "recall"]].tolist() == [1, "N/A", 0.0]


def test_ambiguous_case_is_one_exact_group_not_individual_pairs():
    """Two key rows require every trade and confirmation in a single review."""
    answers = [answer("AMBIGUOUS", "T1", "C1", outcome="NEEDS_REVIEW"),
               answer("AMBIGUOUS", "T2", "C2", outcome="NEEDS_REVIEW")]
    full = prediction("AMBIGUOUS", "", "", candidate_trade_ids="T2;T1",
                      candidate_confirm_ids="C2;C1", outcome="NEEDS_REVIEW")
    table, details = load_scorecard().score_records([full], answers, [])
    assert row(table, "AMBIGUOUS")[["found", "missed", "false_alarms"]].tolist() == [1, 0, 0]
    assert details.iloc[0]["trade_ids"] == "T1;T2"
    assert details.iloc[0]["confirm_ids"] == "C1;C2"
    for partial in [prediction("AMBIGUOUS"),
                    dict(full, candidate_confirm_ids="C1"),
                    dict(full, candidate_trade_ids="T1;T2;T3")]:
        bad, _ = load_scorecard().score_records([partial], answers, [])
        assert row(bad, "AMBIGUOUS")[["found", "missed", "false_alarms"]].tolist() == [0, 1, 1]


def test_same_case_type_with_different_case_ids_stays_separate():
    """Grouping key rows must never merge unrelated planted cases."""
    answers = [answer(case="K1"), answer(trade="T2", confirm="C2", case="K2")]
    table, _ = load_scorecard().score_records([prediction()], answers, [])
    assert row(table, "PRICE")[["found", "missed"]].tolist() == [1, 1]


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_requires_every_raw_confirmation_without_picking_an_original(reverse):
    """Expand the key's extra confirmation to all records sharing the trade ref."""
    confirmations = [{"trade_ref": "T1", "confirm_id": "C9"},
                     {"trade_ref": "T1", "confirm_id": "C1"},
                     {"trade_ref": "T1", "confirm_id": "C4"},
                     {"trade_ref": "T2", "confirm_id": "C2"}]
    if reverse:
        confirmations.reverse()
    key = [answer("DUPLICATE", confirm="C9")]
    full = prediction("DUPLICATE", confirm="C9;C4;C1")
    table, details = load_scorecard().score_records([full], key, confirmations)
    assert row(table, "DUPLICATE")[["found", "missed", "false_alarms"]].tolist() == [1, 0, 0]
    assert details.iloc[0]["confirm_ids"] == "C1;C4;C9"
    for wrong in [prediction("DUPLICATE", confirm="C9"),
                  prediction("DUPLICATE", confirm="C1;C9"),
                  prediction("PRICE", confirm="C1;C4;C9")]:
        table, _ = load_scorecard().score_records([wrong], key, confirmations)
        assert row(table, "DUPLICATE")[["found", "missed"]].tolist() == [0, 1]
        assert table["false_alarms"].sum() == 1


@pytest.mark.parametrize("kind,trade,confirm", [
    ("MISSING_CONFIRMATION", "T1", ""), ("UNKNOWN_CONFIRMATION", "", "C1")])
def test_orphan_empty_identifiers_are_empty_sets(kind, trade, confirm):
    """CSV blanks, None and NaN represent absent records, not literal IDs."""
    expected = answer(kind, trade=trade, confirm=confirm)
    detected = prediction(kind, trade=trade or None, confirm=confirm or float("nan"))
    table, _ = load_scorecard().score_records([detected], [expected], [])
    assert row(table, kind)["found"] == 1


def test_quiet_traps_are_not_detection_successes_or_extra_false_alarms():
    """One alert touching either record spoils quietness but counts only once."""
    answers = [answer("ROUNDING", outcome="NO_BREAK"),
               answer("ROUNDING", "T2", "C2", "K2", "NO_BREAK"),
               answer("EQUIVALENT_UNITS", "T3", "C3", "K3", "NO_BREAK")]
    table, details = load_scorecard().score_records([
        prediction("QUANTITY", trade="T99", confirm="C1"),
        prediction("PRICE", trade="T3", confirm="C99")], answers, [])
    assert row(table, "ROUNDING")[["found", "missed", "false_alarms", "correctly_quiet"]].tolist() == [0, 0, 0, 1]
    assert row(table, "EQUIVALENT_UNITS")["correctly_quiet"] == 0
    assert row(table, "QUANTITY")["false_alarms"] == 1
    assert row(table, "PRICE")["false_alarms"] == 1
    assert table["false_alarms"].sum() == 2
    assert set(details["status"]) == {"CORRECTLY_QUIET", "INCORRECTLY_ALERTED", "FALSE_ALARM"}
    assert row(table, "ROUNDING")[["precision", "recall"]].tolist() == ["N/A", "N/A"]


def test_clean_dataset_has_no_detection_successes_and_no_defined_denominators():
    """An empty clean answer key cannot manufacture perfect precision or recall."""
    scorecard = load_scorecard()
    table, details = scorecard.score_records([], [], [])
    assert table[["found", "missed", "false_alarms", "mislabelled", "correctly_quiet"]].to_numpy().sum() == 0
    assert table["precision"].eq("N/A").all()
    assert table["recall"].eq("N/A").all()
    assert details.empty
    assert list(details.columns) == scorecard.DETAIL_COLUMNS


def test_unexpected_prediction_types_remain_in_the_report():
    """Unexpected labels are still visible as false alarms, not discarded."""
    table, _ = load_scorecard().score_records([prediction("UNEXPECTED")], [], [])
    assert row(table, "UNEXPECTED")[["found", "false_alarms", "precision", "recall"]].tolist() == [0, 1, 0.0, "N/A"]


def test_successfully_quiet_trap_has_a_separate_quiet_count():
    """Not alerting on a harmless case is not a true positive."""
    table, details = load_scorecard().score_records([], [answer("ROUNDING", outcome="NO_BREAK")], [])
    assert row(table, "ROUNDING")[["found", "missed", "correctly_quiet"]].tolist() == [0, 0, 1]
    assert details["status"].tolist() == ["CORRECTLY_QUIET"]


def test_name_resolution_counts_only_exact_planted_variant_pairs():
    """The report counts planted cases, excluding other matches and wrong pairs."""
    answers = [answer("COUNTERPARTY_VARIANT", "T1", "C1", "K1", "NO_BREAK"),
               answer("COUNTERPARTY_VARIANT", "T2", "C2", "K2", "NO_BREAK"),
               answer("COUNTERPARTY_VARIANT", "T3", "C3", "K3", "NO_BREAK"),
               answer("COUNTERPARTY_VARIANT", "T4", "C4", "K4", "NO_BREAK"),
               answer("ROUNDING", "T5", "C5", "K5", "NO_BREAK")]
    matches = [{"trade_id": "T1", "confirm_id": "C1", "counterparty_resolution": "GENERAL_RULES"},
               {"trade_id": "T1", "confirm_id": "C1", "counterparty_resolution": "GENERAL_RULES"},
               {"trade_id": "T2", "confirm_id": "C2", "counterparty_resolution": "ALIAS_TABLE"},
               {"trade_id": "T3", "confirm_id": "C3", "counterparty_resolution": "UNRESOLVED"},
               {"trade_id": "T4", "confirm_id": "C99", "counterparty_resolution": "GENERAL_RULES"},
               {"trade_id": "T5", "confirm_id": "C5", "counterparty_resolution": "GENERAL_RULES"}]
    report = load_scorecard().name_resolution_report(answers, matches)
    assert report.set_index("counterparty_resolution")["count"].to_dict() == {
        "GENERAL_RULES": 1, "ALIAS_TABLE": 1, "UNRESOLVED": 2}


def test_name_resolution_does_not_infer_a_method_from_candidate_lists():
    """Review candidates are not evidence that an actual pair was resolved."""
    answers = [answer("COUNTERPARTY_VARIANT", outcome="NO_BREAK")]
    matches = [{"trade_id": "", "confirm_id": "", "candidate_trade_ids": "T1",
                "candidate_confirm_ids": "C1", "counterparty_resolution": "GENERAL_RULES"}]
    report = load_scorecard().name_resolution_report(answers, matches)
    assert report.set_index("counterparty_resolution").loc["UNRESOLVED", "count"] == 1


@pytest.mark.parametrize("clean", [False, True])
def test_cli_writes_summary_details_and_name_counts_from_explicit_paths(tmp_path, clean):
    """The standalone command reads only supplied CSVs and prints measured tables."""
    paths = {name: tmp_path / (name + ".csv") for name in
             ["results", "answer-key", "confirmations", "matches", "output", "details", "name-report"]}
    inputs = {
        "results": ([prediction()], ["trade_id", "confirm_id", "break_type"]),
        "answer-key": ([answer(), answer("COUNTERPARTY_VARIANT", "T2", "C2", "K2", "NO_BREAK")],
                       ["case_id", "case_type", "trade_id", "confirm_id", "expected_outcome"]),
        "confirmations": ([{"trade_ref": "T1", "confirm_id": "C1"}], ["trade_ref", "confirm_id"]),
        "matches": ([{"trade_id": "T2", "confirm_id": "C2", "counterparty_resolution": "GENERAL_RULES"}],
                    ["trade_id", "confirm_id", "counterparty_resolution"])}
    for name, (records, columns) in inputs.items():
        pd.DataFrame([] if clean else records, columns=columns).to_csv(paths[name], index=False)
    command = [sys.executable, str(ROOT / "src/scorecard.py")]
    for name, path in paths.items():
        command.extend(["--" + name, str(path)])
    completed = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    assert "correctly_quiet" in completed.stdout
    assert "GENERAL_RULES" in completed.stdout
    assert completed.stderr == ""
    table = pd.read_csv(paths["output"], keep_default_na=False)
    details = pd.read_csv(paths["details"], keep_default_na=False)
    names = pd.read_csv(paths["name-report"], keep_default_na=False)
    assert row(table, "PRICE")["found"] == (0 if clean else 1)
    assert details.empty == clean
    assert names.set_index("counterparty_resolution").loc["GENERAL_RULES", "count"] == (0 if clean else 1)
    if clean:
        assert table["precision"].eq("N/A").all()


@pytest.mark.parametrize("confirmations", [[], [{"trade_ref": "T1", "confirm_id": "C1"}]])
def test_duplicate_key_cannot_be_scored_without_its_raw_confirmation_group(confirmations):
    """An incomplete raw group must not make an extra-only prediction look correct."""
    with pytest.raises(ValueError, match="DUPLICATE.*raw confirmation"):
        load_scorecard().score_records([prediction("DUPLICATE", confirm="C9")],
                                       [answer("DUPLICATE", confirm="C9")], confirmations)


def test_conflicting_answer_rows_cannot_silently_share_one_case_id():
    """A case cannot have two expected labels selected arbitrarily by row order."""
    with pytest.raises(ValueError, match="Conflicting.*K1"):
        load_scorecard().score_records([], [answer(), answer("SIDE")], [])


def test_cli_refuses_to_overwrite_an_input_file(tmp_path):
    """A mistyped output path must never overwrite a Stage 1 input."""
    source = tmp_path / "answer_key.csv"
    source.write_text("do not overwrite this input\n")
    arguments = ["--results", str(tmp_path / "results.csv"), "--answer-key", str(source),
                 "--confirmations", str(tmp_path / "confirmations.csv"),
                 "--matches", str(tmp_path / "matches.csv"), "--output", str(source),
                 "--details", str(tmp_path / "details.csv"),
                 "--name-report", str(tmp_path / "names.csv")]
    with pytest.raises(SystemExit) as error:
        load_scorecard().main(arguments)
    assert error.value.code == 2
    assert source.read_text() == "do not overwrite this input\n"


def test_cli_rejects_header_only_files_with_the_wrong_schema(tmp_path):
    """A malformed results file must not be reported as a clean reconciliation."""
    files = {name: tmp_path / (name + ".csv") for name in
             ["results", "answer-key", "confirmations", "matches", "output", "details", "name-report"]}
    files["results"].write_text("wrong_column\n")
    arguments = []
    for name, path in files.items():
        arguments.extend(["--" + name, str(path)])
    with pytest.raises(ValueError, match="results.*missing.*break_type"):
        load_scorecard().main(arguments)
    assert not files["output"].exists()


def test_duplicate_expansion_uses_exact_raw_trade_reference_equality():
    """A malformed multi-ID reference must not join an unrelated confirmation."""
    confirmations = [{"trade_ref": "T1", "confirm_id": "C1"},
                     {"trade_ref": "T1", "confirm_id": "C9"},
                     {"trade_ref": "T1;T2", "confirm_id": "C99"}]
    table, _ = load_scorecard().score_records([prediction("DUPLICATE", confirm="C1;C9")],
                                             [answer("DUPLICATE", confirm="C9")], confirmations)
    assert row(table, "DUPLICATE")[["found", "missed", "false_alarms"]].tolist() == [1, 0, 0]


def test_review_outcome_is_not_an_alternate_ambiguous_type():
    """The outcome label cannot substitute for the canonical AMBIGUOUS type."""
    expected = answer("AMBIGUOUS", outcome="NEEDS_REVIEW")
    table, _ = load_scorecard().score_records([prediction("NEEDS_REVIEW")], [expected], [])
    assert row(table, "AMBIGUOUS")[["found", "missed", "mislabelled"]].tolist() == [0, 1, 1]
    assert row(table, "NEEDS_REVIEW")["false_alarms"] == 1


def test_name_resolution_conflicting_methods_are_unresolved():
    """Contradictory traces must not select a favourable resolution method."""
    expected = answer("COUNTERPARTY_VARIANT", outcome="NO_BREAK")
    matches = [{"trade_id": "T1", "confirm_id": "C1", "counterparty_resolution": method}
               for method in ["GENERAL_RULES", "ALIAS_TABLE"]]
    report = load_scorecard().name_resolution_report([expected], matches)
    assert report.set_index("counterparty_resolution").loc["UNRESOLVED", "count"] == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_a_correct_other_field_is_not_mislabelled(reverse):
    """A correct PRICE row is not a wrongly labelled QUANTITY row when the pair has two breaks."""
    answers = [answer("PRICE", case="K1"), answer("QUANTITY", case="K2")]
    if reverse:
        answers.reverse()
    table, _ = load_scorecard().score_records([prediction("PRICE")], answers, [])
    assert row(table, "PRICE")["found"] == 1
    assert row(table, "QUANTITY")[["missed", "mislabelled"]].tolist() == [1, 0]
    assert table["false_alarms"].sum() == 0


def test_one_wrong_result_remains_one_false_alarm_for_multiple_missed_fields():
    """Mislabelled diagnoses missed cases, while false alarms count emitted rows only once."""
    answers = [answer("PRICE", case="K1"), answer("QUANTITY", case="K2")]
    table, _ = load_scorecard().score_records([prediction("SIDE")], answers, [])
    assert table["missed"].sum() == 2
    assert table["false_alarms"].sum() == 1
    assert table["mislabelled"].sum() == 2


def test_metric_ratios_use_decimal_not_binary_floating_point():
    """A fractional precision is computed with exact decimal division."""
    results = [prediction(), prediction(trade="T2", confirm="C2"), prediction(trade="T3", confirm="C3")]
    table, _ = load_scorecard().score_records(results, [answer()], [])
    value = row(table, "PRICE")["precision"]
    assert isinstance(value, Decimal)
    assert value == Decimal(1) / Decimal(3)


def test_duplicate_reference_whitespace_uses_the_engine_trim_convention():
    """Trim spaces before literal reference equality without splitting a reference into IDs."""
    confirms = [{"trade_ref": " T1 ", "confirm_id": "C1"},
                {"trade_ref": "T1", "confirm_id": "C9"}]
    table, _ = load_scorecard().score_records([prediction("DUPLICATE", confirm="C1;C9")],
                                             [answer("DUPLICATE", confirm="C9")], confirms)
    assert row(table, "DUPLICATE")["found"] == 1
