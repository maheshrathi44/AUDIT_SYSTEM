"""AI Audit System — Streamlit frontend (full-dataset v2 pipeline)"""

import base64
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

_ASSETS = Path(__file__).parent / "assets"


def _real_logo_html(height: int = 82) -> str:
    """Return <img> tag with the real MSIL logo, or empty string if not found."""
    for fname in ("ms_logo.webp", "maruti_logo.png"):
        p = _ASSETS / fname
        if p.exists():
            mime = "image/webp" if fname.endswith(".webp") else "image/png"
            b64 = base64.b64encode(p.read_bytes()).decode()
            return (
                f'<img src="data:{mime};base64,{b64}" '
                f'style="height:{height}px;display:inline-block;vertical-align:middle;'
                f'object-fit:contain;margin-right:8px"/>'
            )
    return ""

# Maruti Suzuki hero emblem — Maruti bird + Suzuki S (no text, proper emblems)
_MSIL_LOGO_SVG = (
    '<svg viewBox="0 0 174 90" xmlns="http://www.w3.org/2000/svg" '
    'style="height:82px;display:block;width:auto">'

    # ── Maruti bird mark (blue) ──────────────────────────────────────────
    # Left inner feather
    '<path d="M43,86 C41,66 33,44 34,8 C38,22 41,50 43,68 Z" fill="#1B3A8A"/>'
    # Left outer feather
    '<path d="M43,86 C33,60 6,34 12,4 L34,8 C33,44 41,66 43,86 Z" fill="#1B3A8A"/>'
    # Right inner feather (mirror)
    '<path d="M47,86 C49,66 57,44 56,8 C52,22 49,50 47,68 Z" fill="#1B3A8A"/>'
    # Right outer feather (mirror)
    '<path d="M47,86 C57,60 84,34 78,4 L56,8 C57,44 49,66 47,86 Z" fill="#1B3A8A"/>'

    # ── Suzuki S mark (red) ──────────────────────────────────────────────
    '<g fill="#C8102E" transform="translate(96,4)">'
    # top parallelogram
    '<polygon points="2,0 54,0 46,38 -6,38"/>'
    # bottom parallelogram (offset right to form S)
    '<polygon points="16,44 68,44 60,82 8,82"/>'
    '</g>'

    '</svg>'
)

# Compact MSIL emblem — bird + S mark (used in nav header, small version)
_MSIL_EMBLEM_SVG = (
    '<svg viewBox="0 0 174 90" xmlns="http://www.w3.org/2000/svg" '
    'style="height:22px;display:inline-block;vertical-align:middle;margin-right:8px;width:auto">'
    '<path d="M43,86 C41,66 33,44 34,8 C38,22 41,50 43,68 Z" fill="#1B3A8A"/>'
    '<path d="M43,86 C33,60 6,34 12,4 L34,8 C33,44 41,66 43,86 Z" fill="#1B3A8A"/>'
    '<path d="M47,86 C49,66 57,44 56,8 C52,22 49,50 47,68 Z" fill="#1B3A8A"/>'
    '<path d="M47,86 C57,60 84,34 78,4 L56,8 C57,44 49,66 47,86 Z" fill="#1B3A8A"/>'
    '<g fill="#C8102E" transform="translate(96,4)">'
    '<polygon points="2,0 54,0 46,38 -6,38"/>'
    '<polygon points="16,44 68,44 60,82 8,82"/>'
    '</g>'
    '</svg>'
)

st.set_page_config(
    page_title="AI Audit System",
    layout="wide",
    initial_sidebar_state="collapsed",
)

for k, v in [
    ("page", "upload"), ("results", None), ("dark", False),
    ("phase1", None), ("phase2", None), ("phase3", None), ("audit_col_map", None),
]:
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

/* ── MSIL Upload Cards ── */
.upload-card-hdr {{
    background: {t['surface']}; border: 1px solid {t['border']};
    border-top: 3px solid {t['accent']};
    border-radius: 10px 10px 0 0; padding: 14px 18px 12px;
}}
.upload-card-icon {{ font-size: 22px; margin-bottom: 6px; }}
.upload-card-title {{ font-size: 13px; font-weight: 700; color: {t['text']}; }}
.upload-card-sub {{ font-size: 11px; color: {t['muted']}; margin-top: 2px; line-height: 1.4; }}

