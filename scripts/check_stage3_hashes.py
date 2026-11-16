"""Check the five protected engine/scorer sources after approved generator corrections."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_FILES = ["src/normalise.py", "src/match.py", "src/compare.py",
                   "src/reconcile.py", "src/scorecard.py"]


def main():
    """Compare real hashes with both original references, without rewriting historical snapshots."""
    references = ROOT / "tests/fixtures/hash_references"
    before = json.loads((references / "engine_before.json").read_text())
    historic = json.loads((references / "hardening_frozen_source.json").read_text())["frozen_source"]
    if set(before) != set(PROTECTED_FILES) or set(historic) != set(PROTECTED_FILES):
        print("The protected-source references must contain exactly the five agreed files.")
        return 2
    rows = []
    lines = []
    for name in PROTECTED_FILES:
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        unchanged = actual == before[name] == historic[name]
        rows.append({"file": name, "before": before[name], "after": actual,
                     "historic_reference": historic[name], "unchanged": unchanged})
        lines.extend([f"{'OK' if unchanged else 'CHANGED'} {name}",
                      f"  before: {before[name]}", f"  after:  {actual}"])
    matches = sum(row["unchanged"] for row in rows)
    lines.append(f"Protected engine/scorer files unchanged: {matches == len(PROTECTED_FILES)} ({matches}/5).")
    text = "\n".join(lines) + "\n"
    folder = ROOT / "reports/expiry_realism"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "hash_check.txt").write_text(text)
    (folder / "hash_check.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(text, end="")
    return 0 if matches == len(PROTECTED_FILES) else 1


if __name__ == "__main__":
    sys.exit(main())
