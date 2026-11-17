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
    """Offer three direct entry choices; keep optional dataset controls collapsed."""
    example, sample, upload = st.columns(3)
    if example.button("See an example (200 trades)", key="see_example", type="primary", width="stretch"):
        st.session_state["upload_open"] = False
        st.session_state["seed"] = 1
        perform_run(lambda workspace: support.run_generated(workspace, 1))
    if sample.button("Try a small sample with three breaks", key="load_sample", width="stretch"):
        st.session_state["upload_open"] = False
        perform_run(support.run_sample)
    if upload.button("Upload your own files", key="upload_own", width="stretch"):
        clear_current_run()
        st.session_state["upload_open"] = True
    with st.expander("Change dataset", expanded=False):
        seed = st.number_input("Seed", min_value=0, max_value=2147483647,
                               value=1, step=1, key="seed", on_change=clear_current_run)
        if st.button("Load dataset", key="generate"):
            st.session_state["upload_open"] = False
            perform_run(lambda workspace: support.run_generated(workspace, int(seed)))
    if st.session_state.get("upload_open", False):
        blotter = st.file_uploader("Blotter CSV", type=["csv"], key="blotter_upload", on_change=clear_current_run)
        confirmations = st.file_uploader("Confirmations CSV", type=["csv"], key="confirmations_upload", on_change=clear_current_run)
        st.caption("CSV only. Row 1 is the header; row 2 is the first data record.")
        if st.button("Reconcile uploaded files", key="reconcile_uploads", disabled=blotter is None or confirmations is None):
            perform_run(lambda workspace: support.run_uploads(
                workspace, blotter.name, blotter.getvalue(), confirmations.name, confirmations.getvalue()))
    with st.sidebar:
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
    st.caption(f"Example dataset {run['seed']}.")
    if attempts > 1:
        st.info(f"This tool used {attempts} attempts to prepare the example. Earlier attempts did not pass its safety checks.")
        with st.expander("Dataset checks"):
            st.dataframe(pd.DataFrame(metadata.get("safety_rejections", [])), hide_index=True, width="stretch",
                         column_config={"attempt": "Attempt", "reason": "Reason"})


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
    with st.container(key="total_value"):
        st.markdown("""<style>
        .st-key-total_value [data-testid="stMetricValue"],
        .st-key-total_value [data-testid="stMetricValue"] > div {
            white-space: normal !important; overflow: visible !important;
            text-overflow: clip !important; overflow-wrap: anywhere;
            font-size: clamp(1.4rem, 3.2vw, 2.6rem);
        }
        </style>""", unsafe_allow_html=True)
        st.metric("Total value of discrepancy", support.dollars(summary["total_value"]))
        st.caption("Value of discrepancy uses different bases by break type. Review items stay blank and are excluded from the total.")
    st.subheader("Count and value by break type")
    rows = [{"Break type": item["break_type"], "Count": item["count"],
             "Value of discrepancy (USD)": support.dollars(item["value"])}
            for item in summary["by_type"]]
    st.dataframe(pd.DataFrame(rows, columns=["Break type", "Count", "Value of discrepancy (USD)"]),
                 hide_index=True, width="stretch", column_config={
                     "Break type": st.column_config.SelectboxColumn("Type of difference", options=list(explain.FRIENDLY_NAMES),
                                                                  format_func=support.pretty_case_name, disabled=True)})


