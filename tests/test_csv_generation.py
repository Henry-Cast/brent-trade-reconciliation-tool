"""CSV-only generator and child launcher regressions, using development seed 1 only."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import app_support as app
import pytest

from src import generate, reconcile

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ["data/brent_spot.csv", "data/ice_brent_expiry_calendar.json", "settings.json"]
SEED1_HASHES = {
    "blotter.csv": "4f29efb03f34dbcd4a12de840c72e93abb752851a0a2d883aec5438e204b4903",
    "confirmations.csv": "4a6c01737ee841d4de192a8d6991e2d22aefb7097fd1097a481ad588746e9446",
    "answer_key.csv": "e3ca0f9fbeaa12bac71d610b7356ba20447bc72a2a59a51863fa99d390599c48",
    "generation_metadata.json": "6e13b297ab369a50351ff80aaa76867a12f34d7d61f39691b50d72707bdce510",
}


def copy_csv_inputs(folder):
    """Create only the public CSV, expiry calendar and settings required by generation."""
    for name in INPUTS:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)


def test_generator_uses_only_csv_without_mutating_inputs(tmp_path, monkeypatch):
    """The CSV alone reproduces the existing seed-1 bytes and exact discrepancy valuation."""
    copy_csv_inputs(tmp_path)
    before = {name: ((tmp_path / name).read_bytes(), (tmp_path / name).stat().st_mtime_ns)
              for name in INPUTS}
    monkeypatch.setattr(generate, "ROOT", tmp_path)
    folder = generate.generate_dataset(seed=1, output_root=tmp_path / "generated")
    for name, expected in SEED1_HASHES.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected
    reconcile.reconcile_files(folder / "blotter.csv", folder / "confirmations.csv",
                              folder / "results.csv", folder / "matches.csv")
    with (folder / "results.csv").open(newline="") as handle:
        total = sum((Decimal(row["value_of_discrepancy_usd"] or "0")
                     for row in csv.DictReader(handle)), Decimal("0"))
    assert total == Decimal("230241854.20")
    for name, expected in before.items():
        assert ((tmp_path / name).read_bytes(), (tmp_path / name).stat().st_mtime_ns) == expected


def test_generator_requires_csv_before_creating_outputs(tmp_path, monkeypatch):
    """Missing market prices cannot be silently regenerated from another source."""
    monkeypatch.setattr(generate, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError) as caught:
        generate.generate_dataset(seed=1, output_root=tmp_path / "generated")
    assert Path(caught.value.filename) == tmp_path / "data/brent_spot.csv"
    assert not (tmp_path / "generated").exists()


@pytest.mark.parametrize("csv_present", [True, False], ids=["csv-only", "missing-private-csv"])
def test_child_launcher_requires_its_private_csv_snapshot(csv_present):
    """A real launcher consumes private inputs only, never falling back to the shared source CSV."""
    with app.create_workspace(ROOT / ".cache") as workspace:
        private = Path(workspace)
        copy_csv_inputs(private)
        if not csv_present:
            (private / "data/brent_spot.csv").unlink()
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in private.rglob("*") if path.is_file()}
        process = subprocess.run([sys.executable, str(ROOT / "scripts/generate_for_app.py"),
                                  str(private), "1"], cwd=str(ROOT), capture_output=True,
                                 text=True, timeout=120, check=False)
        message = json.loads(process.stdout)
        assert not process.stderr
        if csv_present:
            assert process.returncode == 0, message
            folder = Path(message["folder"])
            assert folder == private / "generated/seed_1"
            for name, expected in SEED1_HASHES.items():
                assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected
        else:
            assert process.returncode == 1
            assert str(private / "data/brent_spot.csv") in message["error"]
            assert not (private / "generated").exists()
        for path, expected in before.items():
            assert (path.read_bytes(), path.stat().st_mtime_ns) == expected
