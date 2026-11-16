"""Measure exception detection independently of the reconciliation engine."""

import argparse
from pathlib import Path
from decimal import Decimal

import pandas as pd

POSITIVE_TYPES = ["PRICE", "QUANTITY", "SIDE", "CONTRACT_MONTH", "UNIT_ERROR",
                  "MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION", "DUPLICATE", "AMBIGUOUS"]
QUIET_TYPES = ["EQUIVALENT_UNITS", "COUNTERPARTY_VARIANT", "ROUNDING", "MISSING_TRADE_REF"]
TABLE_COLUMNS = ["case_type", "found", "missed", "false_alarms", "mislabelled",
                 "precision", "recall", "correctly_quiet"]
DETAIL_COLUMNS = ["status", "case_id", "expected_type", "predicted_type", "result_index",
                  "trade_ids", "confirm_ids", "reason"]


def _identifiers(value):
    """Read semicolon-separated record IDs, treating absent values as empty sets."""
    if value is None or pd.isna(value):
        return frozenset()
    return frozenset(part.strip() for part in str(value).split(";") if part.strip())


def _record_ids(record):
    """Get both record identifier sets from one input row."""
    trades = _identifiers(record.get("trade_id")) | _identifiers(record.get("candidate_trade_ids"))
    confirms = _identifiers(record.get("confirm_id")) | _identifiers(record.get("candidate_confirm_ids"))
    return trades, confirms


def _expected_cases(answers, confirmations):
    """Combine answer rows with the same case ID into one exact expected group."""
    grouped = {}
    for index, answer in enumerate(answers):
        key = answer.get("case_id") or "answer_row_{}".format(index)
        if key not in grouped:
            grouped[key] = dict(answer)
        else:
            existing = grouped[key]
            if (existing["case_type"] != answer["case_type"]
                    or existing.get("expected_outcome") != answer.get("expected_outcome")):
                raise ValueError("Conflicting answer rows for case {}.".format(key))
            trades, confirms = _record_ids(existing)
            extra_trades, extra_confirms = _record_ids(answer)
            existing["trade_id"] = ";".join(sorted(trades | extra_trades))
            existing["confirm_id"] = ";".join(sorted(confirms | extra_confirms))
    for expected in grouped.values():
        if expected["case_type"] == "DUPLICATE":
            trades, confirms = _record_ids(expected)
            raw_confirms = frozenset()
            for confirmation in confirmations:
                if str(confirmation.get("trade_ref", "")).strip() in trades:
                    raw_confirms = raw_confirms | _identifiers(confirmation.get("confirm_id"))
            if len(raw_confirms) < 2 or not confirms.issubset(raw_confirms):
                raise ValueError("DUPLICATE {} needs its complete raw confirmation group.".format(
                    expected.get("case_id", "")))
            expected["confirm_id"] = ";".join(sorted(raw_confirms))
    return list(grouped.values())


def _detail(status, expected, predicted, index, reason):
    """Create a trace row explaining one expected case or emitted exception."""
    source = predicted if predicted is not None else expected
    trades, confirms = _record_ids(source)
    return {"status": status, "case_id": expected.get("case_id", "") if expected else "",
            "expected_type": expected.get("case_type", "") if expected else "",
            "predicted_type": predicted.get("break_type", "") if predicted else "",
            "result_index": index if index is not None else "",
            "trade_ids": ";".join(sorted(trades)), "confirm_ids": ";".join(sorted(confirms)),
            "reason": reason}


