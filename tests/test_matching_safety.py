"""Independent checks that generated labels are safe under SPEC section 7."""
from datetime import date
from decimal import Decimal
from itertools import combinations
from pathlib import Path
import csv
import json
import random
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_rows(folder, filename):
    """Read every CSV field as text, including blank references and decimal prices."""
    with (folder / filename).open(newline="") as handle:
        return list(csv.DictReader(handle))


def normalized_attributes(row, settings):
    """Independently apply the spec's text, date, alias, and barrel conversions for tests."""
    counterparty = row["counterparty"].strip().upper()
    counterparty = settings["counterparty_aliases"].get(counterparty, counterparty)
    volume = Decimal(str(row["quantity"]))
    if row["unit"].strip().upper() == "LOTS":
        volume *= settings["barrels_per_lot"]
    return (date.fromisoformat(row["trade_date"].strip()), counterparty,
            row["side"].strip().upper(), row["contract_month"].strip(),
            volume, Decimal(str(row["price_usd_bbl"])))


def allowed_confirmation_pairs(confirmations, answers):
    """Allow only the specific original/duplicate pair or the two IDs of one ambiguous case."""
    allowed = set()
    ambiguous_groups = {}
    for answer in answers:
        if answer["case_type"] == "DUPLICATE":
            originals = [row for row in confirmations
                         if row["trade_ref"] == answer["trade_id"]
                         and row["confirm_id"] != answer["confirm_id"]]
            assert len(originals) == 1
            allowed.add(tuple(sorted([originals[0]["confirm_id"], answer["confirm_id"]])))
        elif answer["case_type"] == "AMBIGUOUS":
            ambiguous_groups.setdefault(answer["case_id"], []).append(answer["confirm_id"])
    for identifiers in ambiguous_groups.values():
        assert len(identifiers) == 2
        allowed.add(tuple(sorted(identifiers)))
    return allowed


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_no_unplanted_confirmation_collisions(tmp_path, seed):
    """Every exact or tolerance-equivalent pair must be an explicitly planted exception."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=seed, output_root=tmp_path)
    settings = json.loads((ROOT / "settings.json").read_text())
    confirmations = read_rows(folder, "confirmations.csv")
    answers = read_rows(folder, "answer_key.csv")
    allowed = allowed_confirmation_pairs(confirmations, answers)
    assert len(allowed) == 5
    actual = set()
    for left, right in combinations(confirmations, 2):
        first = normalized_attributes(left, settings)
        second = normalized_attributes(right, settings)
        if first[:5] == second[:5] and abs(first[5] - second[5]) <= Decimal("0.01"):
            actual.add(tuple(sorted([left["confirm_id"], right["confirm_id"]])))
    assert actual == allowed, {"unexpected": sorted(actual - allowed),
                               "missing_planted_pairs": sorted(allowed - actual)}


def test_collision_redraw_respects_one_cent_boundary():
    """One-cent differences collide, while two-cent differences are accepted without redraw."""
    from src.generate import draw_unique_trade, trade_signature

    settings = json.loads((ROOT / "settings.json").read_text())
    prices = pd.DataFrame({"trade_date": [pd.Timestamp("2026-10-01")],
                           "spot_price_usd_bbl": [80.0]})
    first = draw_unique_trade(0, prices, random.Random(17), set(), settings)
    signature = trade_signature(first, settings["barrels_per_lot"])
    for difference in [Decimal("-0.01"), Decimal("0.01")]:
        existing = signature[:5] + (signature[5] + difference,)
        result = draw_unique_trade(0, prices, random.Random(17), {existing}, settings)
        assert result != first
    for difference in [Decimal("-0.02"), Decimal("0.02")]:
        existing = signature[:5] + (signature[5] + difference,)
        result = draw_unique_trade(0, prices, random.Random(17), {existing}, settings)
        assert result == first


@pytest.fixture(params=[1, 2, 3, 4, 5])
def unknown_dataset(tmp_path, request):
    """Generate a seeded dataset and return its actual orphan records and settings."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=request.param, output_root=tmp_path)
    blotter = read_rows(folder, "blotter.csv")
    confirmations = read_rows(folder, "confirmations.csv")
    answers = read_rows(folder, "answer_key.csv")
    settings = json.loads((ROOT / "settings.json").read_text())
    unknown_ids = {row["confirm_id"] for row in answers if row["case_type"] == "UNKNOWN_CONFIRMATION"}
    missing_ids = {row["trade_id"] for row in answers if row["case_type"] == "MISSING_CONFIRMATION"}
    unknown = [row for row in confirmations if row["confirm_id"] in unknown_ids]
    missing = [row for row in blotter if row["trade_id"] in missing_ids]
    assert len(unknown) == 3 and len(missing) == 4
    return blotter, unknown, missing, settings


def candidate_kind(left, right, settings):
    """Return 0 for an exact candidate, 1 for a near candidate, or None for no candidate."""
    first = normalized_attributes(left, settings)
    second = normalized_attributes(right, settings)
    if first[:2] != second[:2]:
        return None
    differences = sum(first[position] != second[position] for position in [2, 3, 4])
    differences += int(abs(first[5] - second[5]) > Decimal(settings["price_tolerance_usd_bbl"]))
    return differences if differences <= 1 else None


