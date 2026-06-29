"""AI Audit System — Streamlit frontend (full-dataset v2 pipeline)"""

import os
import tempfile

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AI Audit System",
    layout="wide",
    initial_sidebar_state="collapsed",
)

for k, v in [("page", "upload"), ("results", None), ("dark", False)]:
    if k not in st.session_state:
        st.session_state[k] = v


# ── Theme ──────────────────────────────────────────────────────────────────────
def _c():
    """Return color dict for the current theme."""
    d = st.session_state.dark
    if d:
        return dict(
            bg="#0d0f17", surface="#161929", border="#252840",
            text="#dde1f5", muted="#7b82a8", accent="#7c8ef7",
            pass_bg="#0a2e1a", pass_fg="#4ade80",
            fail_bg="#2e0a0a", fail_fg="#f87171",
            miss_bg="#2b2006", miss_fg="#fbbf24",
        )
    return dict(
        bg="#f0f2f8", surface="#ffffff", border="#dde2f0",
        text="#111827", muted="#6b7280", accent="#4b5cf6",
        pass_bg="#dcfce7", pass_fg="#166534",
        fail_bg="#fee2e2", fail_fg="#991b1b",
        miss_bg="#fefce8", miss_fg="#854d0e",
    )


def _inject_css() -> None:
    t = _c()
    st.markdown(f"""
<style>
#MainMenu, footer, header {{ visibility: hidden; }}
.stDeployButton {{ display: none !important; }}

/* ── Base ── */
.stApp {{
    background: {t['bg']};
    color: {t['text']};
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
}}
.block-container {{ padding-top: 1.6rem; padding-bottom: 2.5rem; max-width: 1240px; }}

/* Force text colour in Streamlit markdown/text containers */
.stMarkdown p, .stMarkdown li, .stMarkdown span,
[data-testid="stText"], [data-testid="stMarkdownContainer"] p {{
    color: {t['text']} !important;
}}
.stCaption p {{ color: {t['muted']} !important; }}

/* ── App header ── */
.app-header {{
    display: flex; align-items: flex-start; justify-content: space-between;
    padding-bottom: 14px; margin-bottom: 22px;
    border-bottom: 1.5px solid {t['border']};
}}
.app-title {{ font-size: 19px; font-weight: 700; color: {t['text']}; letter-spacing: -.4px; }}
.app-sub   {{ font-size: 12px; color: {t['muted']}; margin-top: 3px; }}

/* ── Section label ── */
.slbl {{
    font-size: 10.5px; font-weight: 700; color: {t['muted']};
    text-transform: uppercase; letter-spacing: .8px; margin-bottom: 7px;
}}

/* ── KPI grid ── */
.kpi-grid {{ display: flex; gap: 10px; margin-bottom: 22px; flex-wrap: wrap; }}
.kpi {{
    flex: 1; min-width: 110px;
    background: {t['surface']}; border: 1px solid {t['border']};
    border-radius: 10px; padding: 14px 16px; text-align: center;
}}
.kpi-val {{ font-size: 24px; font-weight: 700; color: {t['accent']}; line-height: 1.1; }}
.kpi-lbl {{ font-size: 10px; color: {t['muted']}; text-transform: uppercase; letter-spacing: .6px; margin-top: 4px; }}

/* ── Badges ── */
.badge {{
    display: inline-flex; align-items: center;
    padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600; letter-spacing: .3px; white-space: nowrap;
}}
.b-pass    {{ background: {t['pass_bg']}; color: {t['pass_fg']}; }}
.b-fail    {{ background: {t['fail_bg']}; color: {t['fail_fg']}; }}
.b-partial {{ background: {t['miss_bg']}; color: {t['miss_fg']}; }}
.b-missing {{ background: {t['miss_bg']}; color: {t['miss_fg']}; }}
.b-high    {{ background: {t['fail_bg']}; color: {t['fail_fg']}; }}
.b-medium  {{ background: {t['miss_bg']}; color: {t['miss_fg']}; }}
.b-low     {{ background: {t['pass_bg']}; color: {t['pass_fg']}; }}
.b-prio-cr {{ background: {t['fail_bg']}; color: {t['fail_fg']}; }}
.b-prio-hi {{ background: {t['fail_bg']}; color: {t['fail_fg']}; opacity:.8; }}
.b-prio-me {{ background: {t['miss_bg']}; color: {t['miss_fg']}; }}
.b-prio-lo {{ background: {t['pass_bg']}; color: {t['pass_fg']}; }}

/* ── Verdict cards ── */
.vcard {{
    background: {t['surface']}; border: 1px solid {t['border']};
    border-radius: 10px; padding: 16px 20px; margin: 8px 0;
    border-left: 4px solid {t['border']};
    scroll-margin-top: 80px;
}}
.vcard-pass    {{ border-left-color: #22c55e; }}
.vcard-fail    {{ border-left-color: #ef4444; }}
.vcard-partial {{ border-left-color: #f59e0b; }}
.vcard-missing {{ border-left-color: #94a3b8; }}

/* ── Compliance bar ── */
.cbar-wrap {{ background: {t['border']}; border-radius: 99px; height: 5px; margin: 8px 0; overflow: hidden; }}
.cbar      {{ height: 100%; border-radius: 99px; }}

/* ── Detail computation card ── */
.dcard {{
    background: {t['surface']}; border: 1px solid {t['border']};
    border-radius: 8px; padding: 13px 16px; margin: 6px 0;
}}
.dcard-warn {{
    border-left: 3px solid #f59e0b;
    background: {t['miss_bg']};
}}
.dcard-id   {{ font-size: 12px; font-weight: 700; color: {t['accent']}; }}
.dcard-body {{ font-size: 12.5px; color: {t['text']}; line-height: 1.6; margin-top: 4px; }}
.dcard-meta {{ font-size: 11.5px; color: {t['muted']}; }}

/* ── Summary rule table ── */
.rtable {{ width:100%; border-collapse:collapse; font-size:13px; }}
.rtable th {{
    text-align:left; padding:8px 12px;
    color:{t['muted']}; font-size:10px; font-weight:700;
    text-transform:uppercase; letter-spacing:.5px;
    border-bottom:1.5px solid {t['border']}; white-space:nowrap;
}}
.rtable td {{ padding:9px 12px; border-bottom:1px solid {t['border']}; color:{t['text']}; vertical-align:middle; }}
.rtable tr:last-child td {{ border-bottom:none; }}
.rtable tbody tr:hover td {{ background:{t['bg']}; }}
.rid-link {{
    color:{t['accent']}; font-weight:700; text-decoration:none; font-size:12px; font-family:monospace;
}}
.rid-link:hover {{ text-decoration:underline; }}
.num-pass {{ color:#22c55e; font-weight:600; }}
.num-fail {{ color:#ef4444; font-weight:600; }}
.num-miss {{ color:{t['muted']}; }}

/* ── Streamlit component overrides ── */
[data-testid="stFileUploader"] {{
    background: {t['surface']}; border: 2px dashed {t['border']};
    border-radius: 10px; padding: 8px;
}}
.stButton > button[kind="primary"] {{
    background: {t['accent']}; border: none; border-radius: 8px;
    padding: 10px 28px; font-weight: 600; font-size: 14px;
    color: #fff !important; width: 100%;
}}
.stButton > button[kind="primary"]:hover {{ opacity: .88; }}
.stButton > button[kind="secondary"] {{
    background: transparent; border: 1px solid {t['border']};
    color: {t['text']} !important; border-radius: 8px;
}}
.stExpander > details {{
    background: {t['surface']} !important;
    border: 1px solid {t['border']} !important;
    border-radius: 10px !important;
}}
.stExpander summary span {{ color: {t['text']} !important; }}
div[data-testid="stDataFrame"] {{
    border-radius: 10px; overflow: hidden; border: 1px solid {t['border']};
}}
.stTabs [data-baseweb="tab-list"] {{ border-bottom: 1px solid {t['border']}; gap: 4px; }}
.stTabs [data-baseweb="tab"] {{
    font-size: 13px; font-weight: 500; color: {t['muted']};
    padding: 8px 16px; border-radius: 6px 6px 0 0;
}}
.stTabs [aria-selected="true"] {{
    color: {t['accent']} !important; font-weight: 600;
    border-bottom: 2px solid {t['accent']} !important;
}}
/* number inputs / text inputs */
.stNumberInput input, .stTextInput input {{
    background: {t['surface']} !important; color: {t['text']} !important;
    border: 1px solid {t['border']} !important; border-radius: 8px !important;
}}
/* info/warning/error boxes */
[data-testid="stAlert"] {{ border-radius: 8px; }}
</style>
""", unsafe_allow_html=True)


