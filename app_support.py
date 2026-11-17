"""Nonvisual app boundaries that delegate reconciliation to the frozen engine."""
import csv
from datetime import date
from decimal import Decimal
import io
import json
from pathlib import Path
import re
import tempfile
import shutil
import subprocess
import sys

from src import reconcile
from src.normalise import (COMMON_COLUMNS, general_name, load_settings,
                           normalise_records, positive_decimal)

ROOT = Path(__file__).resolve().parent


class AppInputError(ValueError):
    """Describe an actionable input or runtime failure without exposing a traceback."""


def validate_upload(filename, content, kind):
    """Validate a CSV upload while preserving every original input string."""
    role = str(kind)
    try:
        if kind not in {"blotter", "confirmations"}:
            raise ValueError("Choose blotter or confirmations.")
        if Path(filename).suffix.lower() != ".csv":
            raise ValueError("A CSV file is required.")
        text = content.decode("utf-8-sig", errors="strict")
        if not text.strip() or any(ord(char) < 32 and char not in "\r\n\t" for char in text):
            raise ValueError("Empty or binary CSV content is not accepted.")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        columns = next(reader)
        if len(set(columns)) != len(columns):
            raise ValueError("Duplicate columns are not accepted.")
        id_column = "trade_id" if kind == "blotter" else "confirm_id"
        required = COMMON_COLUMNS + [id_column] + (["trade_ref"] if kind == "confirmations" else [])
        missing = [column for column in required if column not in columns]
        if missing:
            raise ValueError("Missing required columns: {}.".format(", ".join(missing)))
        rows = []
        seen = set()
        for number, values in enumerate(reader, start=2):
            if len(values) != len(columns):
                raise ValueError("CSV row {}: malformed row; expected {} columns.".format(number, len(columns)))
            row = dict(zip(columns, values))
            for column in required:
                value = row[column].strip()
                try:
                    if column == id_column:
                        if not value or ";" in value or value in seen:
                            raise ValueError("Identifier must be nonblank, unique, and contain no semicolons.")
                        seen.add(value)
                    elif column == "trade_date":
                        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                            raise ValueError("Use an ISO date (YYYY-MM-DD).")
                        date.fromisoformat(value)
                    elif column == "contract_month":
                        if not re.fullmatch(r"\d{4}-\d{2}", value):
                            raise ValueError("Use YYYY-MM.")
                        date.fromisoformat(value + "-01")
                    elif column in {"quantity", "price_usd_bbl"}:
                        positive_decimal(value, column)
                    elif column == "side" and value.upper() not in {"BUY", "SELL"}:
                        raise ValueError("Use BUY or SELL.")
                    elif column == "unit" and value.upper() not in {"LOTS", "BBL"}:
                        raise ValueError("Use LOTS or BBL.")
                    elif column == "counterparty" and not general_name(value):
                        raise ValueError("Counterparty must be nonblank.")
                except Exception as error:
                    raise ValueError("CSV row {}, column {}: {}".format(number, column, error)) from None
            rows.append(row)
        if not rows:
            raise ValueError("CSV must include at least one data row.")
        return rows
    except Exception as error:
        raise AppInputError("{} file: {}".format(role, error)) from None


def _project_folder(path):
    """Resolve a runtime folder without permitting writes outside this project."""
    folder = Path(path).resolve()
    try:
        folder.relative_to(ROOT)
    except ValueError:
        raise AppInputError("Runtime workspace must be inside this project.") from None
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def create_workspace(base=None):
    """Create an independently owned temporary session inside the project."""
    try:
        parent = _project_folder(ROOT / ".app_sessions" if base is None else base)
        return tempfile.TemporaryDirectory(dir=parent, prefix="session-")
    except Exception as error:
        raise AppInputError("Cannot create session workspace: {}".format(error)) from None


