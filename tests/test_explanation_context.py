"""Thin canonical context uses the frozen normaliser and actual private settings."""
import csv
from datetime import date
from decimal import Decimal
import io
import json
from pathlib import Path
import subprocess

import pytest

import app_support as app
from src import normalise, reconcile


def csv_bytes(rows):
    """Encode exact fictional source strings as a CSV upload."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


@pytest.fixture
def workspace():
    """Own and remove private test sessions inside the allowed project boundary."""
    with app.create_workspace(app.ROOT / ".cache" / "explanation-context") as folder:
        yield Path(folder)


def test_upload_context_preserves_exact_normaliser_records_and_private_settings(
        workspace, make_trade, make_confirmation, monkeypatch):
    """Use one private settings snapshot for real reconciliation and canonical context."""
    trade = make_trade(identifier=" T001 ", quantity=" 5.000 ", side=" buy ",
                       unit=" lots ", price_usd_bbl="80.000000000000000001",
                       desk_note=" untouched ")
    confirmation = make_confirmation(trade, identifier=" C001 ", trade_ref="", unit=" BBL ",
                                     quantity="5000.000", price_usd_bbl="81.000000000000000001")
    actual = reconcile.reconcile_files
    calls = []

    def observed(*args, **kwargs):
        """Observe, but never replace, the real reconciliation entrypoint."""
        calls.append((args, kwargs))
        return actual(*args, **kwargs)

    monkeypatch.setattr(reconcile, "reconcile_files", observed)
    run = app.run_uploads(workspace, "desk.csv", csv_bytes([trade]),
                          "broker.csv", csv_bytes([confirmation]))
    context = run["explanation_context"]
    assert set(context) == {"trades", "confirmations", "settings"}
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert len(args) == 4
    snapshot = Path(kwargs["settings"])
    assert snapshot == Path(run["folder"]) / "settings.json"
    assert snapshot.read_bytes() == (app.ROOT / "settings.json").read_bytes()
    assert context["settings"] == normalise.load_settings(snapshot)
    assert context["trades"] == {record["trade_id"]: record for record in
                                 normalise.normalise_records([trade], "blotter", context["settings"])}
    assert context["confirmations"] == {record["confirm_id"]: record for record in
                                        normalise.normalise_records([confirmation], "confirmations", context["settings"])}
    record = context["trades"]["T001"]
    assert record["_raw"] == trade and record["_raw"] is not trade
    assert record["_date"] == date(2026, 10, 1)
    assert record["_quantity"] == Decimal("5.000")
    assert record["_price"] == Decimal("80.000000000000000001")
    assert record["_volume_bbl"] == Decimal("5000.000")
    assert context["confirmations"]["C001"]["trade_ref"] == ""
    assert run["blotter"] == [trade] and run["confirmations"] == [confirmation]
    assert (snapshot.parent / "blotter.csv").read_bytes() == csv_bytes([trade])
    assert (snapshot.parent / "confirmations.csv").read_bytes() == csv_bytes([confirmation])
    snapshot.unlink()
    assert record["_price"] == Decimal("80.000000000000000001")
    assert run["results"][0]["value_of_discrepancy_usd"] == "5000.00"


def test_generated_context_uses_generation_snapshot_not_current_root(workspace, monkeypatch):
    """Real generation and reconciliation use the same isolated nondefault settings."""
    root_bytes = (app.ROOT / "settings.json").read_bytes()
    root_stat = (app.ROOT / "settings.json").stat().st_mtime_ns
    launch = subprocess.run
    actual = reconcile.reconcile_files
    generated_settings = []
    reconciled_settings = []

    def isolated_generation(command, *args, **kwargs):
        """Change only the private generation settings before running the real child."""
        snapshot = Path(command[2]) / "settings.json"
        configuration = normalise.load_settings(snapshot)
        configuration["barrels_per_lot"] = 2000
        snapshot.write_text(json.dumps(configuration), encoding="utf-8")
        generated_settings.append(snapshot.read_bytes())
        return launch(command, *args, **kwargs)

    def observed(*args, **kwargs):
        """Record actual reconciliation settings, including a missing explicit argument."""
        snapshot = Path(kwargs.get("settings", app.ROOT / "settings.json"))
        reconciled_settings.append((snapshot, snapshot.read_bytes()))
        return actual(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", isolated_generation)
    monkeypatch.setattr(reconcile, "reconcile_files", observed)
    run = app.run_generated(workspace, 1)
    assert len(reconciled_settings) == len(generated_settings) == 1
    snapshot, used_bytes = reconciled_settings[0]
    assert used_bytes == generated_settings[0]
    assert snapshot == Path(run["folder"]) / "settings.json"
    context = run["explanation_context"]
    assert context["settings"]["barrels_per_lot"] == 2000
    assert context["trades"] == {record["trade_id"]: record for record in
                                 normalise.normalise_records(run["blotter"], "blotter", context["settings"])}
    assert context["confirmations"] == {record["confirm_id"]: record for record in
                                        normalise.normalise_records(run["confirmations"], "confirmations", context["settings"])}
    assert (app.ROOT / "settings.json").read_bytes() == root_bytes
    assert (app.ROOT / "settings.json").stat().st_mtime_ns == root_stat


@pytest.mark.parametrize("field", ["price_usd_bbl", "record"])
def test_detail_notes_use_plain_tool_wording(make_trade, make_confirmation, field):
    """User-facing notes describe this tool, not implementation machinery."""
    trade = make_trade()
    confirmation = make_confirmation(trade)
    run = {"blotter": [trade], "confirmations": [confirmation]}
    row = {"trade_id": trade["trade_id"], "confirm_id": confirmation["confirm_id"],
           "field_affected": field}
    note = app.exception_details(run, row)["note"]
    assert note == {
        "price_usd_bbl": "The differing fields are marked below.",
        "record": "The available records are shown below.",
    }[field]
    assert "engine" not in note.lower()
    assert "generator" not in note.lower()


@pytest.mark.parametrize("operation", ["missing_record", "nonfinite_amount"])
def test_input_errors_use_plain_tool_wording(operation):
    """Known display failures keep actionable language without technical jargon."""
    with pytest.raises(app.AppInputError) as caught:
        if operation == "missing_record":
            app.exception_details({"blotter": [], "confirmations": []}, {"trade_id": "absent"})
        else:
            app.sort_exceptions([{"value_of_discrepancy_usd": "NaN"}])
    assert "engine" not in str(caught.value).lower()


def test_upload_snapshots_current_settings_and_resists_later_drift(
        workspace, make_trade, make_confirmation, monkeypatch):
    """A changing private stand-in root cannot alter an already captured run."""
    configuration = normalise.load_settings(app.ROOT / "settings.json")
    configuration["barrels_per_lot"] = 2000
    private_root = workspace / "private-root"
    private_root.mkdir()
    current = private_root / "settings.json"
    current.write_text(json.dumps(configuration), encoding="utf-8")
    monkeypatch.setattr(app, "ROOT", private_root)
    actual = reconcile.reconcile_files
    snapshots = []

    def drift_after_capture(*args, **kwargs):
        """Change current settings after snapshotting but before real reconciliation."""
        snapshots.append(Path(kwargs["settings"]))
        changed = dict(configuration, barrels_per_lot=3000)
        current.write_text(json.dumps(changed), encoding="utf-8")
        return actual(*args, **kwargs)

    monkeypatch.setattr(reconcile, "reconcile_files", drift_after_capture)
    trade = make_trade()
    confirmation = make_confirmation(trade, price_usd_bbl="81")
    args = (private_root / "runs", "desk.csv", csv_bytes([trade]),
            "broker.csv", csv_bytes([confirmation]))
    first = app.run_uploads(*args)
    first_bytes = snapshots[0].read_bytes()
    second = app.run_uploads(*args)
    assert first["explanation_context"]["settings"]["barrels_per_lot"] == 2000
    assert first["results"][0]["value_of_discrepancy_usd"] == "10000.00"
    assert second["explanation_context"]["settings"]["barrels_per_lot"] == 3000
    assert second["results"][0]["value_of_discrepancy_usd"] == "15000.00"
    assert snapshots[0] != snapshots[1]
    assert snapshots[0].read_bytes() == first_bytes
    assert first["explanation_context"]["trades"]["T001"]["_volume_bbl"] == Decimal("10000")
