"""Stage 3 presentation only; all pairing and monetary values come from the frozen engine."""
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

import app_support as support
from src import explain

SIMULATED_LABEL = "Prices are simulated, anchored to published Brent spot prices."
SCORECARD_CAVEAT = ("Correct against its specification on generated data with known answers. "
                   "Not evidence of production readiness.")
SORT_OPTIONS = ["Priority then value", "Value of discrepancy (largest first)", "Break type", "Trade ID"]


def clear_current_run():
    """Remove prior results and score access whenever the chosen inputs change."""
    support.invalidate_run(st.session_state)
    st.session_state["run"] = None
    st.session_state.pop("exception_index", None)


def session_workspace():
    """Keep one independently named temporary workspace alive for this browser session."""
    resource = st.session_state.get("_workspace")
    if resource is None or not Path(resource.name).is_dir():
        resource = support.create_workspace()
        st.session_state["_workspace"] = resource
    return Path(resource.name)


def perform_run(action):
    """Keep failed actions from showing old results or exposing exception tracebacks."""
    clear_current_run()
    try:
        with st.spinner("Preparing records and checking for differences..."):
            st.session_state["run"] = action(session_workspace())
    except support.AppInputError as error:
        st.session_state["error"] = str(error)
    except Exception:
        st.session_state["error"] = "This run could not be completed. Check your CSV files or try generating again."


def render_sample_downloads():
    """Display the included sample pairs as byte-for-byte downloads."""
    with st.expander("Download sample files", expanded=False):
        for sample, description in [
                ("clean", "Clean: ten trades, no exceptions"),
                ("with_breaks", "With three breaks: price, buy/sell and missing confirmation")]:
            st.markdown("**" + description + "**")
            for role in ["blotter", "confirmations"]:
                path = Path(__file__).resolve().parent / "sample_data" / sample / (role + ".csv")
                st.download_button("Download " + role + " CSV", path.read_bytes(),
                                   file_name=sample + "_" + role + ".csv", mime="text/csv",
                                   key="sample_" + sample + "_" + role, on_click="ignore")


def input_controls():
    """Offer upload and generated-data routes, without accepting an answer-key upload."""
    with st.sidebar:
        mode = st.radio("Input method", ["Upload files", "Generate data"],
                        key="input_mode", on_change=clear_current_run)
        if mode == "Upload files":
            blotter = st.file_uploader("Blotter CSV", type=["csv"], key="blotter_upload",
                                       on_change=clear_current_run)
            confirmations = st.file_uploader("Confirmations CSV", type=["csv"], key="confirmations_upload",
                                             on_change=clear_current_run)
            st.caption("CSV only. Row 1 is the header; row 2 is the first data record.")
            if st.button("Reconcile uploaded files", key="reconcile_uploads",
                         disabled=blotter is None or confirmations is None):
                perform_run(lambda workspace: support.run_uploads(
                    workspace, blotter.name, blotter.getvalue(), confirmations.name, confirmations.getvalue()))
        else:
            seed = st.number_input("Seed", min_value=0, max_value=2147483647,
                                   value=1, step=1, key="seed", on_change=clear_current_run)
            if st.button("Generate new dataset", key="generate", type="primary"):
                perform_run(lambda workspace: support.run_generated(workspace, int(seed)))
        st.caption("Inputs and outputs stay in this session's temporary workspace.")
        if st.button("Clear session", key="clear_session"):
            clear_current_run()
            resource = st.session_state.pop("_workspace", None)
            if resource is not None:
                resource.cleanup()
        render_sample_downloads()


def render_retry_information(run):
    """Display actual generator retry metadata rather than concealing rejected samples."""
    if run["origin"] != "generated":
        return
    metadata = run.get("generation_metadata") or {}
    attempts = metadata.get("generation_attempts", 1)
    st.caption(f"Generated in this session with seed {run['seed']}.")
    if attempts > 1:
        st.info(f"The generator used {attempts} sampling attempts. Unsafe samples were rejected before reconciliation.")
        with st.expander("Generation retry log"):
            st.dataframe(pd.DataFrame(metadata.get("safety_rejections", [])), hide_index=True, width="stretch")
    else:
        st.caption("The generator accepted its first sample.")


def render_summary(run):
    """Show record counts and the engine-valued type breakdown beside the total."""
    introduction = explain.results_summary(run)
    st.text(introduction["text"])
    if introduction["start_here"]:
        st.markdown("**Start here:**")
        for line in introduction["start_here"]:
            st.text(line)
    with st.expander("How to read this", expanded=False):
        st.write(explain.reading_guide())
    summary = support.summarise(run)
    columns = st.columns(4)
    for column, label, key in zip(columns,
                                   ["Trades processed", "Matched trades", "Established pairs", "Review groups"],
                                   ["trades_processed", "matched_trades", "matched_pairs", "review_groups"]):
        column.metric(label, summary[key])
    total_column, breakdown_column = st.columns([1, 2])
    with total_column:
        st.metric("Total value of discrepancy", support.dollars(summary["total_value"]))
        st.caption("Value of discrepancy uses different bases by break type. Review items stay blank and are excluded from the total.")
    with breakdown_column:
        st.subheader("Count and value by break type")
        rows = [{"Break type": item["break_type"], "Count": item["count"],
                 "Value of discrepancy (USD)": support.dollars(item["value"])}
                for item in summary["by_type"]]
        st.dataframe(pd.DataFrame(rows, columns=["Break type", "Count", "Value of discrepancy (USD)"]),
                     hide_index=True, width="stretch")


