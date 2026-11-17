"""Exercise the nonvisual adapter with real inputs and the unchanged engine."""
import csv
import io
import json
from decimal import Decimal
from pathlib import Path
import shutil
import builtins
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor

from src import reconcile, generate, scorecard

import pytest

import app_support as app


def csv_bytes(rows, columns=None):
    """Encode fictional input records without changing their strings."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns or list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def test_validate_preserves_original_strings(make_trade, make_confirmation):
    """Validation accepts BOM and blank references without normalizing source text."""
    trade = make_trade(quantity=" 5.000 ", side=" buy ")
    confirm = make_confirmation(trade, trade_ref="")
    assert app.validate_upload("desk.CSV", b"\xef\xbb\xbf" + csv_bytes([trade]), "blotter") == [trade]
    assert app.validate_upload("broker.csv", csv_bytes([confirm]), "confirmations") == [confirm]


@pytest.mark.parametrize("column,value", [
    ("trade_date", "2026-02-30"), ("trade_date", "2026-1-01"),
    ("contract_month", "2026-13"), ("contract_month", "2026-1"),
    ("quantity", ""), ("quantity", "no"), ("quantity", "NaN"),
    ("quantity", "Infinity"), ("quantity", "0"), ("quantity", "-1"),
    ("price_usd_bbl", ""), ("price_usd_bbl", "no"), ("price_usd_bbl", "NaN"),
    ("price_usd_bbl", "-Infinity"), ("price_usd_bbl", "0"), ("price_usd_bbl", "-1"),
    ("side", "HOLD"), ("unit", "LITRES"), ("trade_id", ""),
    ("trade_id", "T1;T2"), ("counterparty", "..."),
])
def test_invalid_values_have_role_row_column(make_trade, column, value):
    """Invalid values produce a useful location rather than a traceback."""
    trade = make_trade(**{column: value})
    with pytest.raises(app.AppInputError) as caught:
        app.validate_upload("desk.csv", csv_bytes([trade]), "blotter")
    message = str(caught.value)
    assert "blotter" in message and "row 2" in message and column in message
    assert "Traceback" not in message


def test_duplicate_ids_locate_second_row(make_trade):
    """Whitespace-equivalent IDs cannot silently collapse distinct input rows."""
    with pytest.raises(app.AppInputError, match="row 3.*trade_id"):
        app.validate_upload("desk.csv", csv_bytes([make_trade(), make_trade(identifier=" T001 ")]), "blotter")


@pytest.mark.parametrize("name,content", [
    ("desk.xlsx", b"x"), ("desk.csv", b""), ("desk.csv", b" \n\t"),
    ("desk.csv", b"\xff"), ("desk.csv", b"a\x00b"),
    ("desk.csv", b'"unclosed'),
])
def test_bad_upload_formats(name, content):
    """Only nonempty, well-formed UTF-8 CSV is accepted."""
    with pytest.raises(app.AppInputError):
        app.validate_upload(name, content, "blotter")


def test_bad_csv_structure(make_trade):
    """Reject header-only, duplicate/missing headers, and uneven data rows."""
    good = csv_bytes([make_trade()])
    header, row = good.splitlines()
    fixtures = [header + b"\n", good.replace(b"trade_id", b"side", 1),
                good.replace(b"trade_id", b"other_id", 1),
                header + b"\n" + row + b",extra\n", header + b"\nT001\n"]
    for content in fixtures:
        with pytest.raises(app.AppInputError):
            app.validate_upload("desk.csv", content, "blotter")


def test_confirmation_id_validation(make_trade, make_confirmation):
    """Broker identifiers use the same checks while trade_ref may be blank."""
    for value in ["", "C1;C2"]:
        confirmation = make_confirmation(make_trade(), identifier=value)
        with pytest.raises(app.AppInputError, match="confirmations.*row 2.*confirm_id"):
            app.validate_upload("broker.csv", csv_bytes([confirmation]), "confirmations")
    confirmation = make_confirmation(make_trade())
    with pytest.raises(app.AppInputError, match="row 3.*confirm_id"):
        app.validate_upload("broker.csv", csv_bytes([confirmation, confirmation]), "confirmations")


@pytest.fixture
def workspace():
    """Keep each test session inside the engine's approved project boundary."""
    with app.create_workspace(app.ROOT / ".cache" / "app-support-sessions") as folder:
        yield Path(folder)


