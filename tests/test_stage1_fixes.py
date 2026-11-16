"""Regression tests for the three approved Stage 1 corrections."""
from decimal import Decimal
from pathlib import Path
import json
import random
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CLIPS = {5, 10, 25, 50, 100, 200}
FIELDS = ["trade_date", "counterparty", "side", "contract_month", "quantity", "price_usd_bbl"]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_random_clips_and_only_planted_identical_pairs(tmp_path, seed):
    """Sizes repeat freely, while full identical signatures occur only in the two planted pairs."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=seed, output_root=tmp_path)
    b = pd.read_csv(folder / "blotter.csv")
    c = pd.read_csv(folder / "confirmations.csv")
    a = pd.read_csv(folder / "answer_key.csv")
    counts = b.quantity.value_counts()
    assert set(counts.index) == CLIPS
    assert counts.min() > 1
    assert set(c.loc[c.unit == "LOTS", "quantity"]) <= CLIPS
    unknown_ids = a.loc[a.case_type == "UNKNOWN_CONFIRMATION", "confirm_id"]
    unknown = c[c.confirm_id.isin(unknown_ids)]
    assert not unknown.duplicated(FIELDS).any()
    identical = b[b.duplicated(FIELDS, keep=False)]
    ambiguous = a[a.case_type == "AMBIGUOUS"]
    assert len(identical) == 4
    assert set(identical.trade_id) == set(ambiguous.trade_id)
    assert sorted(identical.groupby(FIELDS).size().tolist()) == [2, 2]
    for case_id, group in ambiguous.groupby("case_id"):
        trades = b[b.trade_id.isin(group.trade_id)]
        assert len(trades[FIELDS].drop_duplicates()) == 1
    clean = generate_dataset(seed=seed, clean=True, output_root=tmp_path)
    clean_trades = pd.read_csv(clean / "blotter.csv")
    assert set(clean_trades.quantity) == CLIPS
    assert not clean_trades.duplicated(FIELDS).any()


def test_signature_uses_full_combination_and_barrel_volume():
    """Names outside the matching combination do not matter, and equivalent units share a key."""
    from src.generate import trade_signature

    trade = {"trade_date": "2026-10-01", "counterparty": "Fictional Fuels Ltd",
             "side": "BUY", "contract_month": "2026-12", "quantity": 5,
             "unit": "LOTS", "price_usd_bbl": "80.00", "trader": "A. Example"}
    equivalent = dict(trade, quantity=5000, unit="BBL", trader="B. Example")
    signature = trade_signature(trade, 1000)
    assert signature == trade_signature(equivalent, 1000)
    alternatives = {"trade_date": "2026-10-02", "counterparty": "Other Fictional Fuels Ltd",
                    "side": "SELL", "contract_month": "2027-01", "quantity": 10,
                    "price_usd_bbl": "80.01"}
    for field, value in alternatives.items():
        assert trade_signature(dict(trade, **{field: value}), 1000) != signature


def test_redraw_occurs_only_for_a_full_collision():
    """Replaying a real seeded candidate proves full collisions redraw but partial ones do not."""
    from src.generate import draw_unique_trade, trade_signature

    prices = pd.DataFrame({"trade_date": [pd.Timestamp("2026-10-01")],
                           "spot_price_usd_bbl": [80.0]})
    settings = json.loads((ROOT / "settings.json").read_text())
    first_seen = set()
    first = draw_unique_trade(0, prices, random.Random(1), first_seen, settings)
    signature = trade_signature(first, 1000)
    assert first_seen == {signature}
    collided_seen = {signature}
    redrawn = draw_unique_trade(0, prices, random.Random(1), collided_seen, settings)
    assert trade_signature(redrawn, 1000) != signature
    assert len(collided_seen) == 2
    # Keep five matching fields, changing just one in the existing signature.
    for position in range(len(signature)):
        partial = list(signature)
        partial[position] = signature[position] + Decimal("0.02") if position == 5 else "different value"
        seen = {tuple(partial)}
        accepted = draw_unique_trade(0, prices, random.Random(1), seen, settings)
        assert accepted == first
        assert len(seen) == 2


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_negative_configured_adjustment_and_noise_bounds(tmp_path, seed):
    """The front has zero adjustment; later ranks use the configured negative step and bounded noise."""
    from src.generate import generate_dataset

    settings = json.loads((ROOT / "settings.json").read_text())
    adjustment = Decimal(settings["contract_month_adjustment_usd_bbl"])
    assert adjustment == Decimal("-0.15")
    offsets = [adjustment * rank for rank in [0, 1, 2]]
    assert offsets[0] == Decimal("0")
    assert offsets[0] > offsets[1] > offsets[2]
    folder = generate_dataset(seed=seed, output_root=tmp_path)
    b = pd.read_csv(folder / "blotter.csv", dtype={"price_usd_bbl": str})
    published = pd.read_csv(ROOT / "data/brent_spot.csv", dtype={"spot_price_usd_bbl": str})
    spots = published.set_index("trade_date").spot_price_usd_bbl
    for trade in b.itertuples(index=False):
        rank = pd.Period(trade.contract_month, "M").ordinal - pd.Period("2026-12", "M").ordinal
        assert rank in {0, 1, 2}
        noise = Decimal(trade.price_usd_bbl) - Decimal(spots[trade.trade_date]) - adjustment * rank
        assert Decimal("-0.10") <= noise <= Decimal("0.10")


def test_changing_the_setting_changes_the_contract_adjustment():
    """Replaying the same random draws isolates the effect of the configurable adjustment."""
    from src.generate import draw_unique_trade

    prices = pd.DataFrame({"trade_date": [pd.Timestamp("2026-10-01")],
                           "spot_price_usd_bbl": [80.0]})
    settings = json.loads((ROOT / "settings.json").read_text())
    alternative = dict(settings, contract_month_adjustment_usd_bbl="-0.45")
    observed_ranks = set()
    for seed in [1, 2, 4]:
        first = draw_unique_trade(0, prices, random.Random(seed), set(), settings)
        second = draw_unique_trade(0, prices, random.Random(seed), set(), alternative)
        rank = pd.Period(first["contract_month"], "M").ordinal - pd.Period("2026-12", "M").ordinal
        expected = (Decimal("-0.45") - Decimal(settings["contract_month_adjustment_usd_bbl"])) * rank
        assert Decimal(second["price_usd_bbl"]) - Decimal(first["price_usd_bbl"]) == expected
        observed_ranks.add(rank)
    assert observed_ranks == {0, 1, 2}


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_price_breaks_vary_with_an_exact_five_cent_boundary(tmp_path, seed):
    """The six actual price differences vary in whole cents within the approved range."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=seed, output_root=tmp_path)
    b = pd.read_csv(folder / "blotter.csv", dtype=str).set_index("trade_id")
    c = pd.read_csv(folder / "confirmations.csv", dtype=str).set_index("confirm_id")
    a = pd.read_csv(folder / "answer_key.csv", dtype=str)
    differences = []
    for row in a[a.case_type == "PRICE"].itertuples(index=False):
        left = Decimal(b.loc[row.trade_id, "price_usd_bbl"])
        right = Decimal(c.loc[row.confirm_id, "price_usd_bbl"])
        difference = abs(left - right)
        assert Decimal("0.05") <= difference <= Decimal("1.00")
        assert difference * 100 == (difference * 100).to_integral_value()
        assert Decimal(row.blotter_value) == left
        assert Decimal(row.confirmation_value) == right
        differences.append(difference)
    assert len(differences) == 6
    assert Decimal("0.05") in differences
    assert len(set(differences)) == 6