def record_table(records, id_column, highlights):
    """Present every record in a group and highlight only engine-reported affected fields."""
    if not records:
        st.info("No record is present on this side for this item.")
        return
    frame = pd.DataFrame(records).set_index(id_column).transpose()
    if "side" in frame.index:
        frame.loc["side"] = frame.loc["side"].map(lambda value: {"BUY": "bought", "SELL": "sold"}.get(str(value).strip().upper(), value))
    if "unit" in frame.index:
        frame.loc["unit"] = frame.loc["unit"].map(lambda value: {"LOTS": "lots", "BBL": "barrels"}.get(str(value).strip().upper(), value))
    frame.index = [support.FIELD_LABELS.get(field, str(field).replace("_", " ").capitalize()) for field in frame.index]
    marked = {support.FIELD_LABELS.get(field, str(field).replace("_", " ").capitalize()) for field in highlights}

    def style_field(row):
        """Apply the same visible highlight to an affected field in every shown record."""
        css = "background-color: #fff0b3; color: #171717; font-weight: 600;" if row.name in marked else ""
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
    mode = st.selectbox("Sort exceptions", SORT_OPTIONS, key="sort_mode",
                        format_func=lambda value: "Type of difference" if value == "Break type" else value)
    rows = support.sort_exceptions(run["results"], mode)
    display = []
    for row in rows:
        amount = Decimal(row["value_of_discrepancy_usd"]) if row["value_of_discrepancy_usd"] else None
        display.append({"Priority": row["priority"], "Name": explain.FRIENDLY_NAMES.get(row["break_type"], "Needs manual review"),
                        "Break type": row["break_type"],
                        "Trade IDs": row["trade_id"], "Confirmation IDs": row["confirm_id"],
                        "Value of discrepancy (USD)": support.dollars(amount),
                        "Matching rule": row["matching_rule"], "Group": row.get("group_id", "")})
    st.caption("High-priority items come first. Change the sorting to explore other items.")
    rule_labels = {"RULE_2_REFERENCE": "Desk trade reference", "RULE_3_ATTRIBUTES": "Matching details",
                   "RULE_4_NEAR_MATCH": "One differing detail", "RULE_6_LEFTOVER": "No matching record"}
    st.dataframe(pd.DataFrame(display), hide_index=True, width="stretch", height=350,
                 column_config={"Name": st.column_config.TextColumn("Type of difference"),
                                "Break type": st.column_config.TextColumn("Case code"),
                                "Priority": st.column_config.SelectboxColumn("Priority", options=["HIGH", "STANDARD", "REVIEW"],
                                                                            format_func=lambda value: {"HIGH": "High", "STANDARD": "Standard", "REVIEW": "Manual review"}.get(value, value), disabled=True),
                                "Matching rule": st.column_config.SelectboxColumn("How records were linked", options=list(rule_labels),
                                                                                 format_func=lambda value: rule_labels.get(value, value), disabled=True)})
    choices = [row["_source_index"] for row in rows]
    if st.session_state.get("exception_index") not in choices:
        st.session_state["exception_index"] = choices[0]

    def describe(index):
        """Label a selectable exception with the actual engine type and involved IDs."""
        row = run["results"][index]
        name = explain.FRIENDLY_NAMES.get(row["break_type"], "Needs manual review")
        return f"{name} — trades {row['trade_id'] or 'none'}; confirmations {row['confirm_id'] or 'none'}"

    chosen = st.selectbox("Exception to inspect", choices, format_func=describe, key="exception_index")
    row = run["results"][chosen]
    detail = support.exception_details(run, row)
    st.subheader("Exception detail")
    wording = explain.explain_result(row, run)
    st.caption(wording["friendly_name"])
    for title, field in [("A. What happened", "what_happened"),
                         ("B. How the value is worked out", "how_value_is_worked_out"),
                         ("C. Suggested next step", "suggested_next_step")]:
        st.subheader(title)
        st.text(wording[field])
    st.caption(explain.GUIDANCE_CAPTION)
    st.subheader("D. Draft query to the broker")
    st.code(wording["draft_query"], language=None, wrap_lines=True)
    st.caption(explain.DRAFT_CAPTION)
    st.subheader("Supporting records")
    st.write(detail["note"])
    if detail["highlight_fields"]:
        labels = list(dict.fromkeys(support.FIELD_DIFF_LABELS.get(field, support.FIELD_LABELS.get(field, field)) for field in detail["highlight_fields"]))
        st.caption("Differs: " + ", ".join(labels))
    left, right = st.columns(2)
    with left:
        st.markdown("#### Blotter records")
        record_table(detail["blotter"], "trade_id", detail["highlight_fields"])
    with right:
        st.markdown("#### Confirmation records")
        record_table(detail["confirmations"], "confirm_id", detail["highlight_fields"])


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
    st.text(support.scorecard_headline(measured))
    scores = pd.DataFrame(measured["scores"]).astype(str)
    score_columns = {field: st.column_config.TextColumn(label) for field, label in support.SCORE_COLUMN_LABELS.items()}
    score_columns["case_type"] = st.column_config.SelectboxColumn(
        "Case type", options=list(scores["case_type"].unique()), format_func=support.pretty_case_name, disabled=True)
    st.dataframe(scores, hide_index=True, width="stretch", column_config=score_columns)
    st.subheader("How counterparty names were matched")
    names = pd.DataFrame(measured["names"])
    friendly_names = support.friendly_scorecard_frame(measured["names"])
    methods = dict(zip(names["counterparty_resolution"], friendly_names["counterparty_resolution"]))
    name_columns = {field: st.column_config.TextColumn(label) for field, label in support.NAME_COLUMN_LABELS.items()}
    name_columns["counterparty_resolution"] = st.column_config.SelectboxColumn(
        "Name matching method", options=list(methods), format_func=lambda value: methods.get(value, value), disabled=True)
    st.dataframe(names, hide_index=True, width="stretch", column_config=name_columns)
    st.caption("N/A means there were no cases to calculate that share. Harmless differences left alone are counted separately.")


def main():
    """Coordinate session input and presentation without changing engine behavior."""
    st.set_page_config(page_title="Brent Trade Reconciliation Tool", layout="wide", initial_sidebar_state="collapsed")
    st.title("Brent Trade Reconciliation Tool")
    st.write("Compare the desk's trade blotter with broker confirmations, find differences and see what needs checking.")
    st.caption("Built by Henry Cast")
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
    page = st.radio("Page", pages, key="page", horizontal=True)
    if st.session_state.get("error"):
        st.error(st.session_state["error"])
    if page == "Scorecard":
        render_scorecard(run)
    elif run is None:
        st.info("Choose an example, try the small sample, or upload both of your CSV files.")
    else:
        render_retry_information(run)
        render_summary(run)
        render_exceptions(run)


if __name__ == "__main__":
    main()
