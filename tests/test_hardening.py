"""Generator hardening constraints; development datasets are strictly seeds 1–5."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import hashlib
import json

import pytest

from test_matching_safety import candidate_kind, read_rows
import re


def generic_name(name):
    """Independently implement the general transformations used by these fictional names."""
    words = re.sub(r"[^\w\s]", " ", name.upper()).split()
    if words and words[-1] == "LIMITED":
        words[-1] = "LTD"
    return " ".join(words)

ROOT = Path(__file__).resolve().parents[1]
NEAR_COUNTS = {"PRICE": 2, "QUANTITY": 1, "SIDE": 1, "CONTRACT_MONTH": 1}


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_five_breaks_have_no_reference_and_one_intended_near_candidate(tmp_path, seed):
    """The five chosen breaks have no exact candidate and exactly their intended rule-4 candidate."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=seed, output_root=tmp_path)
    blotter = read_rows(folder, "blotter.csv")
    confirmations = {row["confirm_id"]: row for row in read_rows(folder, "confirmations.csv")}
    answers = read_rows(folder, "answer_key.csv")
    settings = json.loads((ROOT / "settings.json").read_text())
    assert all("expected_matching_rule" in row for row in answers)
    chosen = [row for row in answers if row["expected_matching_rule"] == "RULE_4_NEAR_MATCH"]
    assert Counter(row["case_type"] for row in chosen) == NEAR_COUNTS
    for answer in chosen:
        confirm = confirmations[answer["confirm_id"]]
        assert confirm["trade_ref"] == ""
        exact = [trade["trade_id"] for trade in blotter if candidate_kind(confirm, trade, settings) == 0]
        near = [trade["trade_id"] for trade in blotter if candidate_kind(confirm, trade, settings) == 1]
        assert exact == []
        assert near == [answer["trade_id"]]
    for answer in answers:
        rule = answer["expected_matching_rule"]
        if answer["case_type"] in {"MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION", "AMBIGUOUS"}:
            assert rule == ""
        elif answer["case_type"] == "MISSING_TRADE_REF":
            assert rule == "RULE_3_ATTRIBUTES"
        elif answer not in chosen:
            assert rule == "RULE_2_REFERENCE"


def test_engine_and_scorer_sources_remain_frozen():
    """The hardening round may change fixtures and aliases, not engine or scorer code."""
    frozen = json.loads((ROOT / "tests/fixtures/hash_references/hardening_frozen_source.json").read_text())["frozen_source"]
    assert set(frozen) == {"src/normalise.py", "src/match.py", "src/compare.py",
                           "src/reconcile.py", "src/scorecard.py"}
    for name, expected in frozen.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name


@pytest.mark.parametrize("defect", ["another_near", "an_exact", "restored_reference", "wrong_annotation"])
def test_final_guard_rejects_invalid_near_case_constraints(tmp_path, defect):
    """The final pre-write guard rechecks uniqueness, blank references, and the required type counts."""
    from src.generate import generate_dataset, validate_dataset_safety

    folder = generate_dataset(seed=1, output_root=tmp_path)
    blotter = read_rows(folder, "blotter.csv")
    confirmations = read_rows(folder, "confirmations.csv")
    answers = read_rows(folder, "answer_key.csv")
    settings = json.loads((ROOT / "settings.json").read_text())
    chosen = next(row for row in answers if row["expected_matching_rule"] == "RULE_4_NEAR_MATCH")
    confirmation = next(row for row in confirmations if row["confirm_id"] == chosen["confirm_id"])
    if defect == "another_near":
        extra = dict(next(row for row in blotter if row["trade_id"] == chosen["trade_id"]))
        extra["trade_id"] = "T999999"
        blotter.append(extra)
    elif defect == "an_exact":
        extra = {key: value for key, value in confirmation.items() if key not in {"confirm_id", "trade_ref"}}
        extra["trade_id"] = "T999999"
        blotter.append(extra)
    elif defect == "restored_reference":
        confirmation["trade_ref"] = chosen["trade_id"]
    else:
        chosen["expected_matching_rule"] = "RULE_2_REFERENCE"
    with pytest.raises(ValueError, match="near"):
        validate_dataset_safety(blotter, confirmations, answers, settings)


