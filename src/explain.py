"""Deterministic wording for already-reported results; no matching or valuation decisions."""
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
import logging
import csv
import io

from src.compare import RESULT_COLUMNS

_LOGGER = logging.getLogger(__name__)

GUIDANCE_CAPTION = "General guidance only. Follow your own desk's procedure."
DRAFT_CAPTION = "Draft only. Nothing is sent by this tool."
FRIENDLY_NAMES = {"PRICE": "Price difference", "QUANTITY": "Volume difference",
                  "UNIT_ERROR": "Unit mismatch", "SIDE": "Buy/sell mismatch",
                  "CONTRACT_MONTH": "Wrong delivery month", "MISSING_CONFIRMATION": "Missing confirmation",
                  "UNKNOWN_CONFIRMATION": "Unknown confirmation", "DUPLICATE": "Duplicate confirmation",
                  "AMBIGUOUS": "Needs manual review"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _number(value):
    text = format(value, ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _money(value):
    # Prices retain significant fractional cents; never round a printed operand.
    if value == value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        return "$" + format(value, ",.2f")
    return "$" + _number(value)


def _details(record):
    date = record["_date"]
    year, month = record["contract_month"].split("-")
    barrels = _number(record["_volume_bbl"])
    volume = barrels + " barrels"
    if record["unit"] == "LOTS":
        volume = f"{_number(record['_quantity'])} lots ({barrels} barrels)"
    return dict(side="bought" if record["side"] == "BUY" else "sold", volume=volume,
                month=f"{_MONTHS[int(month)-1]} {year}", price=_money(record["_price"]),
                date=f"{date.day} {_MONTHS[date.month-1]} {date.year}",
                counterparty=record["counterparty"], broker=record["broker"])


def _opening(trade_id, details):
    return (f"The desk booked trade {trade_id}: {details['side']} {details['volume']} of {details['month']} Brent "
            f"at {details['price']} with {details['counterparty']} via {details['broker']} on {details['date']}.")


def _draft_identity(trade_id, details):
    return (f"Our trade {trade_id}: we {details['side']} {details['volume']} of {details['month']} Brent "
            f"at {details['price']} on {details['date']} with {details['counterparty']}.")


def _unilateral(result, context):
    missing = result["break_type"] == "MISSING_CONFIRMATION"
    record = context["trades"][result["trade_id"]] if missing else context["confirmations"][result["confirm_id"]]
    d = _details(record)
    identity = (f"{d['side']} {d['volume']} of {d['month']} Brent at {d['price']} "
                f"on {d['date']} with {d['counterparty']}")
    if missing:
        opening = _opening(result["trade_id"], d) + " No matching confirmation was found in these files."
        suffix = "This is the full value of the unconfirmed trade."
        guidance = "First check whether a confirmation in this report quotes a different trade reference but matches this trade's details. Ask the broker to send the confirmation. If the broker has no record of the trade, check with the trader that it was executed and booked with the right broker and counterparty. Also check the unknown confirmations in this report: one may be this trade with more than one detail different."
        draft = f"We have not been able to match a confirmation to our trade {result['trade_id']}: {identity}. Please send your confirmation or tell us if you have no record of this trade."
    else:
        opening = (f"Confirmation {result['confirm_id']} records the desk as having {d['side']} {d['volume']} of {d['month']} Brent at {d['price']} "
                   f"with {d['counterparty']} on {d['date']}. No matching trade was found in the desk's blotter.")
        suffix = "This is the full value of the confirmed trade."
        guidance = "Ask the trader whether this trade was done but not booked. If confirmed, book it following the desk's procedure. If the desk does not recognise it, ask the broker whether it belongs to another client. Also check the missing confirmations: this may be one of those trades with more than one detail different."
        draft = f"We cannot find a trade matching your confirmation {result['confirm_id']}: the desk {identity}. Please confirm the details and who gave the order while we check on our side."
    barrels = record["_volume_bbl"]
    value = _money(Decimal(result["value_of_discrepancy_usd"]))
    return {"friendly_name": FRIENDLY_NAMES[result["break_type"]], "what_happened": opening,
            "how_value_is_worked_out": f"{_number(barrels)} barrels × {d['price']} per barrel = {value}. {suffix}",
            "suggested_next_step": guidance, "draft_query": draft,
            "sum_shown": True, "sum_value": result["value_of_discrepancy_usd"],
            "displayed_operands": [{"value": str(barrels), "text": _number(barrels)},
                                   {"value": str(record["_price"]), "text": d["price"]}]}


def _duplicate(result, context):
    trade_id = result["trade_id"]
    d = _details(context["trades"][trade_id])
    ids = result["confirm_id"].split(";")
    confirmations = [context["confirmations"][identifier] for identifier in ids]
    count, extra = len(ids), len(ids) - 1
    extra_noun = "confirmation" if extra == 1 else "confirmations"
    names = ", ".join(ids)
    barrels, price = confirmations[0]["_volume_bbl"], confirmations[0]["_price"]
    value = _money(Decimal(result["value_of_discrepancy_usd"]))
    operands = [{"value": str(barrels), "text": _number(barrels)},
                {"value": str(price), "text": _money(price)}]
    if extra == 1:
        formula = (f"{_number(barrels)} barrels x {_money(price)} per barrel = {value}. "
                   "This is the value of the one extra confirmation.")
    else:
        formula = f"{extra} × {_number(barrels)} barrels × {_money(price)} per barrel = {value}. This tool counts {extra} {extra_noun} beyond the one expected."
        operands.insert(0, {"value": str(extra), "text": str(extra)})
    return {"friendly_name": FRIENDLY_NAMES["DUPLICATE"],
            "what_happened": f"The broker has confirmed trade {trade_id} {count} times: {names}. The desk has it booked once.",
            "how_value_is_worked_out": formula,
            "suggested_next_step": "Check how many trades were actually done. If only one, ask the broker to cancel the extra confirmations. If more than one, check whether trades are missing from the blotter before booking anything.",
            "draft_query": (f"We received {count} confirmations ({names}) for our trade {trade_id}: {d['side']} {d['volume']} of {d['month']} Brent "
                            f"at {d['price']} on {d['date']} with {d['counterparty']}. We have it booked once. Please confirm whether these are duplicate copies or separate trades, and cancel any extra copies."),
            "sum_shown": True, "sum_value": result["value_of_discrepancy_usd"],
            "displayed_operands": operands}


def _review(result, context):
    trade_ids = (result.get("candidate_trade_ids") or result["trade_id"]).split(";")
    confirm_ids = (result.get("candidate_confirm_ids") or result["confirm_id"]).split(";")
    trades, confirms = ", ".join(trade_ids), ", ".join(confirm_ids)
    candidates = []
    for label, ids, records in [("Trade", trade_ids, context["trades"]),
                                 ("Confirmation", confirm_ids, context["confirmations"])]:
        for identifier in ids:
            d = _details(records[identifier])
            candidates.append(f"{label} {identifier}: {d['side']} {d['volume']} of {d['month']} Brent at {d['price']} on {d['date']} with {d['counterparty']}")
    return {"friendly_name": FRIENDLY_NAMES["AMBIGUOUS"],
            "what_happened": f"This tool cannot choose one pairing between trades {trades} and confirmations {confirms}. It has not guessed.",
            "how_value_is_worked_out": "No value is shown because the pairing is unresolved. The trade details may still need checking.",
            "suggested_next_step": "Ask the broker which confirmation belongs to each trade. Use the original execution record, including times if available. Do not choose a pairing from these records alone.",
            "draft_query": (f"Your confirmations {confirms} could relate to more than one of our trades ({trades}). Please tell us which confirmation relates to which trade. Details: " + "; ".join(candidates) + "."),
            "sum_shown": False, "sum_value": "", "displayed_operands": []}


def _fallback_text(result):
    amount = result.get("value_of_discrepancy_usd", "")
    if amount == "" or amount is None:
        return "No value is shown."
    return f"This tool reports a value of discrepancy of {_money(Decimal(amount))}. A checked sum is not available for this item."


def _manual_item(result, context=None):
    draft = (f"Please help us check trades {result.get('trade_id') or '(none listed)'} and "
             f"confirmations {result.get('confirm_id') or '(none listed)'}. This item needs manual review.")
    details = []
    for role, field, candidate_field, label in [("trades", "trade_id", "candidate_trade_ids", "Trade"),
                                               ("confirmations", "confirm_id", "candidate_confirm_ids", "Confirmation")]:
        records = (context or {}).get(role, {})
        for identifier in (result.get(candidate_field) or result.get(field) or "").split(";"):
            if identifier not in records:
                continue
            try:
                d = _details(records[identifier])
            except (KeyError, ValueError, TypeError, AttributeError, IndexError, DecimalException):
                continue
            details.append(f"{label} {identifier}: {d['side']} {d['volume']} of {d['month']} Brent at {d['price']} on {d['date']} with {d['counterparty']}")
    if details:
        draft += " Details: " + "; ".join(details) + "."
    return {"friendly_name": FRIENDLY_NAMES.get(result.get("break_type"), "Needs manual review"),
            "what_happened": "This item needs manual review.",
            "how_value_is_worked_out": _fallback_text(result),
            "suggested_next_step": "Check the original records and follow your own desk's procedure.",
            "draft_query": draft,
            "sum_shown": False, "sum_value": "", "displayed_operands": []}


def _checked(item, result, run):
    if not item["sum_shown"]:
        return item
    # Verify the *printed* operands, not merely their underlying canonical values.
    product = Decimal(1)
    for operand in item["displayed_operands"]:
        printed = Decimal(operand["text"].replace("$", "").replace(",", ""))
        if not printed.is_finite() or printed < 0 or printed != Decimal(operand["value"]):
            raise ValueError("Invalid displayed operand")
        product *= printed
    if not item["displayed_operands"]:
        raise ValueError("No displayed operands")
    checked_value = product.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    authority = Decimal(result["value_of_discrepancy_usd"])
    valid = authority.is_finite() and checked_value == authority
    if result["break_type"] == "DUPLICATE":
        records = run["explanation_context"]["confirmations"]
        ids = result["confirm_id"].split(";")
        factors = {(records[i]["_volume_bbl"], records[i]["_price"]) for i in ids}
        valid = valid and len(ids) > 1 and len(factors) == 1
    if not valid:
        _LOGGER.warning("A checked sum is not available for item %s / %s: printed operands disagree or are ambiguous.",
                        result.get("trade_id", ""), result.get("confirm_id", ""))
        item.update(how_value_is_worked_out=_fallback_text(result), sum_shown=False,
                    sum_value="", displayed_operands=[])
    return item


def _other_differences(item, result, run):
    """Count only other reported rows naming the same explicit single pair."""
    trade_id, confirm_id = result.get("trade_id", ""), result.get("confirm_id", "")
    if trade_id and confirm_id and ";" not in trade_id and ";" not in confirm_id:
        count = sum(row.get("trade_id") == trade_id and row.get("confirm_id") == confirm_id
                    for row in run.get("results", [])) - 1
        if count > 0:
            noun = "difference" if count == 1 else "differences"
            item["what_happened"] += f" This pair has {count} other {noun}, listed separately."
    return item


def explain_result(result, run):
    """Return presentation only; the reported kind, order and amount remain authoritative.

    Common captions are separate UI constants. No inputs are read, paired, or changed.
    Missing canonical details or an unverifiable printed sum produce a logged fallback.
    """
    try:
        with localcontext() as arithmetic:
            # Plenty of precision for exact printed multiplication, including unusually
            # precise canonical operands. This does not change the reported valuation.
            records = run.get("explanation_context", {})
            numbers = [v for role in ("trades", "confirmations")
                       for record in records.get(role, {}).values()
                       for k, v in record.items() if k in {"_price", "_quantity", "_volume_bbl"}
                       and isinstance(v, Decimal) and v.is_finite()]
            arithmetic.prec = max([80] + [4 * (len(n.as_tuple().digits) + abs(n.as_tuple().exponent)) + 20 for n in numbers])
            if result.get("break_type") not in FRIENDLY_NAMES:
                _LOGGER.warning("A checked sum is not available for item %s / %s: unrecognised type %s.",
                                result.get("trade_id", ""), result.get("confirm_id", ""), result.get("break_type", ""))
                return _other_differences(_manual_item(result, records), result, run)
            item = _checked(_render_result(result, run), result, run)
            return _other_differences(item, result, run)
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, DecimalException) as error:
        _LOGGER.warning("A checked sum is not available for item %s / %s: canonical details are absent or invalid (%s: %s).",
                        result.get("trade_id", ""), result.get("confirm_id", ""), type(error).__name__, str(error))
        return _other_differences(_manual_item(result, run.get("explanation_context")), result, run)


def explain_all(run):
    """Explain every reported row, retaining its existing order, without filtering."""
    return [explain_result(result, run) for result in run["results"]]


def results_summary(run):
    """Describe existing priorities and the first three rows; do not re-rank them."""
    results = run["results"]
    if not results:
        count = len(run["explanation_context"]["trades"])
        return {"text": f"No exceptions found. All {count} trades matched on trade date, counterparty, buy/sell, delivery month, volume and price (within $0.01 per barrel).", "start_here": []}
    high = sum(row.get("priority") == "HIGH" for row in results)
    standard = sum(row.get("priority") == "STANDARD" for row in results)
    review = sum(row.get("priority") == "REVIEW" for row in results)
    first = []
    for row in results[:3]:
        friendly = FRIENDLY_NAMES.get(row.get("break_type"), "Needs manual review")
        value = "No value shown" if not row.get("value_of_discrepancy_usd") else _money(Decimal(row["value_of_discrepancy_usd"]))
        identifiers = []
        trade_id, confirm_id = row.get("trade_id", ""), row.get("confirm_id", "")
        if trade_id:
            label = "trades" if ";" in trade_id else "trade"
            identifiers.append(label + " " + trade_id.replace(";", ", "))
        if confirm_id and (not trade_id or row.get("break_type") in {"DUPLICATE", "AMBIGUOUS"}):
            label = "confirmations" if ";" in confirm_id else "confirmation"
            identifiers.append(label + " " + confirm_id.replace(";", ", "))
        first.append(", ".join([friendly] + identifiers + [value]))
    return {"text": f"{len(results)} items need attention: {high} high priority, {standard} standard, {review} for manual review.", "start_here": first}


def _spreadsheet_cell(column, value):
    """Escape formula-leading text, leaving numeric value cells unchanged."""
    if column == "value_of_discrepancy_usd":
        return value
    if column in {"blotter_value", "confirmation_value"}:
        try:
            if Decimal(str(value)).is_finite():
                return value
        except DecimalException:
            pass
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def report_csv(run):
    """Return spreadsheet-safe UTF-8 CSV with unchanged columns and numeric values."""
    additions = ["friendly_name", "what_happened", "how_value_is_worked_out", "suggested_next_step"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(RESULT_COLUMNS) + additions)
    writer.writeheader()
    for result, explanation in zip(run["results"], explain_all(run)):
        row = {column: result.get(column, "") for column in RESULT_COLUMNS}
        row.update({column: explanation[column] for column in additions})
        row["suggested_next_step"] += " " + GUIDANCE_CAPTION
        writer.writerow({column: _spreadsheet_cell(column, value) for column, value in row.items()})
    return output.getvalue().encode("utf-8")


def reading_guide():
    """Explain the report's differing value bases without implying realised outcomes."""
    return (
        "- A break is a difference or item that needs checking.\n"
        "- Value of discrepancy is not a loss or an amount owed.\n"
        "- Different break types use different sums. Read each explanation.\n"
        "- A blank value means pairing needs manual review, not zero.\n"
        "- Bought/sold describe the desk's direction; lots also show barrels.\n"
        "- Suggested steps are general guidance; drafts are not sent by this tool."
    )


def _render_result(result, run):
    """Explain one existing result using canonical records without modifying the run."""
    trade_id, confirm_id = result["trade_id"], result["confirm_id"]
    context = run["explanation_context"]
    kind = result["break_type"]
    if kind in {"MISSING_CONFIRMATION", "UNKNOWN_CONFIRMATION"}:
        return _unilateral(result, context)
    if kind == "DUPLICATE":
        return _duplicate(result, context)
    if kind == "AMBIGUOUS":
        return _review(result, context)
    trade, confirmation = context["trades"][trade_id], context["confirmations"][confirm_id]
    details = _details(trade)
    difference = abs(trade["_price"] - confirmation["_price"])
    barrels = trade["_volume_bbl"]
    value = _money(Decimal(result["value_of_discrepancy_usd"]))
    kind = result["break_type"]
    other = _details(confirmation)
    opening = _opening(trade_id, details)
    draft = _draft_identity(trade_id, details)
    if kind == "PRICE":
        ending = f"The broker's confirmation {confirm_id} shows {other['price']}."
        formula = f"{_money(difference)} per barrel × {_number(barrels)} barrels = {value}."
        guidance = "Check the price against the original execution record (a recorded call, chat or deal ticket) before changing either record. If the desk's booking is wrong, amend the blotter. If the confirmation is wrong, ask the broker for a corrected confirmation."
        draft += f" Your confirmation {confirm_id} shows {other['price']}. Please check your record and confirm the correct price."
        operands = [(difference, _money(difference)), (barrels, _number(barrels))]
    elif kind in {"QUANTITY", "UNIT_ERROR"}:
        difference = abs(barrels - confirmation["_volume_bbl"])
        formula = f"{_number(difference)} barrels × {details['price']} per barrel = {value}."
        operands = [(difference, _number(difference)), (trade["_price"], details["price"])]
        if kind == "QUANTITY":
            ending = f"The broker's confirmation {confirm_id} shows {other['volume']}."
            guidance = f"Check the agreed volume against the original execution record. The recorded volumes differ by {_number(difference)} barrels. Amend the blotter or ask the broker for a corrected confirmation, whichever is wrong."
            draft += f" Your confirmation {confirm_id} shows {other['volume']}. Please check your record and confirm the correct volume."
        else:
            desk_unit = "lots" if trade["unit"] == "LOTS" else "barrels"
            broker_unit = "lots" if confirmation["unit"] == "LOTS" else "barrels"
            ending = (f"Confirmation {confirm_id} shows the same number {_number(trade['_quantity'])}, but the desk uses {desk_unit} and the broker uses {broker_unit}. "
                      f"That is {_number(barrels)} barrels against {_number(confirmation['_volume_bbl'])} barrels.")
            guidance = "The same number with different units can mean a unit was entered wrongly. Confirm the intended volume against the original execution record, then correct whichever record has the wrong unit."
            draft += f" Your confirmation {confirm_id} shows {other['volume']}. Please confirm whether the agreed volume is in lots or barrels and send a corrected confirmation if needed."
    elif kind == "SIDE":
        ending = f"The broker's confirmation {confirm_id} shows the desk as having {other['side']}."
        formula = f"2 × {_number(barrels)} barrels × {details['price']} per barrel = {value}. The value is doubled because a trade booked the wrong way round would leave the position out by twice its volume."
        operands = [(Decimal(2), "2"), (barrels, _number(barrels)), (trade["_price"], details["price"])]
        guidance = "Treat this as urgent and tell the trader now. Check whether the desk bought or sold against the original execution record. Then amend the blotter or ask the broker for a corrected confirmation, whichever is wrong."
        draft = draft.replace(": we ", ": our record shows we ", 1)
        draft += f" Your confirmation {confirm_id} shows that we {other['side']}. Please check urgently and confirm the correct direction."
    else:
        ending = f"The broker's confirmation {confirm_id} shows {other['month']}."
        formula = f"{_number(barrels)} barrels × {details['price']} per barrel = {value}. The full trade value is shown because the whole trade may sit in the wrong delivery month."
        operands = [(barrels, _number(barrels)), (trade["_price"], details["price"])]
        guidance = "Check the delivery month against the original execution record. Until this is resolved, the desk may hold its position in a different month from the one it expects. Amend the blotter or ask the broker for a corrected confirmation, whichever is wrong."
        draft += f" Your confirmation {confirm_id} shows {other['month']}. Please check your record and confirm the correct delivery month."
    return {"friendly_name": FRIENDLY_NAMES[kind], "what_happened": opening + " " + ending,
            "how_value_is_worked_out": formula, "suggested_next_step": guidance,
            "draft_query": draft, "sum_shown": True,
            "sum_value": result["value_of_discrepancy_usd"],
            "displayed_operands": [{"value": str(number), "text": text} for number, text in operands]}
