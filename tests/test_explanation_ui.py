"""Rendered explanation, CSV and sample-download checks using the real application."""
from pathlib import Path
from collections import Counter
import csv
import io

import pytest
from test_app_ui import app_test, generate, uploaded_values

ROOT = Path(__file__).resolve().parents[1]


def test_results_intro_uses_reported_priorities(app_test):
    """The added introduction precedes unchanged financial figures and has three start-here items."""
    at = generate(app_test)
    assert not at.exception and not at.error
    text = "\n".join(item.value for item in at.text)
    assert "32 items need attention: 13 high priority, 17 standard, 2 for manual review." in text
    assert any(item.label == "How to read this" for item in at.expander)
    assert any("Start here" in item.value for item in at.markdown)
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["Total value of discrepancy"] == "$230,241,854.20"


def test_every_detail_renders_four_parts_and_single_captions(app_test):
    """All nine reported types display copyable drafts without replacing highlighted original records."""
    at = generate(app_test)
    run = at.session_state["run"]
    for kind in ["PRICE", "QUANTITY", "UNIT_ERROR", "SIDE", "CONTRACT_MONTH",
                 "MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION", "DUPLICATE", "AMBIGUOUS"]:
        index = next(i for i, row in enumerate(run["results"]) if row["break_type"] == kind)
        at.selectbox(key="exception_index").set_value(index).run()
        assert not at.exception
        headers = "\n".join(item.value for item in at.subheader)
        for title in ["A. What happened", "B. How the value is worked out", "C. Suggested next step", "D. Draft query to the broker"]:
            assert title in headers
        captions = [item.value for item in at.caption]
        assert captions.count("General guidance only. Follow your own desk's procedure.") == 1
        assert captions.count("Draft only. Nothing is sent by this tool.") == 1
        assert len(at.code) == 1 and at.code[0].value.strip()
        visible = "\n".join(item.value for item in at.text) + at.code[0].value
        assert "the engine" not in visible.lower()


def test_sample_pair_has_exactly_three_confirmation_changes(tmp_path):
    """The visitor example changes one price, one side and removes a third confirmation only."""
    from src.reconcile import reconcile_files
    clean, broken = ROOT / "sample_data/clean", ROOT / "sample_data/with_breaks"
    assert (clean / "blotter.csv").read_bytes() == (broken / "blotter.csv").read_bytes()
    read = lambda p: list(csv.DictReader(p.open()))
    before = {r["confirm_id"]: r for r in read(clean / "confirmations.csv")}
    after = {r["confirm_id"]: r for r in read(broken / "confirmations.csv")}
    assert len(before) == 10 and len(after) == 9
    assert len(before.keys() - after.keys()) == 1 and not (after.keys() - before.keys())
    fields = [(key, field) for key in after for field in before[key] if before[key][field] != after[key][field]]
    assert sorted(field for _, field in fields) == ["price_usd_bbl", "side"]
    assert fields[0][0] != fields[1][0]
    reconcile_files(broken / "blotter.csv", broken / "confirmations.csv", tmp_path / "results.csv", tmp_path / "matches.csv")
    assert Counter(r["break_type"] for r in read(tmp_path / "results.csv")) == Counter({"PRICE": 1, "SIDE": 1, "MISSING_CONFIRMATION": 1})


@pytest.mark.parametrize("sample,summary", [
    ("clean", "No exceptions found. All 10 trades matched on trade date, counterparty, buy/sell, delivery month, volume and price (within $0.01 per barrel)."),
    ("with_breaks", "3 items need attention: 2 high priority, 1 standard, 0 for manual review."),
])
def test_uploaded_samples_have_explanations_and_complete_csv(app_test, monkeypatch, sample, summary):
    """Uploaded files use the same explanation path; CSV keeps all original reported fields."""
    import streamlit as st
    from src.compare import RESULT_COLUMNS
    calls = []
    original = st.download_button

    def observe(label, data, *args, **kwargs):
        calls.append((label, data, kwargs))
        return original(label, data, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", observe)
    folder = ROOT / "sample_data" / sample
    uploaded_values(monkeypatch, (folder / "blotter.csv").read_bytes(), (folder / "confirmations.csv").read_bytes())
    at = app_test.run()
    at.button(key="upload_own").click().run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception and not at.error
    assert summary in "\n".join(item.value for item in at.text)
    report = next(data for _, data, kw in reversed(calls) if kw.get("key") == "download_exceptions")
    table = csv.DictReader(io.StringIO(report.decode("utf-8-sig")))
    assert table.fieldnames == RESULT_COLUMNS + ["friendly_name", "what_happened", "how_value_is_worked_out", "suggested_next_step"]
    rows = list(table)
    assert len(rows) == (0 if sample == "clean" else 3)
    expected = at.session_state["run"]["results"]
    for actual, source in zip(rows, expected):
        assert {key: actual[key] for key in RESULT_COLUMNS} == source
        assert actual["friendly_name"] and actual["what_happened"] and actual["suggested_next_step"]
        assert "the engine" not in " ".join(actual.values()).lower()
    assert at.radio(key="page").options == ["Reconciliation"]


def test_all_sample_downloads_preserve_included_bytes(app_test, monkeypatch):
    """Both labelled pairs download the exact included files without running reconciliation."""
    import streamlit as st
    calls = {}
    original = st.download_button

    def observe(label, data, *args, **kwargs):
        calls[kwargs.get("key")] = data
        return original(label, data, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", observe)
    at = app_test.run()
    assert not at.exception
    for sample in ["clean", "with_breaks"]:
        for role in ["blotter", "confirmations"]:
            assert calls["sample_" + sample + "_" + role] == (ROOT / "sample_data" / sample / (role + ".csv")).read_bytes()
    labels = "\n".join(item.value for item in at.markdown)
    assert "Clean: ten trades, no exceptions" in labels
    assert "With three breaks: price, buy/sell and missing confirmation" in labels
    assert at.session_state["run"] is None
