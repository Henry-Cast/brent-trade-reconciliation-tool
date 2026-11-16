"""Independently check tradability and front-month pricing, using development seeds only."""
import csv
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OCTOBER_MONTHS = {"2026-12", "2027-01", "2027-02"}


def read_rows(path):
    """Read delivered CSV strings rather than infer success from generator labels."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_clean_october_uses_front_and_next_two_contracts(tmp_path):
    """October's clean trades use December, January and February, never expired November."""
    from src.generate import generate_dataset
    folder = generate_dataset(seed=1, clean=True, output_root=tmp_path)
    blotter = read_rows(folder / "blotter.csv")
    confirmations = read_rows(folder / "confirmations.csv")
    assert {row["contract_month"] for row in blotter} == OCTOBER_MONTHS
    assert {row["contract_month"] for row in confirmations} == OCTOBER_MONTHS


def test_clean_prices_count_adjustment_from_front_month(tmp_path):
    """December has zero month adjustment; January and February use one and two configured steps."""
    from src.generate import generate_dataset
    folder = generate_dataset(seed=1, clean=True, output_root=tmp_path)
    spots = {row["trade_date"]: Decimal(row["spot_price_usd_bbl"])
             for row in read_rows(ROOT / "data/brent_spot.csv")}
    rank = {"2026-12": 0, "2027-01": 1, "2027-02": 2}
    for row in read_rows(folder / "blotter.csv"):
        residual = Decimal(row["price_usd_bbl"]) - spots[row["trade_date"]] - Decimal("-0.15") * rank[row["contract_month"]]
        assert Decimal("-0.10") <= residual <= Decimal("0.10"), row


def test_planted_month_breaks_and_unknowns_stay_in_tradable_months(tmp_path):
    """A planted month disagreement stays real, but neither side uses an expired or out-of-set month."""
    from src.generate import generate_dataset
    folder = generate_dataset(seed=1, output_root=tmp_path)
    blotter = read_rows(folder / "blotter.csv")
    confirmations = read_rows(folder / "confirmations.csv")
    answers = read_rows(folder / "answer_key.csv")
    assert {row["contract_month"] for row in blotter + confirmations} == OCTOBER_MONTHS
    trades = {row["trade_id"]: row for row in blotter}
    confirms = {row["confirm_id"]: row for row in confirmations}
    cases = [row for row in answers if row["case_type"] == "CONTRACT_MONTH"]
    assert len(cases) == 4
    for case in cases:
        assert trades[case["trade_id"]]["contract_month"] != confirms[case["confirm_id"]]["contract_month"]
    unknowns = [confirms[row["confirm_id"]] for row in answers if row["case_type"] == "UNKNOWN_CONFIRMATION"]
    assert len(unknowns) == 3
    assert all(row["contract_month"] in OCTOBER_MONTHS for row in unknowns)


@pytest.mark.parametrize("side", ["blotter", "confirmations"])
@pytest.mark.parametrize("month", ["2026-11", "2027-03"])
def test_final_guard_rejects_out_of_universe_months(tmp_path, side, month):
    """Both delivered sides are checked after mutations, including expired and unexpired out-of-set months."""
    import json
    from src.generate import DatasetSafetyError, generate_dataset, validate_dataset_safety
    folder = generate_dataset(seed=1, clean=True, output_root=tmp_path)
    blotter = read_rows(folder / "blotter.csv")
    confirmations = read_rows(folder / "confirmations.csv")
    records = blotter if side == "blotter" else confirmations
    records[0]["contract_month"] = month
    settings = json.loads((ROOT / "settings.json").read_text())
    with pytest.raises(DatasetSafetyError, match="tradable"):
        validate_dataset_safety(blotter, confirmations, [], settings)


@pytest.mark.parametrize("trade_date,expected", [
    ("2026-09-30", ["2026-11", "2026-12", "2027-01"]),
    ("2026-10-01", ["2026-12", "2027-01", "2027-02"]),
    ("2026-10-30", ["2026-12", "2027-01", "2027-02"]),
    ("2026-11-02", ["2027-01", "2027-02", "2027-03"]),
    ("2026-11-30", ["2027-01", "2027-02", "2027-03"]),
    ("2026-12-01", ["2027-02", "2027-03", "2027-04"]),
    ("2026-12-30", ["2027-02", "2027-03", "2027-04"]),
    ("2026-12-31", ["2027-03", "2027-04", "2027-05"]),
])
def test_front_roll_and_holiday_exception_use_published_ice_dates(trade_date, expected):
    """Expiry dates remain eligible before cutoff; the next date rolls, including December's holiday exception."""
    from src.generate import tradable_contract_months
    assert tradable_contract_months(trade_date) == expected


@pytest.mark.parametrize("trade_date", ["2026-08-31", "2027-01-01"])
def test_unverified_trade_dates_stop_instead_of_guessing(trade_date):
    """Calendar coverage is explicit; the generator must not invent future or earlier expiry dates."""
    from src.generate import tradable_contract_months
    with pytest.raises(ValueError, match="No verified ICE expiry-calendar coverage"):
        tradable_contract_months(trade_date)


@pytest.mark.parametrize("missing", ["2026-12", "2027-01"])
def test_missing_verified_contract_cannot_silently_skip_a_month(missing):
    """Removing the front or next month is detected rather than replacing it with a later one."""
    from src.generate import load_expiry_calendar, tradable_contract_months
    calendar = load_expiry_calendar()
    calendar["contracts"] = [row for row in calendar["contracts"] if row["contract_month"] != missing]
    with pytest.raises(ValueError, match="verified ICE calendar"):
        tradable_contract_months("2026-10-01", calendar)


