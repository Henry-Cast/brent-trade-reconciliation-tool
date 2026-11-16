"""Tests of the generated files, independent of any reconciliation engine."""
from pathlib import Path
import json
import sys

import pandas as pd
import pytest
from decimal import Decimal

EXPECTED_COUNTS = {
    "PRICE": 6, "QUANTITY": 5, "SIDE": 3, "CONTRACT_MONTH": 4,
    "UNIT_ERROR": 2, "MISSING_CONFIRMATION": 4, "UNKNOWN_CONFIRMATION": 3,
    "DUPLICATE": 3, "EQUIVALENT_UNITS": 5, "COUNTERPARTY_VARIANT": 4,
    "ROUNDING": 3, "MISSING_TRADE_REF": 3, "AMBIGUOUS": 2,
}


def barrels(record):
    """Convert a test record's quantity into barrels without using generator logic."""
    return int(record.quantity) * (1000 if record.unit == "LOTS" else 1)


def price(record):
    """Read a CSV price as exact decimal dollars for boundary checks."""
    return Decimal(str(record.price_usd_bbl))


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_planted_cases_have_real_record_differences(tmp_path, seed):
    """Check every planted case against the actual records, not just the answer labels."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=seed, output_root=tmp_path)
    assert folder == tmp_path / f"seed_{seed}"
    b = pd.read_csv(folder / "blotter.csv", keep_default_na=False)
    c = pd.read_csv(folder / "confirmations.csv", keep_default_na=False)
    a = pd.read_csv(folder / "answer_key.csv", keep_default_na=False)
    assert len(b) == 200 and len(c) == 202
    assert b.trade_id.is_unique and c.confirm_id.is_unique
    cases = a.drop_duplicates("case_id")
    assert cases.case_type.value_counts().to_dict() == EXPECTED_COUNTS
    assert cases.expected_outcome.value_counts().to_dict() == {
        "BREAK": 30, "NO_BREAK": 15, "NEEDS_REVIEW": 2}
    assert len(a) == 49 and a.case_id.nunique() == 47
    assert set(a.columns) == {"case_id", "trade_id", "confirm_id", "case_type",
                              "field_affected", "blotter_value", "confirmation_value", "expected_outcome", "expected_matching_rule"}
    for row in a.itertuples(index=False):
        trade = b[b.trade_id == row.trade_id]
        confirm = c[c.confirm_id == row.confirm_id]
        kind = row.case_type
        if kind == "MISSING_CONFIRMATION":
            assert len(trade) == 1 and confirm.empty
            assert not c.trade_ref.eq(row.trade_id).any()
            continue
        if kind == "UNKNOWN_CONFIRMATION":
            assert trade.empty and len(confirm) == 1
            assert confirm.iloc[0].trade_ref not in set(b.trade_id)
            # Orphans use the normal counterparties; independent safety tests check attributes.
            assert confirm.iloc[0].counterparty in set(b.counterparty)
            continue
        assert len(trade) == len(confirm) == 1
        t, f = trade.iloc[0], confirm.iloc[0]
        changed_fields = {
            "PRICE": {"price_usd_bbl"}, "QUANTITY": {"quantity"}, "SIDE": {"side"},
            "CONTRACT_MONTH": {"contract_month"}, "UNIT_ERROR": {"unit"},
            "EQUIVALENT_UNITS": {"quantity", "unit"},
            "COUNTERPARTY_VARIANT": {"counterparty"}, "ROUNDING": {"price_usd_bbl"},
        }
        for field in COLUMNS[1:]:
            if field not in changed_fields.get(kind, set()):
                assert t[field] == f[field]
        if kind == "PRICE":
            assert abs(price(t) - price(f)) >= Decimal("0.05")
        elif kind == "QUANTITY":
            assert t.unit == f.unit and barrels(t) != barrels(f)
        elif kind == "SIDE":
            assert {t.side, f.side} == {"BUY", "SELL"}
        elif kind == "CONTRACT_MONTH":
            assert t.contract_month != f.contract_month
        elif kind == "UNIT_ERROR":
            assert t.quantity == f.quantity and t.unit != f.unit
            assert barrels(t) != barrels(f)
        elif kind == "DUPLICATE":
            matches = c[c.trade_ref == t.trade_id]
            assert len(matches) == 2
            assert len(matches.drop(columns="confirm_id").drop_duplicates()) == 1
        elif kind == "EQUIVALENT_UNITS":
            assert t.unit != f.unit and barrels(t) == barrels(f)
        elif kind == "COUNTERPARTY_VARIANT":
            assert t.counterparty != f.counterparty
            aliases = json.loads(Path("settings.json").read_text())["counterparty_aliases"]
            assert (t.counterparty.upper().replace(" LTD", " LIMITED") == f.counterparty
                    or aliases.get(f.counterparty) == t.counterparty.upper())
        elif kind == "ROUNDING":
            assert Decimal("0") < abs(price(t) - price(f)) <= Decimal("0.01")
        elif kind == "MISSING_TRADE_REF":
            assert f.trade_ref == ""
            for field in COLUMNS[1:]:
                assert t[field] == f[field]
        elif kind == "AMBIGUOUS":
            assert f.trade_ref == ""
        if kind not in {"MISSING_TRADE_REF", "AMBIGUOUS", "DUPLICATE", "EQUIVALENT_UNITS"}:
            if row.field_affected in {"price_usd_bbl", "quantity"}:
                assert Decimal(str(t[row.field_affected])) == Decimal(str(row.blotter_value))
                assert Decimal(str(f[row.field_affected])) == Decimal(str(row.confirmation_value))
            else:
                assert str(t[row.field_affected]) == str(row.blotter_value)
                assert str(f[row.field_affected]) == str(row.confirmation_value)
    ambiguous = a[a.case_type == "AMBIGUOUS"]
    attributes = COLUMNS[1:]
    for case_id, group in ambiguous.groupby("case_id"):
        assert len(group) == 2 and group.trade_id.nunique() == group.confirm_id.nunique() == 2
        trades = b[b.trade_id.isin(group.trade_id)]
        confirms = c[c.confirm_id.isin(group.confirm_id)]
        assert len(trades[attributes].drop_duplicates()) == 1
        assert len(confirms[attributes].drop_duplicates()) == 1
        assert confirms.trade_ref.eq("").all()
        assert trades.iloc[0][attributes].tolist() == confirms.iloc[0][attributes].tolist()
        signature = trades.iloc[0][attributes]
        assert b[attributes].eq(signature).all(axis=1).sum() == 2
    # All records not in the answer key must remain exact one-to-one matches.
    untouched = b[~b.trade_id.isin(a.trade_id)]
    assert len(untouched) == 154
    for t in untouched.itertuples(index=False):
        confirms = c[c.trade_ref == t.trade_id]
        assert len(confirms) == 1
        for field in COLUMNS[1:]:
            assert getattr(t, field) == confirms.iloc[0][field]
    first_bytes = {name: (folder / name).read_bytes() for name in [
        "blotter.csv", "confirmations.csv", "answer_key.csv"]}
    generate_dataset(seed=seed, output_root=tmp_path)
    for name, contents in first_bytes.items():
        assert (folder / name).read_bytes() == contents

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLUMNS = ["trade_id", "trade_date", "trader", "counterparty", "broker", "side",
           "contract_month", "quantity", "unit", "price_usd_bbl"]


def test_clean_dataset_is_exactly_paired(tmp_path):
    """Clean mode produces 200 exact matches and an empty answer key with headers."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=1, clean=True, output_root=tmp_path)
    assert folder == tmp_path / "clean"
    blotter = pd.read_csv(folder / "blotter.csv")
    confirmations = pd.read_csv(folder / "confirmations.csv")
    answer = pd.read_csv(folder / "answer_key.csv")
    assert list(blotter.columns) == COLUMNS
    assert list(confirmations.columns) == ["confirm_id", "trade_ref"] + COLUMNS[1:]
    assert len(blotter) == len(confirmations) == 200
    assert blotter.trade_id.is_unique and confirmations.confirm_id.is_unique
    assert confirmations.trade_ref.tolist() == blotter.trade_id.tolist()
    pd.testing.assert_frame_equal(blotter.drop(columns="trade_id"),
                                  confirmations.drop(columns=["confirm_id", "trade_ref"]))
    assert answer.empty
    assert set(blotter.unit) == {"LOTS"}
    assert set(blotter.side) == {"BUY", "SELL"}
    dates = pd.read_csv("data/brent_spot.csv").trade_date
    assert set(blotter.trade_date) <= set(dates)
    assert blotter.quantity.gt(0).all() and blotter.price_usd_bbl.gt(0).all()
    published = pd.read_csv("data/brent_spot.csv").set_index("trade_date")
    settings = json.loads(Path("settings.json").read_text())
    for trade in blotter.itertuples(index=False):
        contract_month = pd.Period(trade.contract_month, freq="M")
        front_month_rank = contract_month.ordinal - pd.Period("2026-12", freq="M").ordinal
        assert front_month_rank in {0, 1, 2}
        spot = Decimal(str(published.loc[trade.trade_date, "spot_price_usd_bbl"]))
        offset = Decimal(front_month_rank) * Decimal(settings["contract_month_adjustment_usd_bbl"])
        noise = Decimal(str(trade.price_usd_bbl)) - spot - offset
        assert Decimal("-0.10") <= noise <= Decimal("0.10")
    attributes = ["trade_date", "counterparty", "side", "contract_month", "quantity", "price_usd_bbl"]
    assert not blotter.duplicated(attributes).any()


def test_same_seed_has_identical_bytes(tmp_path):
    """A seed controls all random choices and output formatting."""
    from src.generate import generate_dataset

    first = generate_dataset(seed=1, clean=True, output_root=tmp_path / "first")
    second = generate_dataset(seed=1, clean=True, output_root=tmp_path / "second")
    for name in ["blotter.csv", "confirmations.csv", "answer_key.csv"]:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    third = generate_dataset(seed=2, clean=True, output_root=tmp_path / "third")
    assert (first / "blotter.csv").read_bytes() != (third / "blotter.csv").read_bytes()