def test_safety_rejection_is_recorded_and_reproducible(tmp_path, monkeypatch):
    """A bounded safety retry is logged; the engine and scorecard never select acceptable data."""
    from src import generate

    original = generate.validate_dataset_safety
    calls = []
    active_root = [tmp_path / "first"]

    def reject_first(*args):
        """Simulate one explicit safety failure before allowing the normal checks."""
        calls.append(True)
        if len(calls) == 1:
            assert not (active_root[0] / "seed_1").exists()
            raise generate.DatasetSafetyError("deliberate fixture safety rejection")
        return original(*args)

    monkeypatch.setattr(generate, "validate_dataset_safety", reject_first)
    folder = generate.generate_dataset(seed=1, output_root=active_root[0])
    metadata = json.loads((folder / "generation_metadata.json").read_text())
    assert metadata["generation_attempts"] >= 2
    assert metadata["safety_rejections"][0] == {"attempt": 1, "reason": "deliberate fixture safety rejection"}
    assert len(metadata["safety_rejections"]) == metadata["generation_attempts"] - 1
    calls.clear()
    active_root[0] = tmp_path / "second"
    repeated = generate.generate_dataset(seed=1, output_root=active_root[0])
    assert (folder / "generation_metadata.json").read_bytes() == (repeated / "generation_metadata.json").read_bytes()
    for filename in ["blotter.csv", "confirmations.csv", "answer_key.csv"]:
        assert (folder / filename).read_bytes() == (repeated / filename).read_bytes()


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_name_traps_split_between_general_rules_and_required_aliases(tmp_path, seed):
    """Two variants are general equivalents; two require explicit nontrivial manual mappings."""
    from src.generate import generate_dataset

    folder = generate_dataset(seed=seed, output_root=tmp_path)
    b = {row["trade_id"]: row for row in read_rows(folder, "blotter.csv")}
    c = {row["confirm_id"]: row for row in read_rows(folder, "confirmations.csv")}
    answers = read_rows(folder, "answer_key.csv")
    settings = json.loads((ROOT / "settings.json").read_text())
    aliases = {generic_name(source): generic_name(target)
               for source, target in settings["counterparty_aliases"].items()}
    methods = Counter()
    for answer in answers:
        if answer["case_type"] != "COUNTERPARTY_VARIANT":
            continue
        left, right = b[answer["trade_id"]]["counterparty"], c[answer["confirm_id"]]["counterparty"]
        assert left != right
        generic_left, generic_right = generic_name(left), generic_name(right)
        if generic_left == generic_right:
            methods["GENERAL_RULES"] += 1
        else:
            assert generic_right in aliases
            assert aliases[generic_right] == generic_left
            assert generic_left != generic_right
            methods["ALIAS_TABLE"] += 1
    assert methods == {"GENERAL_RULES": 2, "ALIAS_TABLE": 2}


def test_final_guard_rejects_a_name_trap_without_its_required_alias(tmp_path):
    """Removing a required mapping cannot silently leave a labelled harmless name unresolved."""
    from src.generate import generate_dataset, validate_dataset_safety

    folder = generate_dataset(seed=1, output_root=tmp_path)
    blotter = read_rows(folder, "blotter.csv")
    confirmations = read_rows(folder, "confirmations.csv")
    answers = read_rows(folder, "answer_key.csv")
    settings = json.loads((ROOT / "settings.json").read_text())
    settings["counterparty_aliases"] = {}
    with pytest.raises(ValueError, match="variant"):
        validate_dataset_safety(blotter, confirmations, answers, settings)