# ── Shared helpers ─────────────────────────────────────────────────────────────
def _header(title: str, subtitle: str = "") -> None:
    c1, c2 = st.columns([7, 1])
    with c1:
        sub = f'<div class="app-sub">{subtitle}</div>' if subtitle else ""
        st.markdown(
            f'<div class="app-header"><div>'
            f'<div class="app-title">{title}</div>{sub}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        lbl = "Light Mode" if st.session_state.dark else "Dark Mode"
        if st.button(lbl, key="theme_btn"):
            st.session_state.dark = not st.session_state.dark
            st.rerun()


def _badge(verdict: str) -> str:
    cls = {
        "Pass": "b-pass", "Fail": "b-fail",
        "Partial": "b-partial", "Missing": "b-missing",
    }.get(verdict, "b-missing")
    return f'<span class="badge {cls}">{verdict}</span>'


def _risk_badge(risk: str) -> str:
    cls = {"High": "b-high", "Medium": "b-medium", "Low": "b-low"}.get(risk, "b-medium")
    return f'<span class="badge {cls}">{risk} Risk</span>'


def _kpi(label: str, value: str) -> str:
    return (
        f'<div class="kpi">'
        f'<div class="kpi-val">{value}</div>'
        f'<div class="kpi-lbl">{label}</div>'
        f'</div>'
    )


def _bar_color(pct: float) -> str:
    if pct >= 90: return "#22c55e"
    if pct >= 60: return "#f59e0b"
    return "#ef4444"


def _cbar(pct: float) -> str:
    return (
        f'<div class="cbar-wrap">'
        f'<div class="cbar" style="width:{pct}%;background:{_bar_color(pct)}"></div>'
        f'</div>'
    )


def _prio_badge(priority: str) -> str:
    p = priority.lower()
    cls = {"critical": "b-prio-cr", "high": "b-prio-hi",
           "medium": "b-prio-me", "low": "b-prio-lo"}.get(p, "b-prio-me")
    return f'<span class="badge {cls}">{priority.title()}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Upload
# ══════════════════════════════════════════════════════════════════════════════
def page_upload() -> None:
    _inject_css()
    _header("AI Audit System", "Full-dataset compliance auditing — all rows, minimal LLM calls")

    c_proc, c_data, c_supp = st.columns(3, gap="large")

    with c_proc:
        st.markdown('<div class="slbl">Procedure Documents</div>', unsafe_allow_html=True)
        proc_files = st.file_uploader(
            "procedures",
            type=["pdf", "docx", "txt", "md"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

    with c_data:
        st.markdown('<div class="slbl">Dataset</div>', unsafe_allow_html=True)
        dataset_file = st.file_uploader(
            "dataset",
            type=["xlsx"],
            label_visibility="collapsed",
        )

    with c_supp:
        t = _c()
        st.markdown('<div class="slbl">Supported Documents</div>', unsafe_allow_html=True)
        supp_files = st.file_uploader(
            "supported_docs",
            type=["pdf", "docx"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if supp_files:
            names = [f.name for f in supp_files]
            name_pills = "".join(
                f'<code style="background:{t["surface"]};border:1px solid {t["border"]};'
                f'border-radius:4px;padding:2px 7px;font-size:11px;'
                f'color:{t["accent"]};margin:2px 3px 2px 0;display:inline-block">{n}</code>'
                for n in names
            )
            st.markdown(
                f'<div style="font-size:12px;color:{t["text"]};margin-top:8px;line-height:1.8">'
                f'<b>Detected:</b><br>{name_pills}'
                f'<div style="color:{t["muted"]};margin-top:6px;font-size:11px">'
                f'These exact filenames must appear in the relevant dataset column.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption(
                "Optional — upload documents that rules may reference. "
                "The filename must match exactly what the dataset column stores."
            )

    st.markdown("<br>", unsafe_allow_html=True)
    ready = bool(proc_files and dataset_file)
    if not ready:
        st.caption("Upload at least one procedure document and a dataset to continue.")

    if st.button("Run Audit", type="primary", disabled=not ready):
        doc_names = [f.name for f in supp_files] if supp_files else []
        _run_pipeline(proc_files, dataset_file, doc_names)


def _run_pipeline(proc_files, dataset_file, supported_doc_names=None) -> None:
    status   = st.empty()
    progress = st.progress(0)

    step_map = {
        "step 1": 5,  "extract": 12,
        "step 2": 28, "column": 33, "read": 22,
        "step 3": 44, "filter": 50,
        "step 4": 55, "rule check": 62, "check": 62,
        "step 5": 68, "travers": 72,
        "step 6": 80, "verdict": 83,
        "step 7": 90, "report": 93,
    }

    def log(msg: str) -> None:
        status.info(msg)
        low = msg.lower()
        for kw, pct in step_map.items():
            if kw in low:
                progress.progress(pct)
                break

    with tempfile.TemporaryDirectory() as tmp:
        proc_paths = []
        for f in proc_files:
            p = os.path.join(tmp, f.name)
            with open(p, "wb") as fout:
                fout.write(f.getvalue())
            proc_paths.append(p)

        ds_path = os.path.join(tmp, dataset_file.name)
        with open(ds_path, "wb") as fout:
            fout.write(dataset_file.getvalue())

        try:
            from audit.pipeline_v2 import run_pipeline_v2
            results = run_pipeline_v2(
                proc_paths, ds_path,
                supported_doc_names=supported_doc_names or [],
                on_progress=log,
            )
        except Exception as e:
            status.empty()
            progress.empty()
            st.error(f"Pipeline failed: {e}")
            return

    progress.progress(100)
    status.empty()
    progress.empty()
    st.session_state.results = results
    st.session_state.page    = "results"
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Results
# ══════════════════════════════════════════════════════════════════════════════
def page_results() -> None:
    _inject_css()
    t       = _c()
    results = st.session_state.results
    report  = results.report

    _header("Audit Results")

    cb, _ = st.columns([1, 6])
    with cb:
        if st.button("← New Audit", key="back_btn"):
            st.session_state.page    = "upload"
            st.session_state.results = None
            st.rerun()

    for w in results.warnings:
        st.warning(w)

    # ── KPI strip ─────────────────────────────────────────────────────────────
    kpis = [
        ("Total Rows",        f"{results.total_rows:,}"),
        ("Rules Audited",     str(report.total_rules_audited)),
        ("Passed",            str(len(report.passed_rules))),
        ("Failed / Partial",  f"{len(report.failed_rules)} / {len(report.partial_rules)}"),
        ("Overall Compliance", f"{report.overall_compliance_pct}%"),
        ("Overall Risk",      report.overall_risk),
    ]
    st.markdown(
        '<div class="kpi-grid">' + "".join(_kpi(l, v) for l, v in kpis) + "</div>",
        unsafe_allow_html=True,
    )

    # ── Executive summary banner ───────────────────────────────────────────────
    risk_border = {"High": "#ef4444", "Medium": "#f59e0b", "Low": "#22c55e"}.get(report.overall_risk, t["border"])
    risk_areas_html = (
        "<ul style='margin:8px 0 0;padding-left:18px'>"
        + "".join(f'<li style="color:{t["text"]};font-size:13px;margin-bottom:3px">{a}</li>'
                  for a in report.risk_areas)
        + "</ul>"
    ) if report.risk_areas else ""

    st.markdown(
        f'<div style="background:{t["surface"]};border:1px solid {t["border"]};'
        f'border-left:4px solid {risk_border};border-radius:10px;'
        f'padding:16px 20px;margin-bottom:20px">'
        f'<div style="margin-bottom:8px">{_risk_badge(report.overall_risk)}</div>'
        f'<div style="font-size:13.5px;color:{t["text"]};line-height:1.65">{report.summary}</div>'
        f'{risk_areas_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_v, tab_d, tab_r, tab_c, tab_drop = st.tabs([
        f"Rule Verdicts ({report.total_rules_audited})",
        "Detailed Data",
        f"All Rules ({len(results.all_rules)})",
        f"Column Map ({len(results.audit_cols)})",
        f"Dropped ({len(results.dropped_rules)})",
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Rule Verdicts
    # ══════════════════════════════════════════════════════════════════════════
    with tab_v:
        # Summary table with clickable rule ID links
        st.markdown(
            f'<div class="slbl" style="margin-bottom:10px">'
            f'Click a Rule ID to jump to its full detail below</div>',
            unsafe_allow_html=True,
        )

        header_html = (
            "<thead><tr>"
            "<th>Rule ID</th><th>Verdict</th><th>Compliance</th><th>Risk</th>"
            "<th>Total</th><th>Pass</th><th>Fail</th><th>Missing</th>"
            "</tr></thead>"
        )
        rows_html = ""
        for v in results.verdicts:
            rows_html += (
                f"<tr>"
                f'<td><a class="rid-link" href="#vcard-{v.rule_id}">{v.rule_id}</a></td>'
                f"<td>{_badge(v.verdict)}</td>"
                f'<td style="color:{_bar_color(v.compliance_pct)};font-weight:600">{v.compliance_pct}%</td>'
                f"<td>{_risk_badge(v.risk)}</td>"
                f'<td style="color:{t["text"]}">{v.total_rows:,}</td>'
                f'<td class="num-pass">{v.pass_count:,}</td>'
                f'<td class="num-fail">{v.fail_count:,}</td>'
                f'<td class="num-miss">{v.missing_count:,}</td>'
                f"</tr>"
            )

        st.markdown(
            f'<div style="background:{t["surface"]};border:1px solid {t["border"]};'
            f'border-radius:10px;overflow:hidden;margin-bottom:28px">'
            f'<table class="rtable">{header_html}<tbody>{rows_html}</tbody></table>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="slbl">Full details — scroll or click a Rule ID above</div>',
            unsafe_allow_html=True,
        )

        # Per-rule verdict cards with anchor IDs
        for v in results.verdicts:
            v_cls = {
                "Pass": "vcard-pass", "Fail": "vcard-fail",
                "Partial": "vcard-partial", "Missing": "vcard-missing",
            }.get(v.verdict, "vcard-missing")

            stat_style = "display:flex;gap:28px;margin-top:12px;align-items:flex-end"
            def _stat(val, label, color):
                return (
                    f'<div><div style="font-size:20px;font-weight:700;color:{color}">'
                    f'{val:,}</div>'
                    f'<div style="font-size:10px;color:{t["muted"]};text-transform:uppercase;'
                    f'letter-spacing:.5px;margin-top:1px">{label}</div></div>'
                )

            st.markdown(
                f'<div id="vcard-{v.rule_id}" class="vcard {v_cls}">'
                # header row
                f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">'
                f'<span style="font-size:13px;font-weight:700;color:{t["accent"]};font-family:monospace">{v.rule_id}</span>'
                f'<div style="display:flex;gap:6px">{_badge(v.verdict)}&nbsp;{_risk_badge(v.risk)}</div>'
                f'</div>'
                # rule statement
                f'<div style="font-size:13px;color:{t["text"]};line-height:1.55;margin-bottom:8px">'
                f'{v.rule_statement}</div>'
                # compliance bar
                f'{_cbar(v.compliance_pct)}'
                # finding
                f'<div style="font-size:12px;color:{t["muted"]};margin:6px 0 10px;line-height:1.5">'
                f'{v.finding}</div>'
                # stats
                f'<div style="{stat_style}">'
                + _stat(v.pass_count,    "Pass",    "#22c55e")
                + _stat(v.fail_count,    "Fail",    "#ef4444")
                + _stat(v.missing_count, "Missing", t["muted"])
                + _stat(v.total_rows,    "Total",   t["text"])
                + f'<div style="margin-left:auto;text-align:right">'
                  f'<div style="font-size:24px;font-weight:700;color:{_bar_color(v.compliance_pct)}">'
                  f'{v.compliance_pct}%</div>'
                  f'<div style="font-size:10px;color:{t["muted"]};text-transform:uppercase">Compliance</div>'
                  f'</div>'
                + f'</div></div>',
                unsafe_allow_html=True,
            )

            if v.fail_examples:
                with st.expander(f"Sample failures — {v.rule_id}"):
                    st.dataframe(
                        pd.DataFrame(v.fail_examples),
                        use_container_width=True, hide_index=True,
                    )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Detailed Data
    # ══════════════════════════════════════════════════════════════════════════
    with tab_d:
        st.markdown(
            f'<div style="color:{t["text"]};font-size:13px;margin-bottom:16px;line-height:1.6">'
            f'This tab shows the <b>computation spec</b> generated per rule and the <b>raw traversal counts</b> '
            f'from scanning all {results.total_rows:,} rows — before any audit verdict is assigned.<br>'
            f'<span style="color:{t["muted"]}">Missing = data not found in that column for a row (not a violation). '
            f'If all rows show Missing, the column mapping may need review.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


        # ── Formula Checks ────────────────────────────────────────────────────
        formula_checks = [ch for ch in results.rule_checks if ch.check_type == "formula"]
        if formula_checks:
            st.markdown(
                f'<div class="slbl">Formula Checks — executed deterministically on every row (zero LLM)</div>',
                unsafe_allow_html=True,
            )
            for ch in formula_checks:
                fr = results.detailed_data.formula_results.get(ch.rule_id)

                col_display = f'"{ch.column_a}"'
                if ch.column_b:
                    col_display += f' → "{ch.column_b}"'

                formula_display = ch.computation or "—"
                if ch.computation == "date_difference":
                    formula_display = f"date_difference {ch.pass_condition} {ch.threshold}d"
                elif ch.computation == "value_contains":
                    formula_display = f"contains '{ch.pass_condition}'"
                elif ch.computation in ("not_blank", "is_blank"):
                    formula_display = ch.computation

                # warn if all missing (likely bad column mapping)
                all_missing = fr and fr.total > 0 and fr.passed == 0 and fr.failed == 0
                card_cls = "dcard dcard-warn" if all_missing else "dcard"
                warn_note = (
                    f'<div style="color:#f59e0b;font-size:11px;margin-top:6px;font-weight:600">'
                    f'All rows missing — column name may not match dataset. Check column mapping.</div>'
                ) if all_missing else ""

                pass_c  = fr.passed  if fr else 0
                fail_c  = fr.failed  if fr else 0
                miss_c  = fr.missing if fr else 0
                total_c = fr.total   if fr else 0
                pct     = fr.compliance_pct if fr else 0.0

                st.markdown(
                    f'<div class="{card_cls}">'
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                    f'<span class="dcard-id">{ch.rule_id}</span>'
                    f'<span class="badge b-low" style="font-size:10px">formula</span>'
                    f'</div>'
                    f'<div class="dcard-body">'
                    f'<span style="color:{t["muted"]}">Columns:</span> {col_display} &nbsp;|&nbsp; '
                    f'<span style="color:{t["muted"]}">Formula:</span> {formula_display}'
                    f'</div>'
                    f'<div class="dcard-meta" style="margin-top:6px">{ch.description}</div>'
                    f'<div style="display:flex;gap:20px;margin-top:10px">'
                    f'<span><b style="color:#22c55e">{pass_c:,}</b> <span style="color:{t["muted"]};font-size:11px">pass</span></span>'
                    f'<span><b style="color:#ef4444">{fail_c:,}</b> <span style="color:{t["muted"]};font-size:11px">fail</span></span>'
                    f'<span><b style="color:{t["muted"]}">{miss_c:,}</b> <span style="color:{t["muted"]};font-size:11px">missing</span></span>'
                    f'<span><b style="color:{t["text"]}">{total_c:,}</b> <span style="color:{t["muted"]};font-size:11px">total</span></span>'
                    f'<span style="margin-left:auto"><b style="color:{_bar_color(pct)}">{pct}%</b> <span style="color:{t["muted"]};font-size:11px">compliance</span></span>'
                    f'</div>'
                    f'{warn_note}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Judgment Checks ───────────────────────────────────────────────────
        judgment_checks = [ch for ch in results.rule_checks if ch.check_type == "judgment"]
        if judgment_checks:
            st.markdown(
                f'<div class="slbl" style="margin-top:18px">'
                f'Judgment Checks — LLM evaluated on sample rows</div>',
                unsafe_allow_html=True,
            )
            for ch in judgment_checks:
                jr = results.detailed_data.judgment_results.get(ch.rule_id)
                n_samples  = len(jr.samples)   if jr else 0
                n_total    = jr.total_rows      if jr else 0
                cols_str   = ", ".join(f'"{c}"' for c in ch.sample_columns) if ch.sample_columns else "—"

                st.markdown(
                    f'<div class="dcard">'
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                    f'<span class="dcard-id">{ch.rule_id}</span>'
                    f'<span class="badge b-medium" style="font-size:10px">judgment</span>'
                    f'</div>'
                    f'<div class="dcard-body">'
                    f'<span style="color:{t["muted"]}">Sampled:</span> {cols_str}'
                    f'</div>'
                    f'<div class="dcard-meta" style="margin-top:4px">'
                    f'<i>"{ch.judgment_question}"</i>'
                    f'</div>'
                    f'<div style="display:flex;gap:20px;margin-top:10px">'
                    f'<span><b style="color:{t["text"]}">{n_samples}</b> <span style="color:{t["muted"]};font-size:11px">samples collected</span></span>'
                    f'<span><b style="color:{t["text"]}">{n_total:,}</b> <span style="color:{t["muted"]};font-size:11px">total rows</span></span>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if jr and jr.samples:
                    with st.expander(f"View samples — {ch.rule_id}"):
                        st.dataframe(
                            pd.DataFrame(jr.samples),
                            use_container_width=True, hide_index=True,
                        )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — All Rules
    # ══════════════════════════════════════════════════════════════════════════
    with tab_r:
        st.markdown(
            f'<div class="slbl">'
            f'{len(results.applicable_rules)} applicable out of {len(results.all_rules)} extracted</div>',
            unsafe_allow_html=True,
        )
        for r in results.applicable_rules:
            tl = f"  ·  {r.timeline_days}d" if r.timeline_days else ""
            with st.expander(f"{r.rule_id}  ·  {r.rule_type.title()}{tl}"):
                st.markdown(
                    f'{_prio_badge(r.priority)}&nbsp;&nbsp;'
                    f'<span style="font-size:11px;color:{t["muted"]}">{r.rule_type.title()}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{r.statement}**")
                if r.keywords:
                    st.caption("Keywords: " + "  ·  ".join(r.keywords))

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4 — Column Map
    # ══════════════════════════════════════════════════════════════════════════
    with tab_c:
        st.markdown(
            f'<div class="slbl">'
            f'{len(results.audit_cols)} columns identified as audit-relevant</div>',
            unsafe_allow_html=True,
        )
        col_rows = [
            {
                "Column":  h,
                "Role":    results.col_map.get(h, {}).get("semantic_role", "—"),
                "Type":    results.col_map.get(h, {}).get("data_type", "—"),
                "Meaning": results.col_map.get(h, {}).get("meaning", "—"),
            }
            for h in results.audit_cols
        ]
        if col_rows:
            st.dataframe(pd.DataFrame(col_rows), use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 5 — Dropped Rules
    # ══════════════════════════════════════════════════════════════════════════
    with tab_drop:
        if results.dropped_rules:
            st.markdown(
                f'<div class="slbl">'
                f'{len(results.dropped_rules)} rules had no matching evidence in this dataset</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(
                pd.DataFrame([
                    {"Rule ID": rid, "Reason": reason}
                    for rid, reason in results.dropped_rules.items()
                ]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("All extracted rules were applicable to this dataset.")


# ── Router ─────────────────────────────────────────────────────────────────────
if st.session_state.page == "upload":
    page_upload()
else:
    page_results()
