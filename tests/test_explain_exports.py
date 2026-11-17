"""Public explanation APIs preserve result rows, ordering and CSV data."""
import builtins
import copy
import csv
import io
import re
import socket
from decimal import Decimal

import pytest
from src.compare import RESULT_COLUMNS
from test_explain import real_run, explanation_module

ADDITIONS = ["friendly_name", "what_happened", "how_value_is_worked_out", "suggested_next_step"]
ITEM_KEYS = set(ADDITIONS + ["draft_query", "sum_shown", "sum_value", "displayed_operands"])


def mixed_run(make_trade, make_confirmation, settings):
    first = make_trade(identifier="T1")
    second = make_trade(identifier="T2", counterparty="Second Example Ltd")
    review1 = make_trade(identifier="TR1", counterparty="Review Entity")
    review2 = make_trade(identifier="TR2", counterparty="Review Entity")
    confirmations = [make_confirmation(first, identifier="C1", side="SELL"),
                     make_confirmation(second, identifier="C2", price_usd_bbl="81"),
                     make_confirmation(review1, identifier="CR1", trade_ref=""),
                     make_confirmation(review2, identifier="CR2", trade_ref="")]
    return real_run([first, second, review1, review2], confirmations, settings)


def test_public_apis_csv_original_fields_and_captions(make_trade, make_confirmation, engine_settings):
    run = mixed_run(make_trade, make_confirmation, engine_settings)
    before = copy.deepcopy(run)
    ex = explanation_module()
    items = ex.explain_all(run)
    assert len(ex.FRIENDLY_NAMES) == 9
    assert len(items) == len(run["results"]) == 3
    assert items == [ex.explain_result(r, run) for r in run["results"]]
    assert all(set(item) == ITEM_KEYS for item in items)
    assert ex.GUIDANCE_CAPTION == "General guidance only. Follow your own desk's procedure."
    assert ex.DRAFT_CAPTION == "Draft only. Nothing is sent by this tool."
    for item in items:
        assert ex.GUIDANCE_CAPTION not in item["suggested_next_step"]
        assert ex.DRAFT_CAPTION not in item["draft_query"]
    output = ex.report_csv(run)
    assert isinstance(output, bytes)
    reader = csv.DictReader(io.StringIO(output.decode("utf-8")))
    assert reader.fieldnames == RESULT_COLUMNS + ADDITIONS
    exported = list(reader)
    for result, item, row in zip(run["results"], items, exported):
        assert {key: row[key] for key in RESULT_COLUMNS} == result
        for key in ADDITIONS:
            assert row[key] == item[key] + (" " + ex.GUIDANCE_CAPTION if key == "suggested_next_step" else "")
        assert row["suggested_next_step"].count(ex.GUIDANCE_CAPTION) == 1
    assert exported[-1]["value_of_discrepancy_usd"] == ""
    assert run == before


def test_summary_uses_existing_first_three_without_reranking(make_trade, make_confirmation, engine_settings):
    run = mixed_run(make_trade, make_confirmation, engine_settings)
    ex = explanation_module()
    summary = ex.results_summary(run)
    assert set(summary) == {"text", "start_here"}
    assert summary["text"] == "3 items need attention: 1 high priority, 1 standard, 1 for manual review."
    assert summary["start_here"] == [
        "Buy/sell mismatch, trade T1, $800,000.00",
        "Price difference, trade T2, $5,000.00",
        "Needs manual review, trades TR1, TR2, confirmations CR1, CR2, No value shown",
    ]
    assert len(summary["start_here"]) == 3
    for row, text in zip(run["results"], summary["start_here"]):
        assert isinstance(text, str)
        assert ex.FRIENDLY_NAMES[row["break_type"]] in text
        assert row["trade_id"].replace(";", ", ") in text
        if row["break_type"] == "AMBIGUOUS":
            assert row["confirm_id"].replace(";", ", ") in text
        else:
            assert "confirmation" not in text.lower()
        if row["value_of_discrepancy_usd"]:
            assert f"${Decimal(row['value_of_discrepancy_usd']):,.2f}" in text
        else:
            assert "$0" not in text
            assert "No value" in text
    run["results"] = list(reversed(run["results"]))
    assert ex.results_summary(run)["start_here"] == list(reversed(summary["start_here"]))


