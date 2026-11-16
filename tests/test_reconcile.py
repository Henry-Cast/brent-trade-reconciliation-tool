"""Real command-line execution and proof that the engine cannot consult labels."""
from pathlib import Path
import csv
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def write_records(path, records):
    """Write hand-built CSV fixtures, retaining exact textual prices."""
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def test_real_cli_writes_results_and_complete_pair_audit(tmp_path, make_trade, make_confirmation):
    """The documented command must produce both requested artifacts from explicit inputs."""
    trade = make_trade()
    write_records(tmp_path / "blotter.csv", [trade])
    write_records(tmp_path / "confirmations.csv", [make_confirmation(trade, price_usd_bbl="80.05")])
    result = subprocess.run([sys.executable, "src/reconcile.py", "--blotter", str(tmp_path / "blotter.csv"),
                             "--confirmations", str(tmp_path / "confirmations.csv"),
                             "--results", str(tmp_path / "results.csv"), "--matches", str(tmp_path / "matches.csv")],
                            cwd=ROOT, text=True, capture_output=True, check=True)
    summary = json.loads(result.stdout)
    assert summary["result_rows"] == 1 and summary["matched_pairs"] == 1
    with (tmp_path / "results.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["break_type"] == "PRICE" and rows[0]["value_of_discrepancy_usd"] == "250.00"
    assert (tmp_path / "matches.csv").is_file()


def test_engine_never_reads_answer_key_even_when_present(tmp_path):
    """Audit every open call, prove the trap works, and compare malformed/changed/absent-key runs."""
    import shutil

    for name in ["blotter.csv", "confirmations.csv"]:
        shutil.copyfile(ROOT / "data/generated/seed_1" / name, tmp_path / name)
    script = r'''
import json, pathlib, runpy, sys
root, folder = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
attempts = []
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = pathlib.Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
        if path.resolve().name == "answer_key.csv":
            attempts.append(str(path))
            raise PermissionError("answer key access forbidden")
sys.addaudithook(audit)
try:
    (folder / "answer_key.csv").read_text()
except PermissionError:
    pass
assert len(attempts) == 1, "the audit guard was not exercised"
attempts.clear()
sys.argv = [str(root / "src/reconcile.py"), "--blotter", str(folder / "blotter.csv"),
            "--confirmations", str(folder / "confirmations.csv"),
            "--results", str(folder / "results.csv"), "--matches", str(folder / "matches.csv")]
runpy.run_path(sys.argv[0], run_name="__main__")
assert not attempts, attempts
assert "src.scorecard" not in sys.modules and "src.generate" not in sys.modules
print(json.dumps({"guard_probe_blocked": True, "engine_answer_key_reads": len(attempts)}))
'''
    outputs = []
    for contents in ["deliberately invalid CSV", "different answers must not affect the engine", None]:
        key = tmp_path / "answer_key.csv"
        if contents is None:
            key.unlink()
        else:
            key.write_text(contents)
        result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path)],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        probe = json.loads(result.stdout.splitlines()[-1])
        assert probe == {"guard_probe_blocked": True, "engine_answer_key_reads": 0}
        outputs.append({name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                        for name in ["results.csv", "matches.csv"]})
    assert outputs[0] == outputs[1] == outputs[2]
