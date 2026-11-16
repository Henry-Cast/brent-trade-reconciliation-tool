"""AppTest checks of rendered Stage 3 flows, separate from browser checks."""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
LABEL = "Prices are simulated, anchored to published Brent spot prices."
CAVEAT = ("Correct against its specification on generated data with known answers. "
          "Not evidence of production readiness.")


@pytest.fixture
def app_test(monkeypatch):
    """Run the real entrypoint with project-local runtime storage and clean up its session."""
    monkeypatch.setenv("HOME", str(ROOT / ".cache/streamlit-home"))
    monkeypatch.setenv("TMPDIR", str(ROOT / ".cache/tmp"))
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    yield at
    try:
        resource = at.session_state["_workspace"]
    except KeyError:
        resource = None
    if resource is not None:
        resource.cleanup()


def test_exact_application_and_browser_title(app_test, monkeypatch):
    """Both the visible heading and Streamlit page configuration use the approved exact title."""
    import streamlit as st
    original = st.set_page_config
    configurations = []

    def observed(*args, **kwargs):
        """Observe the real page configuration without replacing its behavior."""
        configurations.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "set_page_config", observed)
    at = app_test.run()
    assert not at.exception
    assert at.title[0].value == "Brent Trade Reconciliation Tool"
    assert configurations[-1]["page_title"] == "Brent Trade Reconciliation Tool"


def test_initial_screen_has_required_label_and_no_scorecard(app_test):
    """A new session cannot show measured scores before data was generated in that session."""
    at = app_test.run()
    assert not at.exception
    assert any(LABEL in item.value for item in at.caption)
    assert at.radio(key="input_mode").options == ["Upload files", "Generate data"]
    assert at.radio(key="page").options == ["Reconciliation"]


def generate(at, seed=1):
    """Use the real controls to generate and reconcile a dataset in this AppTest session."""
    at.run()
    at.radio(key="input_mode").set_value("Generate data").run()
    at.number_input(key="seed").set_value(seed).run()
    at.button(key="generate").click().run(timeout=30)
    return at


def test_generated_screen_has_counts_and_break_type_values(app_test):
    """The rendered summary distinguishes trades from pair records and keeps review values blank."""
    at = generate(app_test)
    assert not at.exception and not at.error
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["Trades processed"] == "200"
    assert metrics["Matched trades"] == "192"
    assert metrics["Established pairs"] == "195"
    assert metrics["Review groups"] == "2"
    tables = [item.value for item in at.dataframe]
    table = next(frame for frame in tables if "Count" in frame.columns and "Break type" in frame.columns)
    review = table[table["Break type"] == "AMBIGUOUS"].iloc[0]
    assert str(review["Count"]) == "2"
    assert review["Value of discrepancy (USD)"] == ""
    assert at.radio(key="page").options == ["Reconciliation", "Scorecard"]


def test_generated_scorecard_displays_actual_measurements_and_caveat(app_test):
    """Only generated data offers a scorecard, calculated by the existing scorer."""
    at = generate(app_test)
    at.radio(key="page").set_value("Scorecard").run()
    assert not at.exception
    assert any(CAVEAT == item.value for item in at.warning)
    table = next(item.value for item in at.dataframe if "found" in item.value.columns)
    assert table["found"].astype(int).sum() == 32
    assert table["missed"].astype(int).sum() == 0


def test_switching_to_uploads_removes_generated_scores_and_stale_results(app_test):
    """A previous generated run cannot make user uploads eligible for measured scores."""
    at = generate(app_test)
    at.radio(key="page").set_value("Scorecard").run()
    at.radio(key="input_mode").set_value("Upload files").run()
    assert not at.exception
    assert at.radio(key="page").options == ["Reconciliation"]
    assert at.session_state["run"] is None
    assert not at.metric


def test_development_seed_retry_log_is_visible_without_an_exception(app_test, monkeypatch):
    """A real development-seed retry is displayed without consuming a reserved seed."""
    from test_app_support import inject_child_failure
    inject_child_failure(monkeypatch,
        "original_validation = generate.validate_dataset_safety\nattempts = [0]\n"
        "def reject_first(*args, **kwargs):\n    attempts[0] += 1\n    if attempts[0] == 1:\n        raise generate.DatasetSafetyError('deliberate UI safety rejection')\n    return original_validation(*args, **kwargs)\n"
        "generate.validate_dataset_safety = reject_first\n")
    at = generate(app_test, 1)
    assert not at.exception and not at.error
    metadata = at.session_state["run"]["generation_metadata"]
    assert metadata["generation_attempts"] >= 2
    assert metadata["safety_rejections"][0] == {"attempt": 1, "reason": "deliberate UI safety rejection"}
    assert any(f"{metadata['generation_attempts']} sampling attempts" in item.value for item in at.info)


def test_exception_details_use_engine_highlight_metadata(app_test):
    """Choosing a PRICE exception shows its engine-reported field, not an app comparison."""
    at = generate(app_test)
    run = at.session_state["run"]
    index = next(index for index, row in enumerate(run["results"]) if row["break_type"] == "PRICE")
    at.selectbox(key="exception_index").set_value(index).run()
    assert not at.exception
    assert any("price_usd_bbl" in item.value for item in at.caption)