def record_table(records, id_column, highlights):
    """Present every record in a group and highlight only engine-reported affected fields."""
    if not records:
        st.info("No record is present on this side for this item.")
        return
    frame = pd.DataFrame(records).set_index(id_column).transpose()

    def style_field(row):
        """Apply the same visible highlight to an affected field in every shown record."""
        css = "background-color: #fff0b3; color: #171717; font-weight: 600;" if row.name in highlights else ""
        return [css] * len(row)

    styled = frame.style.apply(style_field, axis=1).format(escape="html")
    st.table(styled)


def render_exceptions(run):
    """Sort existing exceptions without recalculating them and inspect original records side by side."""
    st.subheader("Exceptions")
    st.download_button("Download exceptions report (CSV)", explain.report_csv(run),
                       file_name="exceptions_report.csv", mime="text/csv", key="download_exceptions")
    if not run["results"]:
        st.success("No exceptions were reported by this tool.")
        return
    mode = st.selectbox("Sort exceptions", SORT_OPTIONS, key="sort_mode")
    rows = support.sort_exceptions(run["results"], mode)
    display = []
    for row in rows:
        amount = Decimal(row["value_of_discrepancy_usd"]) if row["value_of_discrepancy_usd"] else None
        display.append({"Priority": row["priority"], "Name": explain.FRIENDLY_NAMES.get(row["break_type"], "Needs manual review"),
                        "Break type": row["break_type"],
                        "Trade IDs": row["trade_id"], "Confirmation IDs": row["confirm_id"],
                        "Value of discrepancy (USD)": support.dollars(amount),
                        "Matching rule": row["matching_rule"], "Group": row.get("group_id", "")})
    st.caption("Starts HIGH first. Use the sort control for exact numeric value sorting; table headers also sort displayed columns.")
    st.dataframe(pd.DataFrame(display), hide_index=True, width="stretch", height=350)
    choices = [row["_source_index"] for row in rows]
    if st.session_state.get("exception_index") not in choices:
        st.session_state["exception_index"] = choices[0]

    def describe(index):
        """Label a selectable exception with the actual engine type and involved IDs."""
        row = run["results"][index]
        name = explain.FRIENDLY_NAMES.get(row["break_type"], "Needs manual review")
        return f"{name} ({row['break_type']}) — trades {row['trade_id'] or 'none'}; confirmations {row['confirm_id'] or 'none'}"

    chosen = st.selectbox("Exception to inspect", choices, format_func=describe, key="exception_index")
    row = run["results"][chosen]
    detail = support.exception_details(run, row)
    st.subheader("Exception detail")
    st.write(detail["note"])
    if row["break_type"] == "CONTRACT_MONTH":
        st.caption("Wrong delivery month.")
    if detail["highlight_fields"]:
        st.caption("Highlighted fields: " + ", ".join(detail["highlight_fields"]))
    if row.get("group_id"):
        st.caption("Group: " + row["group_id"] + ". All involved records are shown without selecting a preferred record.")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Blotter records")
        record_table(detail["blotter"], "trade_id", detail["highlight_fields"])
    with right:
        st.markdown("#### Confirmation records")
        record_table(detail["confirmations"], "confirm_id", detail["highlight_fields"])
    wording = explain.explain_result(row, run)
    st.caption(wording["friendly_name"] + " (" + row["break_type"] + ")")
    for title, field in [("A. What happened", "what_happened"),
                         ("B. How the value is worked out", "how_value_is_worked_out"),
                         ("C. Suggested next step", "suggested_next_step")]:
        st.subheader(title)
        st.text(wording[field])
    st.caption(explain.GUIDANCE_CAPTION)
    st.subheader("D. Draft query to the broker")
    st.code(wording["draft_query"], language=None, wrap_lines=True)
    st.caption(explain.DRAFT_CAPTION)


def render_scorecard(run):
    """Show scorer measurements only for a dataset generated in this app session."""
    if run is None or run["origin"] != "generated":
        st.info("A measured scorecard is available only after generating a dataset in this session.")
        return
    st.header("Measured scorecard")
    st.warning(SCORECARD_CAVEAT)
    try:
        measured = support.load_scorecard(run)
    except support.AppInputError as error:
        st.error(str(error))
        return
    except Exception:
        st.error("The scorecard could not be measured. Generate the dataset again and retry.")
        return
    st.dataframe(pd.DataFrame(measured["scores"]).astype(str), hide_index=True, width="stretch")
    st.subheader("Planted counterparty-name resolution")
    st.dataframe(pd.DataFrame(measured["names"]), hide_index=True, width="stretch")
    st.caption("Precision and recall are fractions from the existing scorer. N/A means no denominator; correctly quiet is reported separately.")


def main():
    """Coordinate session input and presentation without changing engine behavior."""
    st.set_page_config(page_title="Brent Trade Reconciliation Tool", layout="wide")
    st.title("Brent Trade Reconciliation Tool")
    st.caption(SIMULATED_LABEL)
    st.session_state.setdefault("run", None)
    resource = st.session_state.get("_workspace")
    if resource is not None and not Path(resource.name).is_dir():
        st.session_state.pop("_workspace", None)
        clear_current_run()
        st.info("Temporary session files were cleared. Generate or upload a dataset again.")
    input_controls()
    run = st.session_state.get("run")
    pages = ["Reconciliation", "Scorecard"] if run and run["origin"] == "generated" else ["Reconciliation"]
    if st.session_state.get("page") not in pages:
        st.session_state["page"] = pages[0]
    page = st.sidebar.radio("Page", pages, key="page")
    if st.session_state.get("error"):
        st.error(st.session_state["error"])
    if page == "Scorecard":
        render_scorecard(run)
    elif run is None:
        st.info("Upload both CSV files and reconcile them, or choose Generate data and click Generate new dataset.")
    else:
        render_retry_information(run)
        render_summary(run)
        render_exceptions(run)


if __name__ == "__main__":
    main()