def test_workspaces_are_isolated_and_recreate_parent():
    """TemporaryDirectory resources own distinct sessions even after parent loss."""
    with app.create_workspace() as first, app.create_workspace() as second:
        assert Path(first).parent == app.ROOT / ".app_sessions"
        assert first != second
        (Path(first) / "private.txt").write_text("one")
        assert not (Path(second) / "private.txt").exists()
    parent = app.ROOT / ".cache" / "app-support-parent"
    with app.create_workspace(parent) as folder:
        assert Path(folder).is_dir()
    shutil.rmtree(parent)
    with app.create_workspace(parent) as folder:
        assert Path(folder).is_dir()
    assert isinstance(app.create_workspace(), tempfile.TemporaryDirectory)


def test_upload_calls_real_engine_without_answer_key(workspace, make_trade, make_confirmation, monkeypatch):
    """The upload path uses fixed filenames and cannot read generated labels."""
    trade = make_trade()
    confirmation = make_confirmation(trade, price_usd_bbl="81.00")
    original = reconcile.reconcile_files
    calls = []

    def observed(*args, **kwargs):
        """Record the unchanged engine entrypoint while retaining real execution."""
        calls.append(args)
        return original(*args, **kwargs)

    original_open = builtins.open
    original_io_open = io.open

    def guard(original_function):
        """Refuse any accidental label access, including pandas and Path opens."""
        def opened(file, *args, **kwargs):
            if not isinstance(file, int):
                assert Path(file).name != "answer_key.csv"
            return original_function(file, *args, **kwargs)
        return opened

    monkeypatch.setattr(reconcile, "reconcile_files", observed)
    monkeypatch.setattr(builtins, "open", guard(original_open))
    monkeypatch.setattr(io, "open", guard(original_io_open))
    run = app.run_uploads(workspace, "../../desk.csv", csv_bytes([trade]), "/broker.csv", csv_bytes([confirmation]))
    assert len(calls) == 1
    assert run["origin"] == "uploaded" and run["seed"] is None
    assert run["generation_metadata"] is None
    assert run["blotter"] == [trade] and run["confirmations"] == [confirmation]
    assert run["results"][0]["value_of_discrepancy_usd"] == "5000.00"
    assert run["matches"][0]["trade_id"] == trade["trade_id"]
    assert run["engine_summary"]["matched_pairs"] == 1
    folder = Path(run["folder"])
    assert folder.parent == workspace
    assert {file.name for file in folder.iterdir()} == {
        "blotter.csv", "confirmations.csv", "results.csv", "matches.csv", "settings.json"}
    assert (folder / "blotter.csv").read_bytes() == csv_bytes([trade])
    again = app.run_uploads(workspace, "x.csv", csv_bytes([trade]), "x.csv", csv_bytes([confirmation]))
    assert again["folder"] != run["folder"]
    assert (folder / "results.csv").is_file()


def test_validate_both_before_creating_run(workspace, make_trade):
    """An invalid second upload leaves no partially created run folder."""
    before = set(workspace.iterdir())
    with pytest.raises(app.AppInputError, match="confirmations"):
        app.run_uploads(workspace, "a.csv", csv_bytes([make_trade()]), "b.csv", b"invalid")
    assert set(workspace.iterdir()) == before


def test_upload_engine_error_is_plain(workspace, make_trade, make_confirmation):
    """Unsupported referenced differences remain the existing engine's decision."""
    trade = make_trade()
    confirmation = make_confirmation(trade, broker="Different Broker")
    with pytest.raises(app.AppInputError, match="broker") as caught:
        app.run_uploads(workspace, "a.csv", csv_bytes([trade]), "b.csv", csv_bytes([confirmation]))
    assert "Traceback" not in str(caught.value)


