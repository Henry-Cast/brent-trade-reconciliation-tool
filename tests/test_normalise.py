"""Tests for Stage 2's independent, exact input normalisation."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def settings():
    """Read the project's shared tolerances, conversion factor, and aliases."""
    return json.loads((ROOT / "settings.json").read_text())


@pytest.fixture
def trade():
    """Provide an explicitly fictional record unrelated to any answer key."""
    return {"trade_id": "T001", "trade_date": "2026-10-01", "trader": "A. Example",
            "counterparty": "Fictional Energy Ltd", "broker": "Example Broker",
            "side": "BUY", "contract_month": "2026-12", "quantity": "5",
            "unit": "LOTS", "price_usd_bbl": "80.10"}


def test_normalise_preserves_raw_values_and_exact_arithmetic(trade, settings):
    """Whitespace and unit conversion must not destroy the original source values."""
    from src.normalise import normalise_records

    trade.update(side=" buy ", unit=" lots ", counterparty="  fictional  energy, LIMITED. ")
    before = deepcopy(trade)
    record = normalise_records([trade], "blotter", settings)[0]
    assert trade == before
    assert record["_raw"] == before
    assert record["_price"] == Decimal("80.10")
    assert record["_volume_bbl"] == Decimal("5000")
    assert record["_counterparty_general"] == "FICTIONAL ENERGY LTD"
    assert record["side"] == "BUY" and record["unit"] == "LOTS"


def test_general_name_rules_precede_alias_fallback(trade, settings):
    """Equivalent spelling needs no alias; a genuinely different name can use a manual alias."""
    from src.normalise import normalise_records, counterparty_resolution

    settings["counterparty_aliases"]["F E TRADING"] = "Fictional Energy Limited"
    left = normalise_records([trade], "blotter", settings)[0]
    right = dict(trade, confirm_id="C001", trade_ref="T001", counterparty="FICTIONAL   ENERGY, LIMITED.")
    right.pop("trade_id")
    generic = normalise_records([right], "confirmations", settings)[0]
    assert counterparty_resolution(left, generic) == "GENERAL_RULES"
    right["counterparty"] = "F. E. Trading"
    manual = normalise_records([right], "confirmations", settings)[0]
    assert counterparty_resolution(left, manual) == "ALIAS_TABLE"
    right["counterparty"] = "Entirely Different Energy Ltd"
    unknown = normalise_records([right], "confirmations", settings)[0]
    assert counterparty_resolution(left, unknown) == "UNRESOLVED"


@pytest.mark.parametrize("field,value", [("quantity", "NaN"), ("price_usd_bbl", "Infinity"),
                                         ("side", "LONG"), ("unit", "TONNES"),
                                         ("trade_date", "01/02/2026"), ("contract_month", "2026-13")])
def test_invalid_records_fail_clearly(trade, settings, field, value):
    """Reject invalid or ambiguous inputs instead of guessing how to repair them."""
    from src.normalise import normalise_records

    trade[field] = value
    with pytest.raises(ValueError):
        normalise_records([trade], "blotter", settings)


def test_duplicate_record_identifiers_are_rejected(trade, settings):
    """Repeated trade IDs must not be confused with repeated broker references."""
    from src.normalise import normalise_records

    with pytest.raises(ValueError, match="Duplicate"):
        normalise_records([trade, dict(trade)], "blotter", settings)