@pytest.mark.parametrize("kind,expected", [
    ("missing", "Missing confirmation, trade T001, $400,000.00"),
    ("unknown", "Unknown confirmation, confirmation C001, $400,000.00"),
    ("duplicate", "Duplicate confirmation, trade T001, confirmations C1, C2, $400,000.00"),
    ("review", "Needs manual review, trades T1, T2, confirmations C1, C2, No value shown"),
])
def test_start_here_only_lists_applicable_identifiers(make_trade, make_confirmation, engine_settings, kind, expected):
    trade = make_trade()
    trades, confirmations = [trade], []
    if kind == "unknown":
        trades, confirmations = [], [make_confirmation(trade, trade_ref="")]
    elif kind == "duplicate":
        confirmations = [make_confirmation(trade, identifier="C1"), make_confirmation(trade, identifier="C2")]
    elif kind == "review":
        trades = [make_trade(identifier="T1"), make_trade(identifier="T2")]
        confirmations = [make_confirmation(trades[0], identifier="C1", trade_ref=""),
                         make_confirmation(trades[1], identifier="C2", trade_ref="")]
    run = real_run(trades, confirmations, engine_settings)
    assert len(run["results"]) == 1
    assert explanation_module().results_summary(run)["start_here"] == [expected]
    assert "(none listed)" not in expected


def test_clean_summary_and_empty_csv_headers(make_trade, make_confirmation, engine_settings):
    trade = make_trade()
    run = real_run([trade], [make_confirmation(trade)], engine_settings)
    ex = explanation_module()
    assert ex.results_summary(run) == {"text": "All 1 trades agree with the broker's confirmations. Nothing to chase.", "start_here": []}
    assert ex.explain_all(run) == []
    assert list(csv.reader(io.StringIO(ex.report_csv(run).decode()))) == [RESULT_COLUMNS + ADDITIONS]


def test_reading_guide_explains_different_bases_blank_review_and_not_a_loss():
    guide = explanation_module().reading_guide()
    assert isinstance(guide, str)
    for word in ["break", "different sums", "blank", "not zero", "not a loss", "desk", "lots", "barrels", "guidance", "not sent", "this tool"]:
        assert word in guide.lower()
    assert "the engine" not in guide.lower()
    assert guide.splitlines() == [
        "- A break is a difference or item that needs checking.",
        "- Value of discrepancy is not a loss or an amount owed.",
        "- Different break types use different sums. Read each explanation.",
        "- A blank value means pairing needs manual review, not zero.",
        "- Bought/sold describe the desk's direction; lots also show barrels.",
        "- Suggested steps are general guidance; drafts are not sent by this tool.",
    ]
    assert len(guide.split()) <= 140
    assert all(len(line.split()) <= 25 for line in guide.splitlines())


def test_runtime_no_file_reads_no_network_no_input_mutation(make_trade, make_confirmation, engine_settings, monkeypatch):
    run = mixed_run(make_trade, make_confirmation, engine_settings)
    ex = explanation_module()
    before = copy.deepcopy(run)
    def forbidden(*args, **kwargs):
        raise AssertionError("Runtime explanations must not read files or use the network")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(io, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    items = ex.explain_all(run)
    ex.report_csv(run)
    ex.results_summary(run)
    ex.reading_guide()
    for item in items:
        for key in ADDITIONS + ["draft_query"]:
            assert not re.search(r"\b(loss|cost|P&L)\b|the engine|Everything else agrees", item[key], re.I)
    assert run == before
