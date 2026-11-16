"""Rule 1: clean explicit trade inputs without using labels or guessing identifiers."""
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import re
import unicodedata

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COMMON_COLUMNS = ["trade_date", "trader", "counterparty", "broker", "side",
                  "contract_month", "quantity", "unit", "price_usd_bbl"]


def load_settings(path):
    """Load the one shared settings file and validate exact tolerances and unit conversion."""
    with Path(path).open(encoding="utf-8") as handle:
        settings = json.load(handle)
    if Decimal(str(settings["price_tolerance_usd_bbl"])) < 0:
        raise ValueError("Price tolerance cannot be negative.")
    if Decimal(str(settings["volume_tolerance_bbl"])) != 0:
        raise ValueError("SPEC requires zero volume tolerance.")
    if Decimal(str(settings["barrels_per_lot"])) <= 0:
        raise ValueError("Barrels per lot must be positive.")
    return settings


def general_name(name):
    """Standardise capitals, punctuation, spacing, and the Ltd/Limited legal suffix."""
    text = unicodedata.normalize("NFKC", str(name)).upper()
    text = "".join(" " if unicodedata.category(character).startswith("P") else character
                   for character in text)
    words = text.split()
    if words and words[-1] == "LIMITED":
        words[-1] = "LTD"
    return " ".join(words)


def alias_name(name, settings):
    """Resolve a generalised spelling through manually maintained nontrivial aliases."""
    aliases = {}
    for source, target in settings.get("counterparty_aliases", {}).items():
        source, target = general_name(source), general_name(target)
        if source != target:
            if source in aliases and aliases[source] != target:
                raise ValueError(f"Conflicting counterparty aliases for {source}.")
            aliases[source] = target
    return aliases.get(name, name)


def counterparty_resolution(left, right):
    """Try general spelling rules first and only then the explicit alias fallback."""
    if left["_counterparty_general"] == right["_counterparty_general"]:
        return "GENERAL_RULES"
    if left["_counterparty_alias"] == right["_counterparty_alias"]:
        return "ALIAS_TABLE"
    return "UNRESOLVED"


def positive_decimal(value, field):
    """Parse an exact positive number, rejecting missing, infinite, or invalid values."""
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as error:
        raise ValueError(f"Invalid {field}: {value!r}") from error
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be finite and positive: {value!r}")
    return number


def normalise_records(rows, kind, settings):
    """Preserve source fields, validate IDs and dates, and add exact comparison attributes."""
    if kind not in {"blotter", "confirmations"}:
        raise ValueError("Input kind must be blotter or confirmations.")
    id_column = "trade_id" if kind == "blotter" else "confirm_id"
    required = COMMON_COLUMNS + [id_column]
    if kind == "confirmations":
        required.append("trade_ref")
    records = []
    seen = set()
    for source in rows:
        missing = [column for column in required if column not in source]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        row = {column: str(source[column]).strip() for column in required}
        row["_raw"] = dict(source)
        identifier = row[id_column]
        if not identifier or ";" in identifier:
            raise ValueError(f"Invalid {id_column}: {identifier!r}")
        if identifier in seen:
            raise ValueError(f"Duplicate {id_column}: {identifier}")
        seen.add(identifier)
        row["_date"] = date.fromisoformat(row["trade_date"])
        if not re.fullmatch(r"\d{4}-\d{2}", row["contract_month"]):
            raise ValueError("Contract month must be YYYY-MM.")
        date.fromisoformat(row["contract_month"] + "-01")
        row["side"] = row["side"].upper()
        row["unit"] = row["unit"].upper()
        if row["side"] not in {"BUY", "SELL"} or row["unit"] not in {"LOTS", "BBL"}:
            raise ValueError(f"Unsupported side or unit in {identifier}.")
        row["_quantity"] = positive_decimal(row["quantity"], "quantity")
        row["_price"] = positive_decimal(row["price_usd_bbl"], "price_usd_bbl")
        multiplier = Decimal(str(settings["barrels_per_lot"])) if row["unit"] == "LOTS" else Decimal(1)
        row["_volume_bbl"] = row["_quantity"] * multiplier
        row["_counterparty_general"] = general_name(row["counterparty"])
        if not row["_counterparty_general"]:
            raise ValueError(f"Empty counterparty in {identifier}.")
        row["_counterparty_alias"] = alias_name(row["_counterparty_general"], settings)
        records.append(row)
    return records


def normalise_file(path, kind, settings):
    """Read only the explicitly supplied CSV, keeping decimals and blank references as text."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    return normalise_records(frame.to_dict("records"), kind, settings)
