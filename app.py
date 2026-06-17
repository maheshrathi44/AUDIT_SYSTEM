"""
AI Audit System — Streamlit frontend
Page 1: Upload procedures + dataset → Run Audit
Page 2: Full audit results (rules, column map, per-row verdicts, summary)
"""

import os
import tempfile

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AI Audit System",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── session state ──────────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "upload"
if "results" not in st.session_state:
    st.session_state.results = None


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Upload
# ══════════════════════════════════════════════════════════════════════════════
def page_upload() -> None:
    st.title("AI Audit System")
    st.caption("Upload procedure documents and a dataset to run an automated compliance audit.")
    st.markdown("---")

    col_left, col_right = st.columns(2, gap="large")

    with col_left:
        st.subheader("Procedure Documents")
        proc_files = st.file_uploader(
            "PDF, DOCX, TXT or MD — multiple files allowed",
            type=["pdf", "docx", "txt", "md"],
            accept_multiple_files=True,
        )

    with col_right:
        st.subheader("Dataset")
        dataset_file = st.file_uploader(
            "Excel file (.xlsx)",
            type=["xlsx"],
        )

    max_rows = st.number_input(
        "Rows to audit", min_value=1, max_value=50, value=4, step=1,
        help="Number of dataset rows to process. Keep low to stay within API limits.",
    )

    st.markdown("---")
    ready = bool(proc_files and dataset_file)
    if not ready:
        st.info("Upload at least one procedure file and a dataset to continue.")

    if st.button("Run Audit", type="primary", disabled=not ready):
        _run_pipeline(proc_files, dataset_file, int(max_rows))


def _run_pipeline(proc_files, dataset_file, max_rows: int) -> None:
    status_box = st.empty()

    def log(msg: str) -> None:
        status_box.info(f"⏳  {msg}")

    with tempfile.TemporaryDirectory() as tmp:
        # save uploaded files to temp dir
        proc_paths = []
        for f in proc_files:
            p = os.path.join(tmp, f.name)
            with open(p, "wb") as out:
                out.write(f.getvalue())
            proc_paths.append(p)

        ds_path = os.path.join(tmp, dataset_file.name)
        with open(ds_path, "wb") as out:
            out.write(dataset_file.getvalue())

        from audit.pipeline import run_pipeline
        try:
            results = run_pipeline(proc_paths, ds_path, max_rows=max_rows, on_progress=log)
        except Exception as e:
            st.error(f"Pipeline failed: {e}")
            return

    st.session_state.results = results
    st.session_state.page = "results"
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Results
# ══════════════════════════════════════════════════════════════════════════════
_VERDICT_FN  = {"Pass": st.success, "Fail": st.error,   "Missing Info": st.warning}
_OVERALL_FN  = {"Pass": st.success, "Fail": st.error,   "Partial": st.warning}
_RISK_BADGE  = {"High": "🔴 High",   "Medium": "🟡 Medium", "Low": "🟢 Low"}


def page_results() -> None:
    results = st.session_state.results

    if st.button("← New Audit"):
        st.session_state.page = "upload"
        st.session_state.results = None
        st.rerun()

    st.title("Audit Results")

    for w in results.warnings:
        st.warning(w)

    tab_rules, tab_cols, tab_rows, tab_summary = st.tabs(
        ["Extracted Rules", "Column Mapping", "Row Audit", "Summary"]
    )

    # ── Tab 1: Extracted Rules ─────────────────────────────────────────────
    with tab_rules:
        st.subheader(f"{len(results.rules)} rules extracted from procedures")
        for r in results.rules:
            tl    = f"  |  {r.timeline_days}d" if r.timeline_days else ""
            label = f"[{r.rule_id}]  {r.rule_type.upper()}  ·  {r.priority.upper()}{tl}"
            with st.expander(label):
                st.write(f"**Statement:** {r.statement}")
                st.write(f"**Keywords:** {', '.join(r.keywords)}")
                st.caption(f"Source: {r.source_name}  |  Section: {r.section}")

    # ── Tab 2: Column Mapping ──────────────────────────────────────────────
    with tab_cols:
        st.subheader("Dataset columns understood by LLM")
        col_rows = [
            {
                "Column":  h,
                "Role":    results.col_map.get(h, {}).get("semantic_role", ""),
                "Type":    results.col_map.get(h, {}).get("data_type", ""),
                "Meaning": results.col_map.get(h, {}).get("meaning", ""),
            }
            for h in results.audit_cols
        ]
        if col_rows:
            st.dataframe(pd.DataFrame(col_rows), use_container_width=True, hide_index=True)

    # ── Tab 3: Row-by-row Audit ────────────────────────────────────────────
    with tab_rows:
        for rr in results.row_results:
            st.markdown("---")
            st.subheader(f"Row {rr.index} — {rr.row_id}")

            # row data
            with st.expander("Row data (audit-relevant columns)"):
                display = [
                    {"Column": k, "Value": v}
                    for k, v in rr.row_data.items()
                    if k in results.audit_cols and v
                ]
                if display:
                    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)

            # matched rules
            with st.expander(f"{len(rr.matched)} matched rules"):
                for m in rr.matched:
                    tl = f"  |  Timeline: {m.rule.timeline_days}d" if m.rule.timeline_days else ""
                    st.markdown(f"**[{m.rule.rule_id}]**  `{m.priority}`{tl}")
                    st.write(f"*Why:* {m.relevance}")
                    st.write(f"*Rule:* {m.rule.statement}")
                    st.divider()

            # per-rule verdicts
            if rr.finding.verdicts:
                st.markdown("**Rule-by-Rule Verdict**")
                for v in rr.finding.verdicts:
                    fn = _VERDICT_FN.get(v.verdict, st.info)
                    fn(f"**[{v.rule_id}]  {v.verdict}**")
                    c1, c2 = st.columns(2)
                    c1.markdown(f"**Actual:** {v.actual_value}")
                    c2.markdown(f"**Expected:** {v.expected_value}")
                    st.markdown(f"**Reason:** {v.reason}")
                    st.divider()

            # row summary
            fn = _OVERALL_FN.get(rr.finding.overall, st.info)
            badge = _RISK_BADGE.get(rr.finding.risk, rr.finding.risk)
            fn(f"**Result: {rr.finding.overall}  |  Risk: {badge}**\n\n{rr.finding.summary}")

    # ── Tab 4: Summary Table ───────────────────────────────────────────────
    with tab_summary:
        st.subheader("Overall Audit Summary")
        summary_rows = [
            {
                "Row":           rr.row_id,
                "Result":        rr.finding.overall,
                "Risk":          rr.finding.risk,
                "Failed Rules":  ", ".join(rr.finding.failed_rules)  or "—",
                "Missing Rules": ", ".join(rr.finding.missing_rules) or "—",
                "Summary":       rr.finding.summary,
            }
            for rr in results.row_results
        ]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)


# ── Router ─────────────────────────────────────────────────────────────────────
if st.session_state.page == "upload":
    page_upload()
else:
    page_results()