def test_unknowns_are_fresh_diverse_draws_with_one_blank_reference(unknown_dataset):
    """Unknowns vary across the requested fields, use normal pools and prices, and have one blank ref."""
    blotter, unknown, missing, settings = unknown_dataset
    blotter_ids = {row["trade_id"] for row in blotter}
    assert sum(row["trade_ref"] == "" for row in unknown) == 1
    nonblank = [row["trade_ref"] for row in unknown if row["trade_ref"]]
    assert len(set(nonblank)) == 2
    assert not set(nonblank) & blotter_ids
    for field in ["trade_date", "counterparty", "contract_month", "price_usd_bbl"]:
        assert len({row[field] for row in unknown}) == 3
    assert {row["side"] for row in unknown} == {"BUY", "SELL"}
    assert len({row["broker"] for row in unknown}) >= 2
    assert {row["counterparty"] for row in unknown} <= {row["counterparty"] for row in blotter}
    assert {row["broker"] for row in unknown} <= {row["broker"] for row in blotter}
    published = pd.read_csv(ROOT / "data/brent_spot.csv", dtype=str).set_index("trade_date")
    adjustment = Decimal(settings["contract_month_adjustment_usd_bbl"])
    for row in unknown:
        assert int(row["quantity"]) in {5, 10, 25, 50, 100, 200}
        rank = pd.Period(row["contract_month"], "M").ordinal - pd.Period("2026-12", "M").ordinal
        assert rank in {0, 1, 2}
        spot = Decimal(published.loc[row["trade_date"], "spot_price_usd_bbl"])
        noise = Decimal(row["price_usd_bbl"]) - spot - rank * adjustment
        assert Decimal("-0.10") <= noise <= Decimal("0.10")


def test_no_unknown_matches_a_missing_trade(unknown_dataset):
    """Neither an exact nor any permitted one-field match may contradict the orphan labels."""
    blotter, unknown, missing, settings = unknown_dataset
    for confirmation in unknown:
        for trade in missing:
            assert candidate_kind(confirmation, trade, settings) is None, (
                confirmation["confirm_id"], trade["trade_id"])


def test_blank_unknown_matches_no_blotter_trade(unknown_dataset):
    """The blank-reference orphan must remain unmatched against all 200 desk records."""
    blotter, unknown, missing, settings = unknown_dataset
    blank = [row for row in unknown if row["trade_ref"] == ""]
    assert len(blank) == 1
    for trade in blotter:
        assert candidate_kind(blank[0], trade, settings) is None, (
            blank[0]["confirm_id"], trade["trade_id"])


def test_final_validation_rejects_a_postplant_collision():
    """A one-cent collision introduced after initial generation cannot reach output files."""
    from src.generate import validate_dataset_safety

    settings = json.loads((ROOT / "settings.json").read_text())
    trade = {"trade_id": "T000001", "trade_date": "2026-10-01",
             "counterparty": "Kestrel Shoal Energy Ltd", "side": "BUY",
             "contract_month": "2026-12", "quantity": 5, "unit": "LOTS",
             "price_usd_bbl": "80.00"}
    original = dict(trade, confirm_id="C000001", trade_ref="T000001")
    collision = dict(original, confirm_id="C000002", trade_ref="T000002",
                     counterparty=" KESTREL SHOAL ENERGY LIMITED ", quantity=5000,
                     unit="BBL", price_usd_bbl="80.01")
    with pytest.raises(ValueError, match="confirmation collision"):
        validate_dataset_safety([trade], [original, collision], [], settings)


@pytest.mark.parametrize("changed_field", ["side", "contract_month", "quantity", "price_usd_bbl"])
def test_final_validation_rejects_a_blank_unknown_near_match(changed_field):
    """Each permitted one-field difference remains a candidate despite an alias and equivalent units."""
    from src.generate import validate_dataset_safety

    settings = json.loads((ROOT / "settings.json").read_text())
    trade = {"trade_id": "T000001", "trade_date": "2026-10-01",
             "counterparty": "Kestrel Shoal Energy Ltd", "side": "BUY",
             "contract_month": "2026-12", "quantity": 5, "unit": "LOTS",
             "price_usd_bbl": "80.00"}
    original = dict(trade, confirm_id="C000001", trade_ref="T000001")
    orphan = dict(original, confirm_id="C000002", trade_ref="",
                  counterparty=" KESTREL SHOAL ENERGY LIMITED ", quantity=5000,
                  unit="BBL", price_usd_bbl="80.01")
    alternatives = {"side": "SELL", "contract_month": "2027-01",
                    "quantity": 10000, "price_usd_bbl": "80.02"}
    orphan[changed_field] = alternatives[changed_field]
    answers = [{"case_id": "CASE001", "trade_id": "", "confirm_id": "C000002",
                "case_type": "UNKNOWN_CONFIRMATION"}]
    with pytest.raises(ValueError, match="unknown confirmation.*desk candidate"):
        validate_dataset_safety([trade], [original, orphan], answers, settings)


def test_safety_validation_runs_before_dataset_files_are_written(tmp_path, monkeypatch):
    """The CLI generation path must call the final guard before publishing any dataset CSV."""
    from src import generate

    def reject_dataset(*args):
        """Stand in for a final validation failure to verify output ordering."""
        raise ValueError("validation rejected the candidate dataset")

    monkeypatch.setattr(generate, "validate_dataset_safety", reject_dataset)
    with pytest.raises(ValueError, match="validation rejected"):
        generate.generate_dataset(seed=1, output_root=tmp_path)
    assert not (tmp_path / "seed_1").exists()
