"""Exercise the command a user will actually run."""
from pathlib import Path
import json
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_cli_writes_separate_folders_and_reports_measured_counts():
    """Seed 2 and clean mode must not change the seed 1 files."""
    for options, subfolder in [(["--seed", "1"], "seed_1"),
                               (["--seed", "2"], "seed_2"),
                               (["--seed", "1", "--clean"], "clean")]:
        result = subprocess.run([sys.executable, "src/generate.py"] + options,
                                cwd=ROOT, text=True, capture_output=True, check=True)
        report = json.loads(result.stdout)
        folder = ROOT / "data/generated" / subfolder
        b = pd.read_csv(folder / "blotter.csv")
        c = pd.read_csv(folder / "confirmations.csv")
        a = pd.read_csv(folder / "answer_key.csv")
        assert report["blotter_rows"] == len(b)
        assert report["confirmation_rows"] == len(c)
        assert report["answer_key_rows"] == len(a)
        assert report["case_counts"] == a.drop_duplicates("case_id").case_type.value_counts().to_dict()
        if subfolder == "seed_1":
            snapshot = {p.name: p.read_bytes() for p in folder.glob("*.csv")}
    for name, contents in snapshot.items():
        assert (ROOT / "data/generated/seed_1" / name).read_bytes() == contents


def test_settings_hold_the_shared_tolerances():
    """Keep price and volume rules in one settings file for subsequent stages."""
    settings = json.loads((ROOT / "settings.json").read_text())
    assert settings["price_tolerance_usd_bbl"] == "0.01"
    assert settings["volume_tolerance_bbl"] == 0
    assert settings["barrels_per_lot"] == 1000
