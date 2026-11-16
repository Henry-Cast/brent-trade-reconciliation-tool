"""Run the frozen generator with private file paths in a separate Python process."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    """Redirect only this child process's generator root; never alter shared module state."""
    try:
        if len(sys.argv) != 3:
            raise ValueError("Supply a private runtime folder and an integer seed.")
        folder = Path(sys.argv[1]).resolve()
        relative = folder.relative_to(ROOT)
        if not relative.parts or relative.parts[0] not in {".app_sessions", ".cache"}:
            raise ValueError("Generation requires a private temporary folder inside this project.")
        seed = int(sys.argv[2])
        from src import generate
        # The child reads its private CSV snapshot, calendar and settings.
        # A separate process makes this path configuration private to one run.
        # Its sampling, validation, retries, settings and pricing logic are unchanged.
        generate.ROOT = folder
        dataset = generate.generate_dataset(seed=seed, output_root=folder / "generated")
        print(json.dumps({"folder": str(dataset)}))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