def test_local_calendar_matches_retained_ice_reference_dates():
    """Pin the official reference dates independently of the selection algorithm."""
    from src.generate import load_expiry_calendar
    calendar = load_expiry_calendar()
    actual = {row["contract_month"]: row["last_trade_date"] for row in calendar["contracts"]}
    assert actual == {"2026-11": "2026-09-30", "2026-12": "2026-10-30", "2027-01": "2026-11-30",
                      "2027-02": "2026-12-30", "2027-03": "2027-01-29", "2027-04": "2027-02-26",
                      "2027-05": "2027-03-31"}
    assert "before" in calendar["date_only_assumption"] and "cutoff" in calendar["date_only_assumption"]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_all_delivered_rows_are_unexpired_after_planting(tmp_path, seed):
    """Audit both full delivered files against independent ICE date expectations, not answer-key labels."""
    from src.generate import generate_dataset
    folder = generate_dataset(seed=seed, output_root=tmp_path)
    expiry = {"2026-12": "2026-10-30", "2027-01": "2026-11-30", "2027-02": "2026-12-30"}
    for filename in ["blotter.csv", "confirmations.csv"]:
        for row in read_rows(folder / filename):
            assert row["contract_month"] in expiry
            assert row["trade_date"] <= expiry[row["contract_month"]], row


def test_isolated_app_generation_has_a_private_expiry_calendar():
    """The unchanged app generator process receives its own verified calendar as well as price inputs."""
    import app_support
    calendar_path = ROOT / "data/ice_brent_expiry_calendar.json"
    before = (calendar_path.read_bytes(), calendar_path.stat().st_mtime_ns)
    with app_support.create_workspace() as workspace:
        run = app_support.run_generated(Path(workspace), 1)
        private = Path(run["folder"]).parents[1] / "data/ice_brent_expiry_calendar.json"
        assert private.read_bytes() == before[0]
        assert {row["contract_month"] for row in run["blotter"] + run["confirmations"]} == OCTOBER_MONTHS
    assert (calendar_path.read_bytes(), calendar_path.stat().st_mtime_ns) == before


def test_hash_command_checks_only_the_five_protected_sources(tmp_path):
    """Public references stay immutable; a fresh checkout checks exactly five sources against both baselines."""
    import hashlib
    import json
    import shutil
    import subprocess
    import sys

    fixtures = Path("tests/fixtures/hash_references")
    references = [ROOT / fixtures / name for name in
                  ["engine_before.json", "hardening_frozen_source.json", "stage3_frozen_before.json"]]
    snapshots = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in references}
    provenance = json.loads((ROOT / fixtures / "provenance.json").read_text())
    for record in provenance["references"]:
        assert hashlib.sha256((ROOT / record["public"]).read_bytes()).hexdigest() == record["public_sha256"]
    # Pin the full original stage-3 snapshot, including generator/settings/test hashes.
    assert snapshots[references[2]] == "c015b2985e62edf87bfff723bb73923209d68beb563321d9df9ae9e2e917cbb7"
    protected = {"src/normalise.py", "src/match.py", "src/compare.py",
                 "src/reconcile.py", "src/scorecard.py"}
    for name in protected | {"scripts/check_stage3_hashes.py"}:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    shutil.copytree(ROOT / fixtures, tmp_path / fixtures)
    # Generator content must not become an extra protected input.
    (tmp_path / "src/generate.py").write_text("deliberately not the historical generator\n")
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "archive").exists()

    def run_check():
        """Run the real CLI in the publication-shaped workspace."""
        return subprocess.run([sys.executable, str(tmp_path / "scripts/check_stage3_hashes.py")],
                              cwd=tmp_path, capture_output=True, text=True)

    result = run_check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "5/5" in result.stdout
    assert "src/generate.py" not in result.stdout
    output = tmp_path / "reports/expiry_realism/hash_check.txt"
    assert output.is_file()
    assert output.read_text() == result.stdout
    rows = json.loads(output.with_suffix(".json").read_text())
    assert {row["file"] for row in rows} == protected
    assert len(rows) == 5 and all(row["unchanged"] for row in rows)

    # Each baseline is independently required: missing/extra keys cannot pass,
    # and a changed value in either one must produce a real hash mismatch.
    for reference in references[:2]:
        target = tmp_path / fixtures / reference.name
        original = target.read_bytes()
        for defect in ["missing", "extra", "changed"]:
            document = json.loads(original)
            mapping = document["frozen_source"] if "frozen_source" in document else document
            assert set(mapping) == protected
            if defect == "missing":
                del mapping["src/normalise.py"]
            elif defect == "extra":
                mapping["src/generate.py"] = "0" * 64
            else:
                mapping["src/normalise.py"] = "0" * 64
            target.write_text(json.dumps(document))
            tampered = target.read_bytes()
            failure = run_check()
            assert failure.returncode == (1 if defect == "changed" else 2)
            assert ("CHANGED src/normalise.py" if defect == "changed" else
                    "exactly the five agreed files") in failure.stdout
            assert target.read_bytes() == tampered
            target.write_bytes(original)

    source = tmp_path / "src/normalise.py"
    source.write_bytes(source.read_bytes() + b"\n# deliberate protected-source mutation\n")
    failure = run_check()
    assert failure.returncode == 1
    assert "CHANGED src/normalise.py" in failure.stdout
    for path, expected in snapshots.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        assert hashlib.sha256((tmp_path / fixtures / path.name).read_bytes()).hexdigest() == expected