def test_missing_temporary_workspace_recovers_as_a_fresh_session(app_test):
    """Loss of runtime disk content cannot leave stale results or require persistent host files."""
    import shutil
    at = generate(app_test)
    old = Path(at.session_state["_workspace"].name)
    shutil.rmtree(old)
    at.run()
    assert not at.exception
    assert at.session_state["run"] is None
    assert at.radio(key="page").options == ["Reconciliation"]
    assert any("temporary" in item.value.lower() for item in at.info)


def test_generation_failure_is_a_plain_error_and_clears_old_results(app_test, monkeypatch):
    """Exhausted retries are rendered as a readable message, never st.exception or old results."""
    import app_support
    at = generate(app_test)

    def fail(*args, **kwargs):
        """Exercise the UI error boundary without making up a successful generator result."""
        raise app_support.AppInputError("The generator could not create a safe dataset. Try another seed.")

    monkeypatch.setattr(app_support, "run_generated", fail)
    at.button(key="generate").click().run()
    assert not at.exception
    assert any("safe dataset" in item.value for item in at.error)
    assert at.session_state["run"] is None


def test_two_app_sessions_have_separate_workspaces(app_test):
    """One session's generated files and state do not overwrite another session."""
    from streamlit.testing.v1 import AppTest
    first = generate(app_test)
    second = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    try:
        generate(second, 2)
        one = Path(first.session_state["_workspace"].name)
        two = Path(second.session_state["_workspace"].name)
        assert one != two and one.is_dir() and two.is_dir()
        assert first.session_state["run"]["seed"] == 1
        assert second.session_state["run"]["seed"] == 2
    finally:
        second.session_state["_workspace"].cleanup()


def uploaded_values(monkeypatch, blotter_bytes, confirmation_bytes, blotter_name="blotter.csv"):
    """Inject bytes at the upload-widget boundary: AppTest 1.50 has no native file-upload driver."""
    from types import SimpleNamespace
    import streamlit as st
    files = {
        "blotter_upload": SimpleNamespace(name=blotter_name, getvalue=lambda: blotter_bytes),
        "confirmations_upload": SimpleNamespace(name="confirmations.csv", getvalue=lambda: confirmation_bytes),
    }
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: files[kwargs["key"]])


def changed_csv(content, column, value):
    """Build a deliberate negative input from an actual signed-off clean file, without editing it."""
    import csv
    import io
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    fields = reader.fieldnames
    rows = list(reader)
    rows[0][column] = value
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


@pytest.mark.parametrize("kind", ["blotter", "confirmations"])
@pytest.mark.parametrize("column,value", [
    ("trade_date", "not-a-date"),
    ("price_usd_bbl", "seventy"),
    ("unit", "TONNES"),
    ("quantity", ""),
])
def test_upload_bad_values_render_row_column_errors(app_test, monkeypatch, kind, column, value):
    """Validate real CSV bytes and rendered errors; this does not claim native widget automation."""
    folder = ROOT / "data/generated/clean"
    blotter = (folder / "blotter.csv").read_bytes()
    confirmations = (folder / "confirmations.csv").read_bytes()
    if kind == "blotter":
        blotter = changed_csv(blotter, column, value)
    else:
        confirmations = changed_csv(confirmations, column, value)
    uploaded_values(monkeypatch, blotter, confirmations)
    at = app_test.run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception
    message = " ".join(item.value for item in at.error)
    assert "row 2" in message.lower() and column in message
    assert kind in message.lower()
    assert "traceback" not in message.lower()
    assert at.session_state["run"] is None
    assert at.radio(key="page").options == ["Reconciliation"]


def test_successful_upload_renders_clean_engine_results_without_scores(app_test, monkeypatch):
    """A real clean CSV pair goes through the entrypoint; only the widget boundary is injected."""
    folder = ROOT / "data/generated/clean"
    uploaded_values(monkeypatch, (folder / "blotter.csv").read_bytes(),
                    (folder / "confirmations.csv").read_bytes())
    at = app_test.run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception and not at.error
    assert at.session_state["run"]["origin"] == "uploaded"
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["Matched trades"] == "200"
    assert metrics["Total value of discrepancy"] == "$0.00"
    assert at.radio(key="page").options == ["Reconciliation"]
    assert any("No exceptions" in item.value for item in at.success)


@pytest.mark.parametrize("content,name,expected", [
    (b"", "blotter.csv", "empty"),
    (b"wrong,columns\n1,2\n", "blotter.csv", "column"),
    (b"not an Excel document", "blotter.xlsx", "csv"),
])
def test_malformed_upload_shows_clear_error(app_test, monkeypatch, content, name, expected):
    """Wrong types, missing columns and empty files never create result metrics or traceback elements."""
    valid = (ROOT / "data/generated/clean/confirmations.csv").read_bytes()
    uploaded_values(monkeypatch, content, valid, name)
    at = app_test.run()
    at.button(key="reconcile_uploads").click().run()
    assert not at.exception
    assert expected in " ".join(item.value for item in at.error).lower()
    assert not at.metric


def test_contract_month_detail_has_plain_english_label(app_test):
    """The specification requires the engine's CONTRACT_MONTH result to say wrong delivery month."""
    at = generate(app_test)
    run = at.session_state["run"]
    index = next(index for index, row in enumerate(run["results"]) if row["break_type"] == "CONTRACT_MONTH")
    at.selectbox(key="exception_index").set_value(index).run()
    assert any("wrong delivery month" in item.value.lower() for item in at.caption)
