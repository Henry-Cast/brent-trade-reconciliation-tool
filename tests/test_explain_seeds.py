"""Development-seed audit: actual protected file pipeline, never held-out seeds."""
from collections import Counter
import copy
import csv
import io
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest
from src import generate, reconcile
from test_explain import real_run, explanation_module, assert_checked


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_every_printed_sum_checked_against_actual_protected_output(seed, tmp_path, engine_settings):
    root = Path(__file__).resolve().parents[1]
    # pytest must use our private project-contained basetemp, never a system folder.
    tmp_path.resolve().relative_to(root)
    folder = generate.generate_dataset(seed=seed, output_root=tmp_path / "generated")
    with (folder / "blotter.csv").open(newline="", encoding="utf-8") as handle:
        trades = list(csv.DictReader(handle))
    with (folder / "confirmations.csv").open(newline="", encoding="utf-8") as handle:
        confirmations = list(csv.DictReader(handle))
    result_file, matches_file = folder / "results.csv", folder / "matches.csv"
    reconcile.reconcile_files(folder / "blotter.csv", folder / "confirmations.csv", result_file, matches_file)
    with result_file.open(newline="", encoding="utf-8") as handle:
        authoritative = list(csv.DictReader(handle))
    run = real_run(trades, confirmations, engine_settings)
    assert run["results"] == authoritative
    before = copy.deepcopy(run)
    ex = explanation_module()
    items = ex.explain_all(run)
    assert set(r["break_type"] for r in authoritative) == set(ex.FRIENDLY_NAMES)
    for result, item in zip(authoritative, items):
        if result["break_type"] == "AMBIGUOUS":
            assert item["sum_shown"] is False and item["sum_value"] == ""
        else:
            assert_checked(item, result)
            # Independently parse the formula itself, not just returned metadata.
            printed = item["how_value_is_worked_out"].split(" = ")[0]
            factors = [Decimal(part.replace("$", "").replace(",", ""))
                       for part in printed.replace(" per barrel", "").replace(" barrels", "").replace(" x ", " × ").split(" × ")]
            product = Decimal(1)
            for factor in factors:
                product *= factor
            assert format(product.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f") == result["value_of_discrepancy_usd"]
        for key in ["what_happened", "how_value_is_worked_out", "suggested_next_step", "draft_query"]:
            assert not re.search(r"\b(loss|cost|P&L)\b|the engine|everything else agrees", item[key], re.I)
        assert ex.GUIDANCE_CAPTION not in item["suggested_next_step"]
        assert ex.DRAFT_CAPTION not in item["draft_query"]
    exported = list(csv.DictReader(io.StringIO(ex.report_csv(run).decode("utf-8"))))
    assert len(exported) == len(authoritative)
    assert ex.results_summary(run)["start_here"] == ex.results_summary(dict(run, results=authoritative[:3]))["start_here"]
    if seed == 1:
        assert sum(Decimal(r["value_of_discrepancy_usd"] or "0") for r in authoritative) == Decimal("230241854.20")
        assert Counter(r["break_type"] for r in authoritative) == {
            "PRICE": 6, "QUANTITY": 5, "SIDE": 3, "CONTRACT_MONTH": 4, "UNIT_ERROR": 2,
            "MISSING_CONFIRMATION": 4, "UNKNOWN_CONFIRMATION": 3, "DUPLICATE": 3, "AMBIGUOUS": 2}
    assert run == before
