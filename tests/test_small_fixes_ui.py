"""Small presentation fixes through the real app controls."""
from decimal import Decimal

import pytest

from test_app_ui import ROOT, app_test, uploaded_values

CHOICES = ("see_example", "load_sample", "upload_own")


def assert_choice(at, selected):
    assert not at.exception
    for key in CHOICES:
        assert at.button(key=key).proto.type == ("primary" if key == selected else "secondary")


def test_opening_choices_are_initially_neutral(app_test):
    assert_choice(app_test.run(), None)


def test_choice_highlight_and_data_label_follow_all_transitions(app_test, monkeypatch):
    from src import explain
    import app_support as support
    folder = ROOT / "sample_data/clean"
    uploaded_values(monkeypatch, (folder / "blotter.csv").read_bytes(),
                    (folder / "confirmations.csv").read_bytes())
    at = app_test.run()
    for key, label in [
        ("see_example", "Example: 200 fictional trades with planted errors (dataset 1)."),
        ("load_sample", "Small sample: 10 trades with three planted breaks."),
        ("upload_own", "Your uploaded files."),
        ("see_example", "Example: 200 fictional trades with planted errors (dataset 1)."),
    ]:
        at.button(key=key).click().run()
        assert_choice(at, key)
        assert label in [item.value for item in at.caption]
        if key == "see_example":
            run = at.session_state["run"]
            assert support.summarise(run)["total_value"] == Decimal("230241854.20")
            assert len(explain.explain_all(run)) == 32
            at.radio(key="page").set_value("Scorecard").run()
            assert label in [item.value for item in at.caption]
        elif key == "load_sample":
            assert at.radio(key="page").options == ["Reconciliation"]
        else:
            assert at.session_state["run"] is None
            at.button(key="reconcile_uploads").click().run()
            assert_choice(at, key)
            assert label in [item.value for item in at.caption]
            assert at.radio(key="page").options == ["Reconciliation"]


def test_dataset_control_uses_actual_dataset_label_and_example_highlight(app_test):
    at = app_test.run()
    at.button(key="load_sample").click().run()
    at.number_input(key="seed").set_value(2).run()
    at.button(key="generate").click().run()
    assert_choice(at, "see_example")
    assert "Example: 200 fictional trades with planted errors (dataset 2)." in [item.value for item in at.caption]


def test_clear_session_resets_choice_highlight_and_data_label(app_test):
    at = app_test.run()
    at.button(key="load_sample").click().run()
    at.button(key="clear_session").click().run()
    assert_choice(at, None)
    assert not any(item.value.startswith("Small sample:") for item in at.caption)


@pytest.mark.parametrize("kind,expected", [
    ("MISSING_CONFIRMATION", "No confirmation to compare against."),
    ("UNKNOWN_CONFIRMATION", "No desk trade to compare against."),
    ("PRICE", "Differs: Price"),
    ("SIDE", "Differs: Buy/sell"),
])
def test_supporting_comparison_line_uses_existing_case_type(app_test, kind, expected):
    from src import explain
    at = app_test.run()
    at.button(key="see_example").click().run()
    run = at.session_state["run"]
    before = explain.explain_all(run)
    csv_before = explain.report_csv(run)
    index = next(i for i, row in enumerate(run["results"]) if row["break_type"] == kind)
    at.selectbox(key="exception_index").set_value(index).run()
    assert not at.exception
    captions = [item.value for item in at.caption]
    assert expected in captions
    if kind in {"MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION"}:
        assert not any(value.startswith("Differs:") for value in captions)
    assert explain.explain_all(at.session_state["run"]) == before
    assert explain.report_csv(at.session_state["run"]) == csv_before
