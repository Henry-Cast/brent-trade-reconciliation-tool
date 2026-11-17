"""Independent review regressions for measured headlines and upload price scale."""
from copy import deepcopy
import csv
import io

import pytest

import app_support as app
from src import scorecard


def test_headline_counts_real_mislabelled_output_once():
    """The real scorer counts a wrong label within missed, not as another case."""
    answers = [
        {"case_id": "wrong", "case_type": "PRICE", "trade_id": "T1",
         "confirm_id": "C1", "expected_outcome": "BREAK"},
        {"case_id": "found", "case_type": "SIDE", "trade_id": "T2",
         "confirm_id": "C2", "expected_outcome": "BREAK"},
        {"case_id": "absent", "case_type": "CONTRACT_MONTH", "trade_id": "T3",
         "confirm_id": "C3", "expected_outcome": "BREAK"},
        {"case_id": "quiet", "case_type": "ROUNDING", "trade_id": "T4",
         "confirm_id": "C4", "expected_outcome": "NO_BREAK"},
    ]
    results = [
        {"break_type": "QUANTITY", "trade_id": "T1", "confirm_id": "C1"},
        {"break_type": "SIDE", "trade_id": "T2", "confirm_id": "C2"},
    ]
    scores, details = scorecard.score_records(results, answers, [])
    price = scores.set_index("case_type").loc["PRICE"]
    assert price[["found", "missed", "mislabelled"]].tolist() == [0, 1, 1]
    assert details["status"].tolist() == ["MISSED", "FOUND", "MISSED", "CORRECTLY_QUIET", "FALSE_ALARM"]
    measured = {"scores": list(csv.DictReader(io.StringIO(scores.to_csv(index=False))))}
    original = deepcopy(measured)
    assert app.scorecard_headline(measured) == (
        "Found 1 of 3 planted cases. 2 missed, 1 false alarms, 1 incorrectly labelled. "
        "1 harmless differences correctly left alone.")
    assert measured == original


def _upload(rows):
    """Encode raw test rows without normalising their price strings."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


@pytest.mark.parametrize("role", ["blotter", "confirmations"])
@pytest.mark.parametrize("price", [
    "80.1234567", "80.0000000", "8.01234567e1", "1e-7", "800000000e-7",
], ids=["seven-places", "seven-trailing-zero-places", "scientific-seven-places",
        "scientific-small", "scientific-trailing-zero-places"])
def test_upload_rejects_more_than_six_price_places(make_trade, make_confirmation, role, price):
    """Reject excess supplied decimal scale, including scientific notation."""
    first = make_trade(identifier="T1")
    second = make_trade(identifier="T2", price_usd_bbl=price)
    rows = [first, second] if role == "blotter" else [
        make_confirmation(first, identifier="C1"), make_confirmation(second, identifier="C2")]
    original = deepcopy(rows)
    with pytest.raises(app.AppInputError) as caught:
        app.validate_upload("prices.csv", _upload(rows), role)
    assert str(caught.value) == (
        "{} file: CSV row 3, column price_usd_bbl: "
        "Price must have no more than 6 decimal places.".format(role))
    assert rows == original


@pytest.mark.parametrize("role", ["blotter", "confirmations"])
@pytest.mark.parametrize("price", [
    "80", "80.123456", "80.000000", " 80.123456 ", "8.0123456e1",
    "1e-6", "80000000e-6", "8e1", "8.0000000e2",
], ids=["integer", "six-places", "six-trailing-zero-places", "raw-whitespace",
        "scientific-six-places", "scientific-small-boundary", "scientific-zero-boundary",
        "positive-exponent", "positive-exponent-reduces-scale"])
def test_upload_preserves_prices_at_or_below_six_places(make_trade, make_confirmation, role, price):
    """Accept supported scale without rewriting whitespace, zeros or exponent text."""
    trade = make_trade(price_usd_bbl=price, quantity="0.1234567")
    row = trade if role == "blotter" else make_confirmation(trade)
    original = deepcopy(row)
    assert app.validate_upload("prices.csv", _upload([row]), role) == [original]
    assert row == original


def test_generated_path_does_not_use_upload_price_validation(monkeypatch):
    """Real development-seed generation stays outside the upload-only scale gate."""
    def reject_upload(*args, **kwargs):
        raise AssertionError("Generated data must not pass through upload validation.")

    monkeypatch.setattr(app, "validate_upload", reject_upload)
    with app.create_workspace(app.ROOT / ".cache" / "review-score-price") as workspace:
        run = app.run_generated(workspace, 1)
        measured = app.load_scorecard(run)
        assert run["origin"] == "generated"
        assert len(run["blotter"]) == 200
        assert app.scorecard_headline(measured) == (
            "Found 32 of 32 planted cases. 0 missed, 0 false alarms. "
            "15 harmless differences correctly left alone.")