/* ── Check-type mini badge on verdict cards ── */
.check-type-lbl {{
    font-size: 9.5px; font-weight: 700; letter-spacing: .5px;
    text-transform: uppercase; padding: 2px 7px; border-radius: 20px;
    border: 1px solid {t['border']}; color: {t['muted']};
    background: {t['bg']};
}}
</style>
""", unsafe_allow_html=True)


# ── Shared helpers ─────────────────────────────────────────────────────────────
def _header(title: str, subtitle: str = "") -> None:
    c1, c2 = st.columns([7, 1])
    with c1:
        sub = f'<div class="app-sub">{subtitle}</div>' if subtitle else ""
        logo_html = _real_logo_html(28) or _MSIL_EMBLEM_SVG
        st.markdown(
            f'<div class="app-header"><div>'
            f'<div class="app-title">{logo_html}{title}</div>{sub}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        icon = "☀️" if st.session_state.dark else "🌙"
        if st.button(icon, key="theme_btn"):
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
    t = _c()
    _header("AI Audit System")

    # ── MSIL Professional Hero ──────────────────────────────────────────────────
    dark = st.session_state.dark
    hero_bg   = "#140808" if dark else "#fff8f8"
    hero_bg2  = "#0f0505" if dark else "#ffe8e8"
    txt_brand = "#ff6b6b" if dark else "#C8102E"

    st.markdown(
        f'<div style="background:linear-gradient(135deg,{hero_bg} 0%,{hero_bg2} 100%);'
        f'border:1px solid {t["border"]};border-left:5px solid #C8102E;'
        f'border-radius:14px;padding:28px 36px;margin-bottom:32px;'
        f'display:flex;align-items:center;gap:32px">'

        # ── Logo ────────────────────────────────────────────────────────────
        f'<div style="flex-shrink:0;padding-right:4px">'
        + (_real_logo_html(82) or _MSIL_LOGO_SVG)
        + f'</div>'

        # ── Brand text ───────────────────────────────────────────────────────
        f'<div style="flex:1">'
        f'<div style="font-size:10px;font-weight:800;color:{txt_brand};'
        f'letter-spacing:2.5px;text-transform:uppercase;margin-bottom:5px">'
        f'Maruti Suzuki India Limited</div>'
        f'<div style="font-size:26px;font-weight:800;color:{t["text"]};'
        f'line-height:1.15;letter-spacing:-.5px;margin-bottom:7px">'
        f'AI Compliance<br>Audit System</div>'
        f'<div style="font-size:12.5px;color:{t["muted"]};line-height:1.6">'
        f'Quality Assurance &amp; Quality Department'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;Automated full-dataset compliance verification'
        f'</div>'
        f'</div>'

        # ── Feature list ─────────────────────────────────────────────────────
        f'<div style="flex-shrink:0;display:flex;flex-direction:column;gap:10px;'
        f'border-left:1px solid {t["border"]};padding-left:32px;min-width:210px">'
        + "".join(
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:#C8102E;'
            f'flex-shrink:0;display:inline-block"></span>'
            f'<span style="font-size:12px;color:{t["muted"]}">{step}</span>'
            f'</div>'
            for step in [
                "Extract rules from procedures",
                "Intelligent column mapping",
                "Automated compliance verdicts",
                "Executive audit report",
            ]
        )
        + f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Upload section ──────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="slbl" style="margin-bottom:14px">Upload Files to Begin</div>',
        unsafe_allow_html=True,
    )

    c_proc, c_data, c_supp = st.columns(3, gap="medium")

    with c_proc:
        st.markdown(
            f'<div class="upload-card-hdr" style="border-top-color:#C8102E">'
            f'<div class="upload-card-icon">📋</div>'
            f'<div class="upload-card-title">Procedure Documents</div>'
            f'<div class="upload-card-sub">Standard operating procedures, work instructions, '
            f'quality manuals — any document containing auditable rules.</div>'
            f'<div style="margin-top:8px;font-size:10.5px;color:{t["muted"]}">'
            f'PDF · DOCX · TXT · MD</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        proc_files = st.file_uploader(
            "procedures",
            type=["pdf", "docx", "txt", "md"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

    with c_data:
        st.markdown(
            f'<div class="upload-card-hdr" style="border-top-color:{t["accent"]}">'
            f'<div class="upload-card-icon">📊</div>'
            f'<div class="upload-card-title">Audit Dataset</div>'
            f'<div class="upload-card-sub">The spreadsheet containing records to be verified. '
            f'All rows are traversed — no sampling.</div>'
            f'<div style="margin-top:8px;font-size:10.5px;color:{t["muted"]}">'
            f'XLSX only</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        dataset_file = st.file_uploader(
            "dataset",
            type=["xlsx"],
            label_visibility="collapsed",
        )

    with c_supp:
        st.markdown(
            f'<div class="upload-card-hdr" style="border-top-color:{t["muted"]}">'
            f'<div class="upload-card-icon">📎</div>'
            f'<div class="upload-card-title">Reference Documents <span style="font-size:10px;'
            f'font-weight:400;color:{t["muted"]}">Optional</span></div>'
            f'<div class="upload-card-sub">Forms, checklists, or certificates that your '
            f'procedure expects to be present. Filename must match the dataset column exactly.</div>'
            f'<div style="margin-top:8px;font-size:10.5px;color:{t["muted"]}">'
            f'PDF · DOCX</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
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
                f'{name_pills}'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)
    ready = bool(proc_files and dataset_file)
    if not ready:
        st.markdown(
            f'<div style="font-size:12px;color:{t["muted"]};text-align:center;'
            f'padding:6px 0 2px">Upload at least one procedure document and a dataset to continue.</div>',
            unsafe_allow_html=True,
        )

    if st.button("Run Audit  →", type="primary", disabled=not ready):
        doc_names = [f.name for f in supp_files] if supp_files else []
        _run_pipeline_phase1(proc_files, dataset_file, doc_names)


def _run_pipeline_phase1(proc_files, dataset_file, doc_names=None) -> None:
    status   = st.empty()
    progress = st.progress(0)

    def log(msg: str) -> None:
        status.info(msg)
        low = msg.lower()
        if "step 1" in low or "extract" in low: progress.progress(15)
        elif "rules extracted" in low:           progress.progress(40)
        elif "step 2" in low or "read" in low:  progress.progress(55)
        elif "rows loaded" in low:              progress.progress(70)
        elif "column mapping" in low:           progress.progress(90)

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
            from audit.pipeline_v2 import run_pipeline_phase1
            phase1 = run_pipeline_phase1(
                proc_paths, ds_path,
                supported_doc_names=doc_names or [],
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
    st.session_state.phase1 = phase1
    st.session_state.page   = "col_review"
    st.rerun()


def _run_pipeline_phase2(phase1, col_map: dict) -> None:
    """Runs step 3 (rule filter) then goes to rule_review page."""
    status   = st.empty()
    progress = st.progress(0)

    def log(msg: str) -> None:
        status.info(msg)
        low = msg.lower()
        if "filter" in low:    progress.progress(40)
        elif "applicable" in low: progress.progress(80)

    try:
        from audit.pipeline_v2 import run_pipeline_phase2
        phase2 = run_pipeline_phase2(phase1, col_map, on_progress=log)
    except Exception as e:
        status.empty()
        progress.empty()
        st.error(f"Rule filtering failed: {e}")
        return

    progress.progress(100)
    status.empty()
    progress.empty()
    st.session_state.audit_col_map = col_map
    st.session_state.phase2        = phase2
    st.session_state.page          = "rule_review"
    st.rerun()


def _run_pipeline_phase3(phase1, col_map: dict, applicable_rules, dropped_rules: dict) -> None:
    """Runs step 4 (rule check generation) then goes to rule_check_review page."""
    status   = st.empty()
    progress = st.progress(0)

    def log(msg: str) -> None:
        status.info(msg)
        low = msg.lower()
        if "generating" in low:   progress.progress(20)
        elif "formula check" in low: progress.progress(60)
        elif "review" in low:     progress.progress(90)

    try:
        from audit.pipeline_v2 import run_pipeline_phase3
        phase3 = run_pipeline_phase3(
            phase1, col_map, applicable_rules, dropped_rules,
            on_progress=log,
        )
    except Exception as e:
        status.empty()
        progress.empty()
        st.error(f"Rule check generation failed: {e}")
        return

    progress.progress(100)
    status.empty()
    progress.empty()
    st.session_state.phase3 = phase3
    st.session_state.page   = "rule_check_review"
    st.rerun()


def _run_pipeline_phase4(phase1, col_map: dict, rule_checks, applicable_rules, dropped_rules: dict) -> None:
    """Runs steps 5-7 (traverse, verdicts, report) then goes to results page."""
    status   = st.empty()
    progress = st.progress(0)

    def log(msg: str) -> None:
        status.info(msg)
        low = msg.lower()
        if "step 1" in low or "travers" in low:  progress.progress(20)
        elif "traversal complete" in low:        progress.progress(55)
        elif "step 2" in low or "verdict" in low: progress.progress(70)
        elif "step 3" in low or "report" in low:  progress.progress(90)

    try:
        from audit.pipeline_v2 import run_pipeline_phase4
        results = run_pipeline_phase4(
            phase1, col_map, rule_checks, applicable_rules, dropped_rules,
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
    st.session_state.results       = results
    st.session_state.phase1        = None
    st.session_state.phase2        = None
    st.session_state.phase3        = None
    st.session_state.audit_col_map = None
    st.session_state.page          = "results"
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Column Mapping Review
# ══════════════════════════════════════════════════════════════════════════════

_COL_ROLES = [
    "date_reported", "date_closed", "date_received", "date_replied",
    "date_approved", "date_deadline", "date_other",
    "case_id", "reopen_indicator", "status", "category",
    "description", "identifier", "document_ref", "numeric", "other",
]
_COL_TYPES = ["date", "text", "number", "status", "id", "boolean"]


def page_col_review() -> None:
    _inject_css()
    t      = _c()
    phase1 = st.session_state.phase1

    _header("Column Mapping Review",
            "Step 2 of 3 — Verify AI-generated column meanings before running the audit")

    n_total    = len(phase1.headers)
    n_relevant = sum(1 for h in phase1.headers if phase1.col_map.get(h, {}).get("audit_relevant"))

    st.markdown(
        f'<div style="background:{t["surface"]};border:1px solid {t["border"]};'
        f'border-left:4px solid {t["accent"]};border-radius:10px;'
        f'padding:14px 18px;margin-bottom:18px;font-size:13px;color:{t["text"]};line-height:1.6">'
        f'The AI has mapped <b>{n_total}</b> columns and marked <b>{n_relevant}</b> as audit-relevant. '
        f'Review each row below — correct meanings, adjust roles, and uncheck <b>Include in Audit</b> '
        f'for columns that should not be used in compliance checks. '
        f'<span style="color:{t["muted"]}">Changes here directly affect which rules run and how columns are matched.</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    rows = []
    for col in phase1.headers:
        info = phase1.col_map.get(col, {})
        rows.append({
            "Column":           col,
            "Meaning":          info.get("meaning", ""),
            "Semantic Role":    info.get("semantic_role", "other"),
            "Data Type":        info.get("data_type", "text"),
            "Include in Audit": True,
        })

    edited_df = st.data_editor(
        pd.DataFrame(rows),
        column_config={
            "Column":           st.column_config.TextColumn("Column", disabled=True, width="medium"),
            "Meaning":          st.column_config.TextColumn("Meaning (edit if wrong)", width="large"),
            "Semantic Role":    st.column_config.SelectboxColumn("Semantic Role", options=_COL_ROLES, width="medium"),
            "Data Type":        st.column_config.SelectboxColumn("Data Type", options=_COL_TYPES, width="small"),
            "Include in Audit": st.column_config.CheckboxColumn("Include in Audit", width="small"),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="col_editor",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    cb, _, cp = st.columns([1, 4, 2])

    with cb:
        if st.button("← Back", key="col_back_btn"):
            st.session_state.page   = "upload"
            st.session_state.phase1 = None
            st.rerun()

    with cp:
        if st.button("Proceed with Audit  →", type="primary", key="col_proceed_btn"):
            updated_col_map: dict = {}
            for _, row in edited_df.iterrows():
                col_name = row["Column"]
                updated_col_map[col_name] = {
                    "meaning":       row["Meaning"],
                    "semantic_role": row["Semantic Role"],
                    "data_type":     row["Data Type"],
                    "audit_relevant": bool(row["Include in Audit"]),
                }
            _run_pipeline_phase2(phase1, updated_col_map)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Rule Review
# ══════════════════════════════════════════════════════════════════════════════

_RULE_TYPES = [
    "mandatory", "conditional", "timeline",
    "document", "process", "quality", "other",
]
_PRIORITIES = ["Critical", "High", "Medium", "Low"]


def _rr_init(phase1, phase2) -> None:
    """Initialise or reset rule-review session state from phase2 results."""
    all_by_id = {r.rule_id: r for r in phase1.all_rules}
    applicable = [
        {
            "Rule ID":   r.rule_id,
            "Statement": r.statement,
            "Type":      r.rule_type,
            "Priority":  r.priority.title(),
        }
        for r in phase2.applicable_rules
    ]
    dropped = [
        {
            "Rule ID":     rid,
            "Statement":   all_by_id[rid].statement if rid in all_by_id else "",
            "Drop Reason": reason,
        }
        for rid, reason in phase2.dropped_rules.items()
        if rid in all_by_id
    ]
    st.session_state.rr_applicable = applicable
    st.session_state.rr_dropped    = dropped
    st.session_state.rr_phase2_id  = id(phase2)
    st.session_state.rr_version    = 0   # bump to force data_editor reset


def page_rule_review() -> None:
    import dataclasses

    _inject_css()
    t       = _c()
    phase1  = st.session_state.phase1
    phase2  = st.session_state.phase2
    col_map = st.session_state.audit_col_map or phase1.col_map

    # Initialise live lists on first visit (or when phase2 changes)
    if (
        "rr_applicable" not in st.session_state
        or st.session_state.get("rr_phase2_id") != id(phase2)
    ):
        _rr_init(phase1, phase2)

    rr_app  = st.session_state.rr_applicable   # list[dict]
    rr_drop = st.session_state.rr_dropped       # list[dict]
    ver     = st.session_state.rr_version

    _header("Rule Review",
            "Step 3 of 4 — Review, edit and move rules freely before running the audit")

    st.markdown(
        f'<div style="background:{t["surface"]};border:1px solid {t["border"]};'
        f'border-left:4px solid {t["accent"]};border-radius:10px;'
        f'padding:14px 18px;margin-bottom:18px;font-size:13px;color:{t["text"]};line-height:1.6">'
        f'<b>{len(rr_app)}</b> applicable &nbsp;·&nbsp; <b>{len(rr_drop)}</b> dropped. '
        f'Edit statements inline. Use <b>Move to Dropped / Restore to Applicable</b> to transfer rules '
        f'between sections — you can do this as many times as needed before proceeding.'
        f'</div>',
        unsafe_allow_html=True,
    )

    tab_app, tab_drop = st.tabs([
        f"Applicable Rules  ({len(rr_app)})",
        f"Dropped Rules  ({len(rr_drop)})",
    ])

    # ── Applicable tab ──────────────────────────────────────────────────────
    with tab_app:
        edited_app = st.data_editor(
            pd.DataFrame(rr_app) if rr_app else pd.DataFrame(
                columns=["Rule ID", "Statement", "Type", "Priority"]
            ),
            column_config={
                "Rule ID":   st.column_config.TextColumn("Rule ID",   disabled=True, width="small"),
                "Statement": st.column_config.TextColumn("Statement (edit if needed)", width="large"),
                "Type":      st.column_config.SelectboxColumn("Type",     options=_RULE_TYPES, width="small"),
                "Priority":  st.column_config.SelectboxColumn("Priority", options=_PRIORITIES, width="small"),
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key=f"rr_app_editor_{ver}",
        )
        # Always sync edits back so moves preserve the latest text
        st.session_state.rr_applicable = edited_app.to_dict("records")

        if rr_app:
            st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
            sel_drop, btn_drop = st.columns([5, 1])
            with sel_drop:
                to_drop = st.multiselect(
                    "Select rules to move to Dropped:",
                    options=[r["Rule ID"] for r in st.session_state.rr_applicable],
                    key=f"rr_to_drop_{ver}",
                )
            with btn_drop:
                st.markdown("<div style='margin-top:22px'></div>", unsafe_allow_html=True)
                if st.button("→ Drop", key=f"rr_btn_drop_{ver}", disabled=not to_drop):
                    ids = set(to_drop)
                    moving  = [r for r in st.session_state.rr_applicable if r["Rule ID"] in ids]
                    staying = [r for r in st.session_state.rr_applicable if r["Rule ID"] not in ids]
                    for r in moving:
                        r["Drop Reason"] = "moved to dropped by user"
                    st.session_state.rr_applicable = staying
                    st.session_state.rr_dropped.extend(moving)
                    st.session_state.rr_version += 1
                    st.rerun()

    # ── Dropped tab ─────────────────────────────────────────────────────────
    with tab_drop:
        drop_cols = ["Rule ID", "Statement", "Drop Reason"]
        edited_drop = st.data_editor(
            pd.DataFrame(rr_drop)[drop_cols] if rr_drop else pd.DataFrame(columns=drop_cols),
            column_config={
                "Rule ID":     st.column_config.TextColumn("Rule ID",     disabled=True, width="small"),
                "Statement":   st.column_config.TextColumn("Statement (edit if needed)", width="large"),
                "Drop Reason": st.column_config.TextColumn("Reason", disabled=True, width="medium"),
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key=f"rr_drop_editor_{ver}",
        )
        # Sync statement edits back (reason stays from session state)
        if rr_drop:
            edited_stmts = {row["Rule ID"]: row["Statement"] for _, row in edited_drop.iterrows()}
            for r in st.session_state.rr_dropped:
                if r["Rule ID"] in edited_stmts:
                    r["Statement"] = edited_stmts[r["Rule ID"]]

        if rr_drop:
            st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
            sel_rest, btn_rest = st.columns([5, 1])
            with sel_rest:
                to_restore = st.multiselect(
                    "Select rules to restore to Applicable:",
                    options=[r["Rule ID"] for r in st.session_state.rr_dropped],
                    key=f"rr_to_restore_{ver}",
                )
            with btn_rest:
                st.markdown("<div style='margin-top:22px'></div>", unsafe_allow_html=True)
                if st.button("← Restore", key=f"rr_btn_restore_{ver}", disabled=not to_restore):
                    ids = set(to_restore)
                    moving  = [r for r in st.session_state.rr_dropped if r["Rule ID"] in ids]
                    staying = [r for r in st.session_state.rr_dropped if r["Rule ID"] not in ids]
                    for r in moving:
                        r_clean = {k: v for k, v in r.items() if k != "Drop Reason"}
                        st.session_state.rr_applicable.append(r_clean)
                    st.session_state.rr_dropped = staying
                    st.session_state.rr_version += 1
                    st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    cb, _, cp = st.columns([1, 4, 2])

    with cb:
        if st.button("← Back", key="rule_back_btn"):
            st.session_state.page   = "col_review"
            st.session_state.phase2 = None
            for k in ("rr_applicable", "rr_dropped", "rr_phase2_id", "rr_version"):
                st.session_state.pop(k, None)
            st.rerun()

    with cp:
        if st.button("Proceed with Audit  →", type="primary", key="rule_proceed_btn"):
            all_by_id = {r.rule_id: r for r in phase1.all_rules}
            final_applicable = []
            final_dropped    = {r["Rule ID"]: r["Drop Reason"] for r in st.session_state.rr_dropped}

            for row in st.session_state.rr_applicable:
                rid = row["Rule ID"]
                r   = all_by_id.get(rid)
                if r:
                    final_applicable.append(dataclasses.replace(
                        r,
                        statement=str(row["Statement"]),
                        rule_type=str(row.get("Type", r.rule_type)),
                        priority=str(row.get("Priority", r.priority)).lower(),
                    ))

            # Clean up rule-review state
            for k in ("rr_applicable", "rr_dropped", "rr_phase2_id", "rr_version"):
                st.session_state.pop(k, None)

            _run_pipeline_phase3(phase1, col_map, final_applicable, final_dropped)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — Rule Check Review
# ══════════════════════════════════════════════════════════════════════════════

def _render_filter_ui(rid: str, check, col_opts: list, phase1) -> None:
    """
    Multi-condition AND filter UI. Conditions stored in session state.
    Bumps a version counter on add/remove so widget keys reset cleanly.
    """
    _NONE_OPT = col_opts[0]  # "(none)"
    fcond_key = f"rc_{rid}_fconds"
    fcver_key = f"rc_{rid}_fcv"

    if fcond_key not in st.session_state:
        if check.filter_column and check.filter_column in col_opts:
            st.session_state[fcond_key] = [{"col": check.filter_column, "val": check.filter_value or ""}]
        else:
            st.session_state[fcond_key] = []
    if fcver_key not in st.session_state:
        st.session_state[fcver_key] = 0

    fconds = st.session_state[fcond_key]
    fcver  = st.session_state[fcver_key]

    show_filter = st.checkbox(
        "Add conditional filter — only evaluate rows where column(s) match value(s) [AND logic]",
        value=bool(fconds),
        key=f"rc_{rid}_show_filter",
    )
    if not show_filter:
        if fconds:
            st.session_state[fcond_key] = []
        return

    if not fconds:
        st.session_state[fcond_key] = [{"col": _NONE_OPT, "val": ""}]
        fconds = st.session_state[fcond_key]

    def _save(fconds: list, rid: str, ver: int) -> None:
        for j in range(len(fconds)):
            fconds[j]["col"] = st.session_state.get(f"rc_{rid}_fccol_{j}_{ver}", fconds[j]["col"])
            fconds[j]["val"] = st.session_state.get(f"rc_{rid}_fcval_{j}_{ver}", fconds[j]["val"])

    for i, cond in enumerate(list(fconds)):
        fc1, fc2, fc3 = st.columns([3, 3, 1])
        with fc1:
            fcol_idx = col_opts.index(cond["col"]) if cond["col"] in col_opts else 0
            st.selectbox(
                f"Column {i+1}", col_opts, index=fcol_idx,
                key=f"rc_{rid}_fccol_{i}_{fcver}",
            )
        with fc2:
            sel_col = st.session_state.get(f"rc_{rid}_fccol_{i}_{fcver}", cond["col"]) or ""
            if sel_col and sel_col != _NONE_OPT:
                dist_vals = list(dict.fromkeys(
                    str(r.get(sel_col) or "").strip()
                    for r in phase1.rows
                    if str(r.get(sel_col) or "").strip()
                ))
            else:
                dist_vals = []
            fv_opts = ["(blank)", "(not blank)"] + dist_vals
            cur_val = cond["val"] if cond["val"] in fv_opts else (fv_opts[0] if fv_opts else "")
            st.selectbox(
                f"Value {i+1}", fv_opts,
                index=fv_opts.index(cur_val) if cur_val in fv_opts else 0,
                key=f"rc_{rid}_fcval_{i}_{fcver}",
            )
        with fc3:
            st.markdown("<div style='margin-top:26px'></div>", unsafe_allow_html=True)
            if len(fconds) > 1 and st.button("✕", key=f"rc_{rid}_fcrm_{i}_{fcver}"):
                _save(fconds, rid, fcver)
                fconds.pop(i)
                st.session_state[fcver_key] += 1
                st.rerun()

    if st.button("+ Add AND condition", key=f"rc_{rid}_fcadd_{fcver}"):
        _save(fconds, rid, fcver)
        fconds.append({"col": _NONE_OPT, "val": ""})
        st.session_state[fcver_key] += 1
        st.rerun()

_COMPUTATIONS = ["not_blank", "is_blank", "date_difference", "value_contains"]
_COMP_LABELS  = {
    "not_blank":       "not_blank — field must be filled",
    "is_blank":        "is_blank — field must be empty",
    "date_difference": "date_difference — gap between two date columns",
    "value_contains":  "value_contains — column must contain a keyword",
}


def page_rule_check_review() -> None:
    import dataclasses

    _inject_css()
    t      = _c()
    phase1 = st.session_state.phase1
    phase3 = st.session_state.phase3
    col_map = st.session_state.audit_col_map or phase1.col_map

    audit_cols = phase3.audit_cols   # ordered list of kept columns
    _NONE      = "(none)"
    col_opts   = [_NONE] + audit_cols

    _header("Rule Check Review",
            "Step 4 of 5 — Verify how each rule will be computed before running the audit")

    f_count = sum(1 for c in phase3.rule_checks if c.check_type == "formula")
    j_count = sum(1 for c in phase3.rule_checks if c.check_type == "judgment")

    st.markdown(
        f'<div style="background:{t["surface"]};border:1px solid {t["border"]};'
        f'border-left:4px solid {t["accent"]};border-radius:10px;'
        f'padding:14px 18px;margin-bottom:6px;font-size:13px;color:{t["text"]};line-height:1.7">'
        f'<b>{f_count} formula</b> checks and <b>{j_count} judgment</b> checks were generated. '
        f'Review each one — change the check type, formula, or columns if the AI got it wrong. '
        f'Your changes are applied exactly to the audit.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Legend
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div style="background:{t["pass_bg"]};border:1px solid {t["border"]};'
            f'border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:{t["text"]}">'
            f'<b style="color:{t["pass_fg"]}">Formula</b> — deterministic, runs on every row, '
            f'zero LLM. Checks a specific column or date gap. Fast and exact.'
            f'</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div style="background:{t["miss_bg"]};border:1px solid {t["border"]};'
            f'border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:{t["text"]}">'
            f'<b style="color:{t["miss_fg"]}">Judgment</b> — AI reads a sample of rows and '
            f'estimates compliance. Use when a formula cannot capture the rule intent.'
            f'</div>', unsafe_allow_html=True)

    # ── One expander per rule check ──────────────────────────────────────────
    for check in phase3.rule_checks:
        rid    = check.rule_id
        is_fml = st.session_state.get(f"rc_{rid}_type", check.check_type) == "formula"

        exp_label = (
            f"{rid}  ·  "
            + ("formula" if is_fml else "judgment")
            + (f"  ·  {check.computation}" if is_fml and check.computation else "")
        )
        with st.expander(exp_label):
            st.markdown(
                f'<div style="font-size:12.5px;color:{t["muted"]};'
                f'margin-bottom:10px;line-height:1.5">{check.rule.statement}</div>',
                unsafe_allow_html=True,
            )

            # Check type toggle
            cur_type = st.radio(
                "Check type",
                ["formula", "judgment"],
                index=0 if check.check_type == "formula" else 1,
                key=f"rc_{rid}_type",
                horizontal=True,
            )
            is_fml = cur_type == "formula"
            st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

            if is_fml:
                ca, cb = st.columns(2)
                with ca:
                    comp_idx = _COMPUTATIONS.index(check.computation) if check.computation in _COMPUTATIONS else 0
                    comp = st.selectbox(
                        "Computation",
                        options=_COMPUTATIONS,
                        format_func=lambda x: _COMP_LABELS.get(x, x),
                        index=comp_idx,
                        key=f"rc_{rid}_comp",
                    )
                with cb:
                    cola_idx = col_opts.index(check.column_a) if check.column_a in col_opts else 0
                    st.selectbox("Column A (main column)", col_opts, index=cola_idx, key=f"rc_{rid}_col_a")

                if st.session_state.get(f"rc_{rid}_comp", comp) == "date_difference":
                    cd, ce, cf = st.columns(3)
                    with cd:
                        colb_idx = col_opts.index(check.column_b) if check.column_b in col_opts else 0
                        st.selectbox("Column B (end date)", col_opts, index=colb_idx, key=f"rc_{rid}_col_b")
                    with ce:
                        st.selectbox("Condition", ["<=", ">="],
                                     index=0 if check.pass_condition != ">=" else 1,
                                     key=f"rc_{rid}_cond")
                    with cf:
                        st.number_input("Threshold (days)", min_value=1,
                                        value=int(check.threshold or 7),
                                        key=f"rc_{rid}_threshold")

                elif st.session_state.get(f"rc_{rid}_comp", comp) == "value_contains":
                    st.text_input("Must contain (keyword / value)",
                                  value=check.pass_condition or "",
                                  key=f"rc_{rid}_cond")

                # Conditional filter (multi-column AND)
                _render_filter_ui(rid, check, col_opts, phase1)

            else:
                # Judgment fields
                default_samp = [c for c in check.sample_columns if c in audit_cols]
                st.multiselect("Sample columns (columns the AI will read to evaluate this rule)",
                               options=audit_cols, default=default_samp, key=f"rc_{rid}_sample_cols")
                st.text_area("Judgment question",
                             value=check.judgment_question or "",
                             height=70, key=f"rc_{rid}_question")

                # Optional filter for judgment checks (multi-condition)
                _render_filter_ui(rid, check, col_opts, phase1)

    st.markdown("<br>", unsafe_allow_html=True)
    cb_btn, _, cp_btn = st.columns([1, 4, 2])

    with cb_btn:
        if st.button("← Back", key="rcr_back_btn"):
            st.session_state.page   = "rule_review"
            st.session_state.phase3 = None
            st.rerun()

    with cp_btn:
        if st.button("Proceed with Audit  →", type="primary", key="rcr_proceed_btn"):

            def _read_filter_conds(rid: str) -> list[dict]:
                """Read multi-condition filter from session state for a given rule id."""
                show_f = st.session_state.get(f"rc_{rid}_show_filter", False)
                if not show_f:
                    return []
                fconds = st.session_state.get(f"rc_{rid}_fconds", [])
                fcver  = st.session_state.get(f"rc_{rid}_fcv", 0)
                result = []
                for i, cond in enumerate(fconds):
                    col = st.session_state.get(f"rc_{rid}_fccol_{i}_{fcver}", cond.get("col", ""))
                    val = st.session_state.get(f"rc_{rid}_fcval_{i}_{fcver}", cond.get("val", ""))
                    if col and col != _NONE and val:
                        result.append({"column": col, "value": val})
                return result

            final_checks = []
            for check in phase3.rule_checks:
                rid      = check.rule_id
                new_type = st.session_state.get(f"rc_{rid}_type", check.check_type)
                filter_conditions = _read_filter_conds(rid)
                fc1 = filter_conditions[0] if filter_conditions else {}

                if new_type == "formula":
                    col_a = st.session_state.get(f"rc_{rid}_col_a", check.column_a)
                    col_b = st.session_state.get(f"rc_{rid}_col_b", check.column_b)
                    comp  = st.session_state.get(f"rc_{rid}_comp",  check.computation)
                    cond  = st.session_state.get(f"rc_{rid}_cond",  check.pass_condition)
                    thr   = st.session_state.get(f"rc_{rid}_threshold", check.threshold)
                    final_checks.append(dataclasses.replace(
                        check,
                        check_type        = "formula",
                        column_a          = "" if col_a == _NONE else (col_a or ""),
                        column_b          = "" if col_b == _NONE else (col_b or ""),
                        computation       = comp or "",
                        pass_condition    = str(cond) if cond is not None else "",
                        threshold         = int(thr) if thr is not None else None,
                        filter_column     = fc1.get("column", ""),
                        filter_value      = fc1.get("value", ""),
                        filter_conditions = filter_conditions,
                        sample_columns    = [],
                        judgment_question = "",
                    ))
                else:
                    samp_cols = st.session_state.get(f"rc_{rid}_sample_cols", check.sample_columns)
                    question  = st.session_state.get(f"rc_{rid}_question", check.judgment_question)
                    final_checks.append(dataclasses.replace(
                        check,
                        check_type        = "judgment",
                        sample_columns    = list(samp_cols) if samp_cols else [],
                        judgment_question = question or "",
                        column_a          = "", column_b="", computation="",
                        pass_condition    = "", threshold=None,
                        filter_column     = fc1.get("column", ""),
                        filter_value      = fc1.get("value", ""),
                        filter_conditions = filter_conditions,
                    ))

            _run_pipeline_phase4(
                phase1, col_map, final_checks,
                phase3.applicable_rules, dict(phase3.dropped_rules),
            )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — Results
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
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'<span style="font-size:13px;font-weight:700;color:{t["accent"]};font-family:monospace">{v.rule_id}</span>'
                f'<span class="check-type-lbl">{v.check_type}</span>'
                f'</div>'
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
                with st.expander(f"⚠ Sample failures ({len(v.fail_examples)}) — {v.rule_id}"):
                    st.dataframe(pd.DataFrame(v.fail_examples), use_container_width=True, hide_index=True)

            if v.pass_examples:
                with st.expander(f"✓ Sample passes ({len(v.pass_examples)}) — {v.rule_id}"):
                    st.dataframe(pd.DataFrame(v.pass_examples), use_container_width=True, hide_index=True)

            if v.miss_examples:
                with st.expander(f"– Sample missing ({len(v.miss_examples)}) — {v.rule_id}"):
                    st.dataframe(pd.DataFrame(v.miss_examples), use_container_width=True, hide_index=True)

            if v.samples:
                with st.expander(f"📋 All rows evaluated ({len(v.samples)}) — {v.rule_id}"):
                    st.dataframe(pd.DataFrame(v.samples), use_container_width=True, hide_index=True)

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

                filter_display = ""
                if ch.filter_column and ch.filter_value:
                    filter_display = (
                        f'<div style="font-size:11.5px;color:{t["muted"]};margin-top:3px">'
                        f'Only when <b style="color:{t["text"]}">{ch.filter_column}</b>'
                        f' = <b style="color:{t["accent"]}">{ch.filter_value}</b>'
                        f' &nbsp;·&nbsp; other rows counted as missing (pass)</div>'
                    )

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
                    f'{filter_display}'
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
                n_total    = jr.total_rows      if jr else 0
                cols_str   = ", ".join(f'"{c}"' for c in ch.sample_columns) if ch.sample_columns else "—"

                n_missing  = jr.missing if jr else 0
                n_applicable = n_total - n_missing
                jfilter_display = ""
                if ch.filter_column and ch.filter_value:
                    jfilter_display = (
                        f'<div style="font-size:11.5px;color:{t["muted"]};margin-top:3px">'
                        f'Filter: <b style="color:{t["text"]}">{ch.filter_column}</b>'
                        f' = <b style="color:{t["accent"]}">{ch.filter_value}</b>'
                        f' &nbsp;·&nbsp; {n_missing:,} rows not applicable (excluded from compliance)</div>'
                    )

                # Pull verdict for this rule to show pass/fail counts
                jv = next((v for v in results.verdicts if v.rule_id == ch.rule_id), None)
                j_pass = jv.pass_count if jv else 0
                j_fail = jv.fail_count if jv else 0

                st.markdown(
                    f'<div class="dcard">'
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                    f'<span class="dcard-id">{ch.rule_id}</span>'
                    f'<span class="badge b-medium" style="font-size:10px">judgment</span>'
                    f'</div>'
                    f'<div class="dcard-body">'
                    f'<span style="color:{t["muted"]}">Columns:</span> {cols_str}'
                    f'</div>'
                    f'{jfilter_display}'
                    f'<div class="dcard-meta" style="margin-top:4px">'
                    f'<i>"{ch.judgment_question}"</i>'
                    f'</div>'
                    f'<div style="display:flex;gap:20px;margin-top:10px">'
                    f'<span><b style="color:#22c55e">{j_pass:,}</b> <span style="color:{t["muted"]};font-size:11px">pass</span></span>'
                    f'<span><b style="color:#ef4444">{j_fail:,}</b> <span style="color:{t["muted"]};font-size:11px">fail</span></span>'
                    f'<span><b style="color:{t["muted"]}">{n_missing:,}</b> <span style="color:{t["muted"]};font-size:11px">not applicable</span></span>'
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
        applicable_ids = {r.rule_id for r in results.applicable_rules}
        dropped_ids    = set(results.dropped_rules.keys())
        st.markdown(
            f'<div class="slbl">'
            f'{len(results.all_rules)} total · '
            f'{len(results.applicable_rules)} applicable · '
            f'{len(dropped_ids)} dropped</div>',
            unsafe_allow_html=True,
        )
        for r in results.all_rules:
            tl = f"  ·  {r.timeline_days}d" if r.timeline_days else ""
            if r.rule_id in applicable_ids:
                status_badge = f'<span class="badge b-pass" style="font-size:9px">applicable</span>'
            else:
                status_badge = f'<span class="badge b-fail" style="font-size:9px">dropped</span>'
            with st.expander(f"{r.rule_id}  ·  {r.rule_type.title()}{tl}"):
                st.markdown(
                    f'{status_badge}&nbsp;&nbsp;'
                    f'{_prio_badge(r.priority)}&nbsp;&nbsp;'
                    f'<span style="font-size:11px;color:{t["muted"]}">{r.rule_type.title()}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{r.statement}**")
                if r.rule_id in dropped_ids:
                    st.caption(f"Dropped: {results.dropped_rules[r.rule_id]}")
                elif r.keywords:
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
elif st.session_state.page == "col_review":
    page_col_review()
elif st.session_state.page == "rule_review":
    page_rule_review()
elif st.session_state.page == "rule_check_review":
    page_rule_check_review()
else:
    page_results()