def test_workspace_scope_and_recreation(workspace, make_trade, make_confirmation):
    """Lost sessions recover locally while outside-project paths are rejected."""
    trade = make_trade()
    args = ("a.csv", csv_bytes([trade]), "b.csv", csv_bytes([make_confirmation(trade)]))
    with pytest.raises(app.AppInputError, match="project"):
        app.create_workspace(app.ROOT.parent / "outside")
    with pytest.raises(app.AppInputError, match="project"):
        app.run_uploads(app.ROOT.parent / "outside", *args)
    shutil.rmtree(workspace)
    run = app.run_uploads(workspace, *args)
    assert run["results"] == []
    assert Path(run["folder"]).is_dir()


def test_generated_real_seed_retry_and_scorecard(workspace, monkeypatch):
    """A development seed preserves a real injected safety retry and measured scores without using holdout data."""
    inject_child_failure(monkeypatch,
        "original_validation = generate.validate_dataset_safety\nattempts = [0]\n"
        "def reject_first(*args, **kwargs):\n    attempts[0] += 1\n    if attempts[0] == 1:\n        raise generate.DatasetSafetyError('deliberate app test safety rejection')\n    return original_validation(*args, **kwargs)\n"
        "generate.validate_dataset_safety = reject_first\n")
    original_generate = subprocess.run
    original_engine = reconcile.reconcile_files
    calls = {"generate": [], "engine": [], "key": []}

    def observed_generate(command, *args, **kwargs):
        """Observe the real isolated launcher without replacing generated data."""
        calls["generate"].append(command)
        return original_generate(command, *args, **kwargs)

    def observed_engine(*args, **kwargs):
        """Observe real reconciliation of the generated inputs."""
        calls["engine"].append(args)
        return original_engine(*args, **kwargs)

    original_read = scorecard._read_records
    original_open = io.open
    original_builtin_open = builtins.open
    reading_key = [False]

    def guarded_open(file, *args, **kwargs):
        """Only the scorer's record reader is permitted to open generated labels."""
        if not isinstance(file, int) and Path(file).name == "answer_key.csv":
            assert reading_key[0] or "w" in (args[0] if args else kwargs.get("mode", "r"))
        return original_open(file, *args, **kwargs)

    def guarded_builtin_open(file, *args, **kwargs):
        """Enforce the same label boundary for pandas and regular Python opens."""
        if not isinstance(file, int) and Path(file).name == "answer_key.csv":
            assert reading_key[0] or "w" in (args[0] if args else kwargs.get("mode", "r"))
        return original_builtin_open(file, *args, **kwargs)

    def observed_read(path, required, label):
        """Grant label-reading access only during the existing scorer reader call."""
        assert Path(path).name == "answer_key.csv"
        calls["key"].append(path)
        reading_key[0] = True
        try:
            return original_read(path, required, label)
        finally:
            reading_key[0] = False

    monkeypatch.setattr(subprocess, "run", observed_generate)
    monkeypatch.setattr(reconcile, "reconcile_files", observed_engine)
    monkeypatch.setattr(scorecard, "_read_records", observed_read)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    run = app.run_generated(workspace, 1)
    assert run["origin"] == "generated" and run["seed"] == 1
    assert len(run["blotter"]) == 200
    assert len(calls["generate"]) == 1 and len(calls["engine"]) == 1
    command = calls["generate"][0]
    assert Path(command[1]).name == "generate_for_app.py" and command[3] == "1"
    output_root = Path(command[2]) / "generated"
    assert output_root.name == "generated" and output_root.parent.parent == workspace
    metadata = run["generation_metadata"]
    assert metadata == json.loads((Path(run["folder"]) / "generation_metadata.json").read_text())
    assert metadata["generation_attempts"] >= 2
    assert len(metadata["safety_rejections"]) == metadata["generation_attempts"] - 1
    assert metadata["safety_rejections"][0] == {"attempt": 1, "reason": "deliberate app test safety rejection"}
    measured = app.load_scorecard(run)
    assert set(measured) == {"scores", "names"}
    assert sum(int(row["found"]) for row in measured["scores"]) == 32
    assert {row["counterparty_resolution"]: int(row["count"]) for row in measured["names"]} == {
        "GENERAL_RULES": 2, "ALIAS_TABLE": 2, "UNRESOLVED": 0}
    assert len(calls["key"]) == 1
    shutil.rmtree(Path(run["folder"]).parents[1])
    assert app.load_scorecard(run) == measured
    assert len(calls["key"]) == 1


