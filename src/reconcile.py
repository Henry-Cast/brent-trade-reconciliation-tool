"""Command-line reconciliation: explicit trade inputs only, with no access to generated labels."""
from pathlib import Path
import argparse
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.normalise import load_settings, normalise_file
from src.match import match_records
from src.compare import compare_matches, RESULT_COLUMNS, MATCH_COLUMNS


def project_path(path):
    """Resolve a supplied file path and refuse work outside the approved project folder."""
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise ValueError(f"Path is outside this project: {path}") from error
    if resolved.name == "answer_key.csv":
        raise ValueError("The reconciliation engine does not accept generated label files.")
    return resolved


def write_csv(path, rows, columns):
    """Write a predictable CSV with headers even when there are no results."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def reconcile_files(blotter, confirmations, results, matches, settings=ROOT / "settings.json"):
    """Run normalise, reference/attribute matching, comparison, and leftover classification."""
    blotter, confirmations, results, matches, settings = [project_path(path)
                                                        for path in [blotter, confirmations, results, matches, settings]]
    inputs = {blotter, confirmations, settings}
    if results == matches or results in inputs or matches in inputs:
        raise ValueError("Outputs must be distinct and must not overwrite any input or settings file.")
    configuration = load_settings(settings)
    trades = normalise_file(blotter, "blotter", configuration)
    broker_records = normalise_file(confirmations, "confirmations", configuration)
    matched = match_records(trades, broker_records, configuration)
    exception_rows, match_rows = compare_matches(matched, configuration)
    write_csv(results, exception_rows, RESULT_COLUMNS)
    write_csv(matches, match_rows, MATCH_COLUMNS)
    return {"blotter_rows": len(trades), "confirmation_rows": len(broker_records),
            "matched_pairs": len(match_rows), "review_groups": len(matched["reviews"]),
            "result_rows": len(exception_rows), "results": str(results.relative_to(ROOT)),
            "matches": str(matches.relative_to(ROOT))}


def main():
    """Expose a command that accepts only the two trade files, settings, and output paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blotter", required=True)
    parser.add_argument("--confirmations", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--matches", required=True)
    parser.add_argument("--settings", default=str(ROOT / "settings.json"))
    args = parser.parse_args()
    try:
        summary = reconcile_files(args.blotter, args.confirmations, args.results, args.matches, args.settings)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Reconciliation stopped: {error}\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
