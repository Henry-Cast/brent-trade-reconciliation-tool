"""Shared fictional inputs for engine-only tests; no generator or answer key is imported."""
from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def engine_settings():
    """Read the actual shared settings used by the command-line engine."""
    return json.loads((ROOT / "settings.json").read_text())


@pytest.fixture
def make_trade():
    """Construct a small explicitly fictional desk record with overridable fields."""
    def build(identifier="T001", **changes):
        """Return one independent dictionary without consulting generated data."""
        row = {"trade_id": identifier, "trade_date": "2026-10-01", "trader": "A. Example",
               "counterparty": "Fictional Energy Ltd", "broker": "Example Broker", "side": "BUY",
               "contract_month": "2026-12", "quantity": "5", "unit": "LOTS", "price_usd_bbl": "80.00"}
        row.update(changes)
        return row
    return build


@pytest.fixture
def make_confirmation():
    """Create a broker record from a test trade, optionally changing reference or attributes."""
    def build(trade, identifier="C001", **changes):
        """Copy the test values and replace the desk identifier with broker identifiers."""
        row = dict(trade)
        row["trade_ref"] = row.pop("trade_id")
        row["confirm_id"] = identifier
        row.update(changes)
        return row
    return build