def test_scorecard_upload_guard_precedes_cache(workspace, make_trade, make_confirmation, monkeypatch):
    """No uploaded run may access generated scorecard logic, even with cached data."""
    trade = make_trade()
    run = app.run_uploads(workspace, "a.csv", csv_bytes([trade]), "b.csv", csv_bytes([make_confirmation(trade)]))
    run["scorecard"] = {"scores": ["forged"], "names": []}

    def forbidden(*args, **kwargs):
        """Fail if uploaded data reaches scoring or label access."""
        raise AssertionError("Uploaded runs must not reach the scorer")

    monkeypatch.setattr(scorecard, "_read_records", forbidden)
    monkeypatch.setattr(scorecard, "score_records", forbidden)
    with pytest.raises(app.AppInputError, match="generated"):
        app.load_scorecard(run)


def test_missing_scorecard_files_ask_to_regenerate(workspace):
    """An uncached generated run whose host storage expired is actionable."""
    run = app.run_generated(workspace, 1)
    shutil.rmtree(Path(run["folder"]))
    with pytest.raises(app.AppInputError, match="[Rr]egenerate"):
        app.load_scorecard(run)


def inject_child_failure(monkeypatch, code):
    """Inject failure into a real child process rather than invent a subprocess response."""
    original = subprocess.run
    harness = ("import runpy, sys\nfrom src import generate\n" + code +
               "\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")

    def launch(command, *args, **kwargs):
        """Keep the production launcher and private paths, with only the failure hook added."""
        return original([command[0], "-c", harness] + command[1:], *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", launch)


def test_generator_exhausted_error_is_plain(workspace, monkeypatch):
    """Exercise all 100 real generator attempts under an injected safety failure."""
    inject_child_failure(monkeypatch,
        "def reject(*args, **kwargs):\n    raise generate.DatasetSafetyError('injected unsafe sample')\n"
        "generate.validate_dataset_safety = reject\n")
    with pytest.raises(app.AppInputError, match="100.*attempts") as caught:
        app.run_generated(workspace, 1)
    assert "Traceback" not in str(caught.value)
    assert "Try another seed" in str(caught.value)


def test_generation_unexpected_error_is_plain(workspace, monkeypatch):
    """Real child I/O failures and an enforced process timeout both give plain messages."""
    original_process = subprocess.run
    inject_child_failure(monkeypatch,
        "def broken(*args, **kwargs):\n    raise OSError('source unavailable')\n"
        "generate.generate_dataset = broken\n")
    with pytest.raises(app.AppInputError, match="source unavailable"):
        app.run_generated(workspace, 1)

    def timed_out(command, *args, **kwargs):
        """Start the real child but enforce an immediate deadline instead of waiting 180 seconds."""
        kwargs["timeout"] = 0
        return original_process(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", timed_out)
    with pytest.raises(app.AppInputError, match="took too long") as caught:
        app.run_generated(workspace, 1)
    assert "Traceback" not in str(caught.value)


def upload_records(workspace, trades, confirmations):
    """Run fictional records through the actual adapter and engine."""
    return app.run_uploads(workspace, "desk.csv", csv_bytes(trades), "broker.csv", csv_bytes(confirmations))


def test_summary_exact_values_and_distinct_trades(workspace, make_trade, make_confirmation):
    """Duplicate pairs count one matched trade; totals sum emitted values only."""
    trade = make_trade()
    confirms = [make_confirmation(trade, identifier="C1"), make_confirmation(trade, identifier="C2")]
    run = upload_records(workspace, [trade], confirms)
    summary = app.summarise(run)
    assert summary == {"trades_processed": 1, "matched_trades": 1, "matched_pairs": 2,
                       "review_groups": 0, "total_value": Decimal("400000.00"),
                       "by_type": [{"break_type": "DUPLICATE", "count": 1, "value": Decimal("400000.00")}]}
    assert app.dollars(summary["total_value"]) == "$400,000.00"
    assert app.dollars(Decimal("1234.50")) == "$1,234.50"
    assert app.dollars(None) == ""
    assert app.dollars(Decimal("0")) == "$0.00"


def test_summary_decimal_sum_and_clean_zero(workspace, make_trade, make_confirmation):
    """Cent-valued engine outputs sum exactly; a clean run has real zero."""
    first = make_trade(quantity="1", unit="BBL", price_usd_bbl="0.01")
    second = make_trade(identifier="T002", quantity="1", unit="BBL", price_usd_bbl="0.02")
    confirms = [make_confirmation(first, identifier="C1", price_usd_bbl="0.12"),
                make_confirmation(second, identifier="C2", price_usd_bbl="0.24")]
    summary = app.summarise(upload_records(workspace, [first, second], confirms))
    assert summary["total_value"] == Decimal("0.33")
    assert summary["by_type"] == [{"break_type": "PRICE", "count": 2, "value": Decimal("0.33")}]
    clean = upload_records(workspace, [first], [make_confirmation(first)])
    assert app.summarise(clean)["total_value"] == Decimal("0")
    assert app.summarise(clean)["by_type"] == []


def test_review_summary_and_details_survive_files_loss(workspace, make_trade, make_confirmation):
    """Ambiguous groups retain every raw ID without inventing money or pairing."""
    trades = [make_trade(identifier="T1"), make_trade(identifier="T2")]
    confirms = [make_confirmation(trades[0], identifier="C1", trade_ref=""),
                make_confirmation(trades[0], identifier="C2", trade_ref="")]
    run = upload_records(workspace, trades, confirms)
    assert len(run["results"]) == 1
    shutil.rmtree(workspace)
    summary = app.summarise(run)
    assert summary["review_groups"] == 1 and summary["total_value"] is None
    assert summary["by_type"] == [{"break_type": "AMBIGUOUS", "count": 1, "value": None}]
    detail = app.exception_details(run, run["results"][0])
    assert detail["blotter"] == trades and detail["confirmations"] == confirms
    assert detail["highlight_fields"] == []
    assert "not chosen a pair" in detail["note"].lower() and "manual pairing" in detail["note"].lower()


def test_sort_modes_exact_decimal_and_source_indexes():
    """Sorting uses exact numeric keys, blank-last order, and stable raw indexes."""
    values = [("STANDARD", "9.00", "PRICE", "T3"), ("HIGH", "10.00", "SIDE", "T2"),
              ("REVIEW", "", "AMBIGUOUS", "T1"),
              ("STANDARD", "10000000000000000000.02", "PRICE", "T5"),
              ("STANDARD", "10000000000000000000.01", "PRICE", "T4"), ("HIGH", "", "SIDE", "T0")]
    rows = [dict(priority=p, value_of_discrepancy_usd=v, break_type=b, trade_id=t, confirm_id="C" + t)
            for p, v, b, t in values]
    assert [r["_source_index"] for r in app.sort_exceptions(rows)] == [1, 5, 3, 4, 0, 2]
    assert [r["_source_index"] for r in app.sort_exceptions(rows, "Value of discrepancy (largest first)")] == [3, 4, 1, 0, 5, 2]
    assert [r["_source_index"] for r in app.sort_exceptions(rows, "Break type")] == [2, 3, 4, 0, 1, 5]
    assert [r["_source_index"] for r in app.sort_exceptions(rows, "Trade ID")] == [5, 2, 1, 0, 4, 3]
    copied = app.sort_exceptions(rows)
    copied[0]["trade_id"] = "changed"
    assert rows[1]["trade_id"] == "T2" and all("_source_index" not in r for r in rows)


@pytest.mark.parametrize("changes,fields", [
    ({"price_usd_bbl": "81"}, ["price_usd_bbl"]),
    ({"quantity": "6"}, ["quantity", "unit"]),
    ({"unit": "BBL"}, ["quantity", "unit"]),
    ({"side": "SELL"}, ["side"]),
    ({"contract_month": "2027-01"}, ["contract_month"]),
])
def test_details_follow_only_engine_field(workspace, make_trade, make_confirmation, changes, fields):
    """Highlight only the declared field without a second comparison algorithm."""
    trade = make_trade()
    confirmation = make_confirmation(trade, **changes)
    run = upload_records(workspace, [trade], [confirmation])
    row = run["results"][0]
    detail = app.exception_details(run, row)
    assert set(detail) == {"blotter", "confirmations", "highlight_fields", "note"}
    assert detail["blotter"] == [trade] and detail["confirmations"] == [confirmation]
    assert detail["highlight_fields"] == fields
    assert app.exception_details(run, dict(row, field_affected="pairing"))["highlight_fields"] == []


def test_duplicate_details_include_all_confirmations(workspace, make_trade, make_confirmation):
    """Do not label an original or extra confirmation within a duplicate group."""
    trade = make_trade()
    confirms = [make_confirmation(trade, identifier="C1"), make_confirmation(trade, identifier="C2")]
    run = upload_records(workspace, [trade], confirms)
    detail = app.exception_details(run, run["results"][0])
    assert detail["confirmations"] == confirms
    assert detail["highlight_fields"] == ["trade_ref"]
    assert "all confirmations" in detail["note"].lower() and "not chosen an original" in detail["note"].lower()


def test_record_details_and_invalidation(workspace, make_trade, make_confirmation):
    """Whole-record exceptions highlight raw fields; clearing preserves workspace."""
    trade = make_trade()
    confirmation = make_confirmation(trade, trade_ref="unknown", counterparty="Other Entity")
    run = upload_records(workspace, [trade], [confirmation])
    for row in run["results"]:
        detail = app.exception_details(run, row)
        expected = [trade] if row["trade_id"] else []
        assert detail["blotter"] == expected
        assert detail["confirmations"] == ([] if expected else [confirmation])
        present = set().union(*(set(record) for record in detail["blotter"] + detail["confirmations"]))
        assert set(detail["highlight_fields"]) == present
    resource = object()
    state = {"run": run, "error": "old", "page": 4, "_workspace": resource, "other": "keep"}
    app.invalidate_run(state)
    assert state == {"_workspace": resource, "other": "keep"}
    app.invalidate_run(state)


def test_mixed_review_summary_retains_blank_group(workspace, make_trade, make_confirmation):
    """Review amounts stay absent when valued exception groups are also present."""
    first = make_trade(identifier="T1")
    second = make_trade(identifier="T2")
    priced = make_trade(identifier="T3", counterparty="Separate Entity")
    confirms = [make_confirmation(first, identifier="C1", trade_ref=""),
                make_confirmation(first, identifier="C2", trade_ref=""),
                make_confirmation(priced, identifier="C3", price_usd_bbl="81")]
    run = upload_records(workspace, [first, second, priced], confirms)
    summary = app.summarise(run)
    assert summary["total_value"] == Decimal("5000.00")
    assert summary["by_type"] == [
        {"break_type": "AMBIGUOUS", "count": 1, "value": None},
        {"break_type": "PRICE", "count": 1, "value": Decimal("5000.00")}]
    review = next(row for row in run["results"] if row["break_type"] == "AMBIGUOUS")
    candidates_only = dict(review, trade_id="", confirm_id="")
    detail = app.exception_details(run, candidates_only)
    assert [row["trade_id"] for row in detail["blotter"]] == ["T1", "T2"]
    assert [row["confirm_id"] for row in detail["confirmations"]] == ["C1", "C2"]
    detail["blotter"][0]["trade_id"] = "changed"
    assert run["blotter"][0]["trade_id"] == "T1"


@pytest.mark.parametrize("seed", ["12", 1.5, True, None])
def test_invalid_seed_before_run_creation(workspace, seed):
    """Seeds are integers, not silently coerced values or booleans."""
    with pytest.raises(app.AppInputError, match="integer"):
        app.run_generated(workspace, seed)
    assert list(workspace.iterdir()) == []


def test_unexpected_engine_error_and_session_isolation(workspace, make_trade, make_confirmation, monkeypatch):
    """A failed session cannot modify another session's successfully written inputs."""
    trade = make_trade()
    confirmation = make_confirmation(trade)
    completed = upload_records(workspace, [trade], [confirmation])
    completed_path = Path(completed["folder"]) / "blotter.csv"
    before = completed_path.read_bytes()

    def broken(*args, **kwargs):
        """Inject an unexpected engine failure instead of mocking successful results."""
        raise RuntimeError("injected engine failure")

    monkeypatch.setattr(reconcile, "reconcile_files", broken)
    with app.create_workspace() as other:
        with pytest.raises(app.AppInputError, match="injected engine failure"):
            upload_records(Path(other), [make_trade(identifier="private")], [confirmation])
    assert completed_path.read_bytes() == before


def test_scorer_error_is_plain_and_not_cached(workspace, monkeypatch):
    """A scoring failure is not mistaken for a cached successful measurement."""
    run = app.run_generated(workspace, 1)

    def broken(*args, **kwargs):
        """Inject an unexpected scoring failure after real generation."""
        raise RuntimeError("injected scoring failure")

    monkeypatch.setattr(scorecard, "score_records", broken)
    with pytest.raises(app.AppInputError, match="injected scoring failure"):
        app.load_scorecard(run)
    assert "scorecard" not in run


def test_bad_display_inputs_are_plain_errors():
    """Public display boundaries convert missing or invalid data to app errors."""
    calls = [lambda: app.summarise({}), lambda: app.sort_exceptions([], "unknown"),
             lambda: app.sort_exceptions([{"value_of_discrepancy_usd": "NaN"}]),
             lambda: app.exception_details({}, {}), lambda: app.dollars("not numeric"),
             lambda: app.invalidate_run(None), lambda: app.load_scorecard({})]
    for call in calls:
        with pytest.raises(app.AppInputError) as caught:
            call()
        assert "Traceback" not in str(caught.value)


def test_concurrent_generation_never_writes_shared_price_inputs():
    """Concurrent development sessions keep prices, settings and expiry calendars private and reproducible."""
    inputs = [app.ROOT / "data/brent_spot.csv", app.ROOT / "settings.json",
              app.ROOT / "data/ice_brent_expiry_calendar.json"]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in inputs}
    with app.create_workspace() as first, app.create_workspace() as second:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(app.run_generated, Path(first), 1),
                       executor.submit(app.run_generated, Path(second), 2)]
            runs = [future.result(timeout=120) for future in futures]
        assert runs[0]["folder"] != runs[1]["folder"]
        for run in runs:
            private_root = Path(run["folder"]).parents[1]
            assert (private_root / "data/brent_spot.csv").read_bytes() == before[inputs[0]][0]
            assert (private_root / "settings.json").read_bytes() == before[inputs[1]][0]
            assert (private_root / "data/ice_brent_expiry_calendar.json").read_bytes() == before[inputs[2]][0]
            assert {path.name for path in (private_root / "data").iterdir()} == {
                "brent_spot.csv", "ice_brent_expiry_calendar.json"}
            repeated = app.run_generated(Path(run["folder"]).parents[2], run["seed"])
            for name in ["blotter.csv", "confirmations.csv", "answer_key.csv", "generation_metadata.json"]:
                assert (Path(run["folder"]) / name).read_bytes() == (Path(repeated["folder"]) / name).read_bytes()
        for path in inputs:
            assert (path.read_bytes(), path.stat().st_mtime_ns) == before[path], "Shared input was rewritten: " + path.name
