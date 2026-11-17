"""Presentation-only entry paths and readable, unchanged result displays."""
from pathlib import Path
from decimal import Decimal
import csv
import io

from test_app_ui import app_test

ROOT = Path(__file__).resolve().parents[1]


def test_opening_has_three_direct_choices_and_collapsed_dataset_controls(app_test):
    at = app_test.run()
    assert not at.exception
    labels = {button.label for button in at.button}
    assert {"See an example (200 trades)", "Try a small sample with three breaks", "Upload your own files"} <= labels
    assert next(panel for panel in at.expander if panel.label == "Change dataset").proto.expanded is False
    visible = "\n".join(item.value for item in list(at.caption) + list(at.markdown) + list(at.text))
    assert "Built by Henry Cast" in visible
    assert "Compare the desk's trade blotter with broker confirmations, find differences and see what needs checking." in visible
    assert at.session_state["run"] is None


def test_example_one_click_produces_32_explanations_without_fallbacks(app_test):
    from src import explain
    import app_support as support
    at = app_test.run()
    at.button(key="see_example").click().run(timeout=30)
    assert not at.exception and not at.error
    run = at.session_state["run"]
    assert run["seed"] == 1 and run["origin"] == "generated"
    assert len(run["blotter"]) == 200
    assert support.summarise(run)["total_value"] == Decimal("230241854.20")
    items = explain.explain_all(run)
    assert len(items) == 32
    assert all(not item["what_happened"].startswith("This item needs manual review.") for item in items)
    for row, item in zip(run["results"], items):
        assert "A checked sum is not available" not in item["how_value_is_worked_out"]
        assert item["sum_shown"] is (row["break_type"] != "AMBIGUOUS")
    assert at.radio(key="page").options == ["Reconciliation", "Scorecard"]


def test_direct_small_sample_needs_no_upload_and_has_no_scorecard(app_test):
    from collections import Counter
    at = app_test.run()
    at.button(key="load_sample").click().run()
    assert not at.exception and not at.error
    run = at.session_state["run"]
    assert run["origin"] == "uploaded" and len(run["blotter"]) == 10
    assert Counter(row["break_type"] for row in run["results"]) == Counter({"PRICE": 1, "SIDE": 1, "MISSING_CONFIRMATION": 1})
    assert at.radio(key="page").options == ["Reconciliation"]
    assert not at.get("file_uploader")


def test_explanations_precede_friendly_supporting_records(app_test):
    at = app_test.run()
    at.button(key="see_example").click().run()
    index = next(i for i, row in enumerate(at.session_state["run"]["results"]) if row["break_type"] == "PRICE")
    at.selectbox(key="exception_index").set_value(index).run()
    assert not at.exception
    captions = [item.value for item in at.caption]
    assert "Differs: Price" in captions
    assert not any("Highlighted fields:" in value or "price_usd_bbl" in value for value in captions)
    headings = [node.value for node in at.main if node.type in {"subheader", "markdown"}]
    assert headings.index("D. Draft query to the broker") < headings.index("#### Blotter records")
    labels = [label for table in at.table for label in table.value.index]
    assert "Trade date" in labels and "Price in USD per barrel" in labels
    assert "price_usd_bbl" not in labels and "contract_month" not in labels


def test_scorecard_headline_uses_current_measured_results(app_test):
    at = app_test.run()
    at.button(key="see_example").click().run()
    at.radio(key="page").set_value("Scorecard").run()
    assert not at.exception
    text = "\n".join(item.value for item in list(at.text) + list(at.markdown))
    assert "Found 32 of 32 planted cases. 0 missed, 0 false alarms. 15 harmless differences correctly left alone." in text
    assert at.warning[0].value == "Correct against its specification on generated data with known answers. Not evidence of production readiness."
    measured = at.session_state["run"]["scorecard"]
    table = next(item.value for item in at.dataframe if "found" in item.value.columns)
    assert table.to_dict("records") == measured["scores"]


def test_total_is_in_full_width_container_not_a_column(app_test):
    at = app_test.run()
    at.button(key="see_example").click().run()
    total = next(item for item in at.metric if item.label == "Total value of discrepancy")
    assert total.value == "$230,241,854.20"
    for column in at.get("column"):
        assert all(metric.label != "Total value of discrepancy" for metric in column.metric)
    # A dedicated keyed container allows a scoped responsive rule and a real-browser width check.
    assert any('st-key-total_value' in item.value for item in at.markdown)


def test_default_results_use_no_internal_implementation_phrases(app_test):
    at = app_test.run()
    at.button(key="see_example").click().run()
    visible = "\n".join(str(item.value) for item in list(at.caption) + list(at.text) + list(at.markdown) + list(at.info))
    assert "the generator" not in visible.lower()
    assert "the engine" not in visible.lower()
    assert "whole-record" not in visible.lower()


def test_readable_exception_grid_keeps_original_export_columns(app_test, monkeypatch):
    import streamlit as st
    calls = []
    original = st.dataframe

    def observe(data, *args, **kwargs):
        calls.append((data, kwargs.get("column_config", {})))
        return original(data, *args, **kwargs)

    monkeypatch.setattr(st, "dataframe", observe)
    at = app_test.run()
    at.button(key="see_example").click().run()
    frame, config = next((frame, config) for frame, config in calls if "Matching rule" in frame.columns)
    assert list(frame.columns) == ["Priority", "Name", "Break type", "Trade IDs", "Confirmation IDs", "Value of discrepancy (USD)", "Matching rule", "Group"]
    assert config.get("Name", {}) is not None