def _read_csv(path):
    """Read actual engine output or raw input as strings, never generated labels."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _reconcile_run(folder, blotter, confirmations, origin, seed, metadata, settings_path=None):
    """Retain actual results and normaliser context using one private configuration."""
    snapshot = folder / "settings.json"
    source = ROOT / "settings.json" if settings_path is None else Path(settings_path)
    if source.resolve() != snapshot.resolve():
        shutil.copyfile(source, snapshot)
    configuration = load_settings(snapshot)
    summary = reconcile.reconcile_files(folder / "blotter.csv", folder / "confirmations.csv",
                                        folder / "results.csv", folder / "matches.csv",
                                        settings=snapshot)
    context = {"trades": {record["trade_id"]: record for record in
                          normalise_records(blotter, "blotter", configuration)},
               "confirmations": {record["confirm_id"]: record for record in
                                 normalise_records(confirmations, "confirmations", configuration)},
               "settings": configuration}
    return {"origin": origin, "seed": seed, "folder": str(folder),
            "blotter": blotter, "confirmations": confirmations,
            "results": _read_csv(folder / "results.csv"),
            "matches": _read_csv(folder / "matches.csv"),
            "engine_summary": summary, "generation_metadata": metadata,
            "explanation_context": context}


def run_uploads(workspace, blotter_name, blotter_bytes, confirmations_name, confirmations_bytes):
    """Validate both uploads before storing fixed filenames in a fresh run folder."""
    try:
        blotter = validate_upload(blotter_name, blotter_bytes, "blotter")
        confirmations = validate_upload(confirmations_name, confirmations_bytes, "confirmations")
        parent = _project_folder(workspace)
        folder = Path(tempfile.mkdtemp(prefix="upload-", dir=parent))
        (folder / "blotter.csv").write_bytes(blotter_bytes)
        (folder / "confirmations.csv").write_bytes(confirmations_bytes)
        return _reconcile_run(folder, blotter, confirmations, "uploaded", None, None)
    except Exception as error:
        raise AppInputError("Upload reconciliation stopped: {}".format(error)) from None


def run_generated(workspace, seed):
    """Generate in an isolated run and reconcile without consulting its labels."""
    try:
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("Seed must be an integer.")
        parent = _project_folder(workspace)
        run_folder = Path(tempfile.mkdtemp(prefix="generated-", dir=parent))
        (run_folder / "data").mkdir()
        shutil.copyfile(ROOT / "data/brent_spot.csv", run_folder / "data/brent_spot.csv")
        shutil.copyfile(ROOT / "data/ice_brent_expiry_calendar.json", run_folder / "data/ice_brent_expiry_calendar.json")
        shutil.copyfile(ROOT / "settings.json", run_folder / "settings.json")
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_for_app.py"), str(run_folder), str(seed)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180, check=False)
        try:
            message = json.loads(process.stdout)
        except ValueError:
            message = {}
        if not isinstance(message, dict):
            message = {}
        if process.returncode != 0:
            reason = message.get("error", "The generator stopped before a safe dataset was available.")
            raise AppInputError("{} Try another seed.".format(reason))
        if not isinstance(message.get("folder"), str):
            raise AppInputError("The generator returned no usable dataset. Generate again.")
        folder = Path(message["folder"]).resolve()
        folder.relative_to(run_folder)
        metadata = json.loads((folder / "generation_metadata.json").read_text(encoding="utf-8"))
        return _reconcile_run(folder, _read_csv(folder / "blotter.csv"),
                              _read_csv(folder / "confirmations.csv"), "generated", seed, metadata,
                              settings_path=run_folder / "settings.json")
    except subprocess.TimeoutExpired:
        raise AppInputError("Generation took too long. Try another seed.") from None
    except Exception as error:
        raise AppInputError("Generated reconciliation stopped: {}".format(error)) from None


def _table_records(table):
    """Keep measured scorer tables in the same string form as CSV output."""
    return list(csv.DictReader(io.StringIO(table.to_csv(index=False))))


def load_scorecard(run):
    """Measure only generated runs, letting the existing scorer read its labels."""
    try:
        if run.get("origin") != "generated":
            raise AppInputError("Scorecards are available only for generated runs.")
        if "scorecard" in run:
            return run["scorecard"]
        from src import scorecard
        folder = Path(run["folder"]).resolve()
        folder.relative_to(ROOT)
        key = folder / "answer_key.csv"
        if not key.is_file():
            raise AppInputError("Generated session files are no longer available. Regenerate the dataset.")
        answers = scorecard._read_records(key, ["case_id", "trade_id", "confirm_id", "case_type",
                                               "expected_outcome"], "answer key")
        scores, _details = scorecard.score_records(run["results"], answers, run["confirmations"])
        names = scorecard.name_resolution_report(answers, run["matches"])
        measured = {"scores": _table_records(scores), "names": _table_records(names)}
        run["scorecard"] = measured
        return measured
    except Exception as error:
        raise AppInputError("Scorecard unavailable: {}".format(error)) from None


def _amount(row):
    """Parse only an engine-emitted discrepancy amount, retaining blanks as absent."""
    text = row.get("value_of_discrepancy_usd", "")
    if text is None or str(text).strip() == "":
        return None
    value = Decimal(str(text))
    if not value.is_finite():
        raise AppInputError("The reported discrepancy amount must be finite.")
    return value


def summarise(run):
    """Aggregate engine output without computing any new trade valuations."""
    try:
        rows = run["results"]
        groups = {}
        amounts = []
        for row in rows:
            kind = row["break_type"]
            if kind not in groups:
                groups[kind] = {"break_type": kind, "count": 0, "value": None}
            group = groups[kind]
            group["count"] += 1
            amount = _amount(row)
            if amount is not None:
                amounts.append(amount)
                group["value"] = (group["value"] if group["value"] is not None else Decimal(0)) + amount
        total = sum(amounts, Decimal(0)) if amounts or not rows else None
        return {"trades_processed": len(run["blotter"]),
                "matched_trades": len({row["trade_id"] for row in run["matches"]}),
                "matched_pairs": len(run["matches"]),
                "review_groups": run["engine_summary"]["review_groups"],
                "total_value": total, "by_type": [groups[kind] for kind in sorted(groups)]}
    except Exception as error:
        raise AppInputError("Cannot summarise run: {}".format(error)) from None


def dollars(value):
    """Format a supplied USD amount to two decimals while leaving absent values blank."""
    try:
        return "" if value is None else "${:,.2f}".format(value)
    except Exception as error:
        raise AppInputError("Cannot display amount: {}".format(error)) from None


def sort_exceptions(rows, mode="Priority then value"):
    """Return copied exception rows ordered by the selected display-only keys."""
    try:
        modes = {"Priority then value", "Value of discrepancy (largest first)", "Break type", "Trade ID"}
        if mode not in modes:
            raise AppInputError("Unknown exception sort mode: {}".format(mode))
        priorities = {"HIGH": 0, "STANDARD": 1, "REVIEW": 2}
        copied = [dict(row, _source_index=index) for index, row in enumerate(rows)]

        def key(row):
            """Build an exact Decimal display key with missing amounts last."""
            amount = _amount(row)
            value = (amount is None, amount.copy_negate() if amount is not None else Decimal(0))
            ids = (row.get("trade_id", ""), row.get("confirm_id", ""), row.get("break_type", ""))
            priority = priorities.get(row.get("priority"), 3)
            if mode == "Priority then value":
                return (priority,) + value + ids
            if mode == "Value of discrepancy (largest first)":
                return value + (priority,) + ids
            if mode == "Break type":
                return (row.get("break_type", ""),) + value + ids
            return ids + value

        return sorted(copied, key=key)
    except Exception as error:
        raise AppInputError("Cannot sort exceptions: {}".format(error)) from None


def _row_ids(row, *columns):
    """Read only explicitly listed semicolon-separated identifiers from engine output."""
    identifiers = set()
    for column in columns:
        identifiers.update(part.strip() for part in str(row.get(column, "") or "").split(";") if part.strip())
    return identifiers


def exception_details(run, row):
    """Resolve explicit engine IDs and declared fields without comparing or guessing pairs."""
    try:
        trade_ids = _row_ids(row, "trade_id", "candidate_trade_ids")
        confirm_ids = _row_ids(row, "confirm_id", "candidate_confirm_ids")
        trades = [dict(record) for record in run["blotter"] if record["trade_id"].strip() in trade_ids]
        confirms = [dict(record) for record in run["confirmations"] if record["confirm_id"].strip() in confirm_ids]
        if (trade_ids - {record["trade_id"].strip() for record in trades}
                or confirm_ids - {record["confirm_id"].strip() for record in confirms}):
            raise AppInputError("A record listed by this tool is unavailable in session memory. Regenerate or upload again.")
        fields = {"price_usd_bbl": ["price_usd_bbl"], "volume_bbl": ["quantity", "unit"],
                  "side": ["side"], "contract_month": ["contract_month"],
                  "confirmation_count": ["trade_ref"], "pairing": []}
        affected = row.get("field_affected", "")
        highlight = fields.get(affected, [])
        note = "Fields shown are reported by this tool."
        if affected == "confirmation_count":
            note = "All records in the confirmation group are shown; no original or extra confirmation is chosen."
        elif affected == "pairing":
            note = "No definite differing field or pairing is established; all candidate records are shown."
        elif affected == "record":
            canonical = ["trade_id", "confirm_id", "trade_ref"] + COMMON_COLUMNS
            highlight = [field for field in canonical if any(field in record for record in trades + confirms)]
            note = "This tool reports a whole-record exception; all present input fields are shown."
        return {"blotter": trades, "confirmations": confirms, "highlight_fields": highlight, "note": note}
    except Exception as error:
        raise AppInputError("Cannot display exception details: {}".format(error)) from None


def invalidate_run(state):
    """Clear stale run presentation state while preserving the session workspace resource."""
    try:
        for key in ("run", "error", "page"):
            state.pop(key, None)
    except Exception as error:
        raise AppInputError("Cannot clear run state: {}".format(error)) from None
