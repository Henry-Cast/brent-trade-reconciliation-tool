"""Validate the published CSV directly; historical workbook month selection is retired."""
from decimal import Decimal
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]


def test_price_preparation_uses_latest_complete_month(tmp_path):
    """Keep the historical case ID: load all supplied CSV rows, without selecting a month or writing."""
    from src.generate import load_prices

    source = tmp_path / "prices.csv"
    source.write_text("trade_date,spot_price_usd_bbl\n2026-10-02,135.51\n2026-10-01,114.82\n2026-11-02,123.4567890123456789\n")
    before = source.read_bytes(), source.stat().st_mtime_ns
    prices = load_prices(source)
    assert prices["trade_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-10-01", "2026-10-02", "2026-11-02"]
    assert prices["spot_price_usd_bbl"].tolist() == [
        Decimal("114.82"), Decimal("135.51"), Decimal("123.4567890123456789")]
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert list(tmp_path.iterdir()) == [source]
    published = load_prices(ROOT / "data/brent_spot.csv")
    expected = pd.read_csv(ROOT / "data/brent_spot.csv", dtype=str)
    assert published["trade_date"].dt.strftime("%Y-%m-%d").tolist() == expected["trade_date"].tolist()
    assert published["spot_price_usd_bbl"].tolist() == [Decimal(value) for value in expected["spot_price_usd_bbl"]]


@pytest.mark.parametrize("text,reason", [
    ("", "empty"),
    ("trade_date,spot_price_usd_bbl\n", "empty"),
    ("date,price\n2026-10-01,80\n", "columns"),
    ("trade_date,spot_price_usd_bbl,extra\n2026-10-01,80,x\n", "columns"),
    ("trade_date,spot_price_usd_bbl\n,80\n", "trade_date"),
    ("trade_date,spot_price_usd_bbl\n2026-02-30,80\n", "trade_date"),
    ("trade_date,spot_price_usd_bbl\n2026-1-01,80\n", "trade_date"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01T12:00:00,80\n", "trade_date"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,no\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,NaN\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,Infinity\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,-Infinity\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,0\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,-80\n", "price"),
    ("trade_date,spot_price_usd_bbl\n2026-10-01,80\n2026-10-01,81\n", "duplicate"),
], ids=["empty-file", "empty-rows", "missing-columns", "extra-column", "missing-date",
        "invalid-date", "non-iso-date", "timestamp", "missing-price", "nonnumeric-price",
        "nan", "infinity", "negative-infinity", "zero", "negative", "duplicate-date"])
def test_csv_price_validation(tmp_path, text, reason):
    """Reject unusable prices before sampling and never repair the input file."""
    from src.generate import load_prices

    source = tmp_path / "prices.csv"
    source.write_text(text)
    before = source.read_bytes(), source.stat().st_mtime_ns
    with pytest.raises(ValueError, match=reason):
        load_prices(source)
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_csv_price_readability(tmp_path):
    """Missing, directory and undecodable source files cannot become generated prices."""
    from src.generate import load_prices

    with pytest.raises(OSError):
        load_prices(tmp_path / "missing.csv")
    with pytest.raises(OSError):
        load_prices(tmp_path)
    source = tmp_path / "prices.csv"
    source.write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(UnicodeError):
        load_prices(source)


def test_complete_month_selection_and_missing_prices(tmp_path):
    """Keep the historical case ID: honor CSV dates, including month-end weekends, and reject missing prices."""
    from src.generate import load_prices

    source = tmp_path / "prices.csv"
    dates = pd.bdate_range("2026-09-01", "2026-10-30")
    prices = pd.DataFrame({"trade_date": dates, "spot_price_usd_bbl": 80.0})
    prices.to_csv(source, index=False)
    selected = load_prices(source)
    assert set(selected["trade_date"].dt.strftime("%Y-%m")) == {"2026-09", "2026-10"}
    assert selected["trade_date"].iloc[-1] == pd.Timestamp("2026-10-30")
    prices.loc[prices.index[-1], "spot_price_usd_bbl"] = None
    prices.to_csv(source, index=False)
    with pytest.raises(ValueError, match="price"):
        load_prices(source)