def score_records(results, answers, confirmations):
    """Return (summary DataFrame, details DataFrame), scoring exact IDs and labels."""
    answers = _expected_cases(answers, confirmations)
    kinds = list(dict.fromkeys(POSITIVE_TYPES + QUIET_TYPES
                               + [a["case_type"] for a in answers]
                               + [r["break_type"] for r in results]))
    counts = {kind: {"case_type": kind, "found": 0, "missed": 0, "false_alarms": 0,
                     "mislabelled": 0, "correctly_quiet": 0} for kind in kinds}
    used = set()
    exact_matches = {}
    # Reserve every correct field result before diagnosing wrong labels on missed fields.
    for case_index, expected in enumerate(answers):
        if expected.get("expected_outcome") == "NO_BREAK":
            continue
        for index, predicted in enumerate(results):
            if index not in used and predicted["break_type"] == expected["case_type"] and _record_ids(predicted) == _record_ids(expected):
                exact_matches[case_index] = index
                used.add(index)
                break
    details = []
    for case_index, expected in enumerate(answers):
        kind = expected["case_type"]
        if expected.get("expected_outcome") == "NO_BREAK":
            trades, confirms = _record_ids(expected)
            touching = []
            for index, predicted in enumerate(results):
                predicted_trades, predicted_confirms = _record_ids(predicted)
                if trades & predicted_trades or confirms & predicted_confirms:
                    touching.append(index)
            if touching:
                for index in touching:
                    details.append(_detail("INCORRECTLY_ALERTED", expected, results[index], index,
                                           "Alert touches a NO_BREAK case; false alarm counted on predicted type only."))
            else:
                counts[kind]["correctly_quiet"] += 1
                details.append(_detail("CORRECTLY_QUIET", expected, None, None,
                                       "No alert touches either record set."))
            continue
        match = exact_matches.get(case_index)
        if match is None:
            counts[kind]["missed"] += 1
            wrong = next((index for index, predicted in enumerate(results)
                          if index not in used and predicted["break_type"] != kind
                          and _record_ids(predicted) == _record_ids(expected)), None)
            if wrong is not None:
                counts[kind]["mislabelled"] += 1
                details.append(_detail("MISSED", expected, results[wrong], wrong,
                                       "Mislabelled: exact IDs but wrong type; row is also a false alarm."))
            else:
                details.append(_detail("MISSED", expected, None, None, "No exact IDs and type match."))
        else:
            used.add(match)
            counts[kind]["found"] += 1
            details.append(_detail("FOUND", expected, results[match], match, "Exact IDs and type."))
    for index, predicted in enumerate(results):
        if index not in used:
            counts[predicted["break_type"]]["false_alarms"] += 1
            details.append(_detail("FALSE_ALARM", None, predicted, index, "Unmatched exception row."))
    for values in counts.values():
        predictions = values["found"] + values["false_alarms"]
        expected_count = values["found"] + values["missed"]
        values["precision"] = Decimal(values["found"]) / Decimal(predictions) if predictions else "N/A"
        values["recall"] = Decimal(values["found"]) / Decimal(expected_count) if expected_count else "N/A"
    return (pd.DataFrame(list(counts.values()), columns=TABLE_COLUMNS),
            pd.DataFrame(details, columns=DETAIL_COLUMNS))


def name_resolution_report(answers, matches):
    """Count observed resolution methods for exact planted counterparty-variant pairs."""
    methods = {"GENERAL_RULES": 0, "ALIAS_TABLE": 0, "UNRESOLVED": 0}
    variants = [answer for answer in answers if answer["case_type"] == "COUNTERPARTY_VARIANT"]
    for expected in _expected_cases(variants, []):
        observed = set()
        for match in matches:
            pair_ids = (_identifiers(match.get("trade_id")), _identifiers(match.get("confirm_id")))
            if pair_ids == _record_ids(expected):
                observed.add(match.get("counterparty_resolution", "UNRESOLVED"))
        method = next(iter(observed)) if len(observed) == 1 else "UNRESOLVED"
        if method not in methods:
            method = "UNRESOLVED"
        methods[method] += 1
    return pd.DataFrame([{"counterparty_resolution": method, "count": count}
                         for method, count in methods.items()])


def _read_records(path, required_columns, label):
    """Read CSV records as text and reject missing columns even in empty datasets."""
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = sorted(set(required_columns) - set(table.columns))
    if missing:
        raise ValueError("{} is missing required columns: {}".format(label, ", ".join(missing)))
    return table.to_dict("records")


def main(argv=None):
    """Read explicit CSV paths, save the three reports, and print measured counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["results", "answer-key", "confirmations", "matches", "output", "details", "name-report"]:
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    inputs = {Path(path).resolve() for path in
              [args.results, args.answer_key, args.confirmations, args.matches]}
    outputs = [Path(path).resolve() for path in [args.output, args.details, args.name_report]]
    if inputs.intersection(outputs) or len(set(outputs)) != len(outputs):
        parser.error("Output paths must be distinct from each other and all input files.")
    results = _read_records(args.results, ["trade_id", "confirm_id", "break_type"], "results")
    answers = _read_records(args.answer_key, ["case_id", "trade_id", "confirm_id", "case_type",
                                             "expected_outcome"], "answer key")
    confirmations = _read_records(args.confirmations, ["trade_ref", "confirm_id"], "confirmations")
    matches = _read_records(args.matches, ["trade_id", "confirm_id", "counterparty_resolution"], "matches")
    table, details = score_records(results, answers, confirmations)
    names = name_resolution_report(answers, matches)
    table.to_csv(args.output, index=False)
    details.to_csv(args.details, index=False)
    names.to_csv(args.name_report, index=False)
    print(table.to_string(index=False))
    print("\nPlanted COUNTERPARTY_VARIANT resolution methods:")
    print(names.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
