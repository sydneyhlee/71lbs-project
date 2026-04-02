"""
Streamlit review UI for contract extractions.

Run with: streamlit run app/review/ui.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app.models.schema import ContractExtraction, ExtractionStatus, ExtractedValue
from app.pipeline.ingestion import ingest_pdf
from app.storage.store import (
    approve_extraction,
    delete_extraction,
    list_extractions,
    load_extraction,
    reject_extraction,
    update_extraction,
)
from app.pipeline.confidence import score_extraction


# ---------------------------------------------------------------------------
# Theme CSS
# ---------------------------------------------------------------------------

DARK_CSS = """
<style>
:root {
    --bg-primary: #0e1117;
    --bg-secondary: #1a1d23;
    --bg-card: #1e2128;
    --border: #2d3139;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #79b8ff;
    --success: #3fb950;
    --warning: #d29922;
    --danger: #f85149;
    --confidence-high: #3fb950;
    --confidence-mid: #d29922;
    --confidence-low: #f85149;
}

.main .block-container { max-width: 1200px; padding-top: 2rem; }

div[data-testid="stSidebar"] {
    background: var(--bg-secondary);
    border-right: 1px solid var(--border);
}

.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem;
    text-align: center;
    transition: border-color 0.2s;
}
.metric-card:hover { border-color: var(--accent); }
.metric-card .metric-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.2;
}
.metric-card .metric-label {
    font-size: 0.8rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.25rem;
}

.conf-bar-container {
    background: var(--border);
    border-radius: 6px;
    height: 8px;
    overflow: hidden;
    margin: 0.25rem 0;
}
.conf-bar-fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
}

.extraction-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.extraction-card:hover { border-color: var(--accent); }

.status-badge {
    display: inline-block;
    padding: 0.2rem 0.75rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.status-pending { background: rgba(210,153,34,0.15); color: var(--warning); }
.status-approved { background: rgba(63,185,80,0.15); color: var(--success); }
.status-rejected { background: rgba(248,81,73,0.15); color: var(--danger); }

.field-row {
    display: flex;
    align-items: center;
    padding: 0.6rem 0;
    border-bottom: 1px solid var(--border);
    gap: 1rem;
}
.field-label {
    flex: 0 0 180px;
    font-size: 0.85rem;
    color: var(--text-secondary);
    font-weight: 500;
}
.field-value {
    flex: 1;
    font-size: 0.95rem;
    color: var(--text-primary);
    font-weight: 400;
}
.field-conf {
    flex: 0 0 60px;
    text-align: right;
    font-size: 0.8rem;
    font-weight: 600;
}

.page-header {
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
}
.page-header h1 {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 700;
}
.page-header p {
    margin: 0.25rem 0 0 0;
    color: var(--text-secondary);
    font-size: 0.95rem;
}

.sidebar-brand {
    font-size: 1.4rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
}
.sidebar-subtitle {
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-bottom: 1.5rem;
}

.upload-zone {
    border: 2px dashed var(--border);
    border-radius: 16px;
    padding: 3rem 2rem;
    text-align: center;
    transition: border-color 0.2s;
}
.upload-zone:hover { border-color: var(--accent); }

.data-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.85rem;
}
.data-table th {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    padding: 0.6rem 0.75rem;
    text-align: left;
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
}
.data-table td {
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid var(--border);
    color: var(--text-primary);
}
.data-table tr:hover td { background: rgba(88,166,255,0.04); }
</style>
"""

LIGHT_CSS = """
<style>
:root {
    --bg-primary: #ffffff;
    --bg-secondary: #f6f8fa;
    --bg-card: #ffffff;
    --border: #d1d9e0;
    --text-primary: #1f2328;
    --text-secondary: #656d76;
    --accent: #0969da;
    --accent-hover: #0550ae;
    --success: #1a7f37;
    --warning: #9a6700;
    --danger: #d1242f;
    --confidence-high: #1a7f37;
    --confidence-mid: #9a6700;
    --confidence-low: #d1242f;
}

.main .block-container { max-width: 1200px; padding-top: 2rem; }

div[data-testid="stSidebar"] {
    background: var(--bg-secondary);
    border-right: 1px solid var(--border);
}

.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    transition: border-color 0.2s, box-shadow 0.2s;
}
.metric-card:hover { border-color: var(--accent); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.metric-card .metric-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.2;
}
.metric-card .metric-label {
    font-size: 0.8rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.25rem;
}

.conf-bar-container {
    background: #e1e4e8;
    border-radius: 6px;
    height: 8px;
    overflow: hidden;
    margin: 0.25rem 0;
}
.conf-bar-fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
}

.extraction-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    transition: border-color 0.2s, box-shadow 0.2s;
}
.extraction-card:hover { border-color: var(--accent); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

.status-badge {
    display: inline-block;
    padding: 0.2rem 0.75rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.status-pending { background: rgba(154,103,0,0.1); color: var(--warning); }
.status-approved { background: rgba(26,127,55,0.1); color: var(--success); }
.status-rejected { background: rgba(209,36,47,0.1); color: var(--danger); }

.field-row {
    display: flex;
    align-items: center;
    padding: 0.6rem 0;
    border-bottom: 1px solid #eaeef2;
    gap: 1rem;
}
.field-label {
    flex: 0 0 180px;
    font-size: 0.85rem;
    color: var(--text-secondary);
    font-weight: 500;
}
.field-value {
    flex: 1;
    font-size: 0.95rem;
    color: var(--text-primary);
    font-weight: 400;
}
.field-conf {
    flex: 0 0 60px;
    text-align: right;
    font-size: 0.8rem;
    font-weight: 600;
}

.page-header {
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
}
.page-header h1 {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text-primary);
}
.page-header p {
    margin: 0.25rem 0 0 0;
    color: var(--text-secondary);
    font-size: 0.95rem;
}

.sidebar-brand {
    font-size: 1.4rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
}
.sidebar-subtitle {
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-bottom: 1.5rem;
}

.data-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.85rem;
}
.data-table th {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    padding: 0.6rem 0.75rem;
    text-align: left;
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 2px solid var(--border);
}
.data-table td {
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid #eaeef2;
    color: var(--text-primary);
}
.data-table tr:hover td { background: rgba(9,105,218,0.03); }
</style>
"""


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="71lbs Contract Review",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Theme state
# ---------------------------------------------------------------------------

if "theme" not in st.session_state:
    st.session_state.theme = "dark"


def get_theme_css() -> str:
    return DARK_CSS if st.session_state.theme == "dark" else LIGHT_CSS


st.markdown(get_theme_css(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def conf_color(score: float) -> str:
    if score >= 0.85:
        return "var(--confidence-high)"
    if score >= 0.7:
        return "var(--confidence-mid)"
    return "var(--confidence-low)"


def conf_bar(score: float, width: str = "100%") -> str:
    pct = int(score * 100)
    color = conf_color(score)
    return (
        f'<div class="conf-bar-container" style="width:{width}">'
        f'<div class="conf-bar-fill" style="width:{pct}%;background:{color}"></div>'
        f'</div>'
    )


def status_badge(status: ExtractionStatus) -> str:
    label = status.value.replace("_", " ").title()
    cls = {
        ExtractionStatus.PENDING: "status-pending",
        ExtractionStatus.APPROVED: "status-approved",
        ExtractionStatus.REJECTED: "status-rejected",
    }.get(status, "status-pending")
    return f'<span class="status-badge {cls}">{label}</span>'


def metric_card(value: str, label: str) -> str:
    return (
        f'<div class="metric-card">'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-label">{label}</div>'
        f'</div>'
    )


def format_ev(ev: ExtractedValue) -> str:
    val = ev.effective()
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    if val is None:
        return "-"
    return str(val)


def field_row_html(label: str, ev: ExtractedValue) -> str:
    val = format_ev(ev)
    pct = int(ev.confidence * 100)
    color = conf_color(ev.confidence)
    review = ' <span style="color:var(--warning);font-size:0.75rem">REVIEW</span>' if ev.needs_review else ""
    return (
        f'<div class="field-row">'
        f'<div class="field-label">{label}</div>'
        f'<div class="field-value">{val}</div>'
        f'<div class="field-conf" style="color:{color}">{pct}%{review}</div>'
        f'</div>'
    )


def build_table_html(headers: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th>{h}</th>" for h in headers)
    trs = ""
    for row in rows:
        tds = "".join(f"<td>{c}</td>" for c in row)
        trs += f"<tr>{tds}</tr>"
    return f'<table class="data-table"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>'


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown('<div class="sidebar-brand">71lbs</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sidebar-subtitle">Contract Extraction Pipeline</div>',
        unsafe_allow_html=True,
    )

    theme_label = "Switch to Light Mode" if st.session_state.theme == "dark" else "Switch to Dark Mode"
    if st.button(theme_label, use_container_width=True, key="theme_toggle"):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()

    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["Upload", "Review Queue", "Approved"],
        index=0,
        label_visibility="collapsed",
    )

    st.markdown("---")

    all_ext = list_extractions()
    pending_count = sum(1 for e in all_ext if e.status == ExtractionStatus.PENDING)
    approved_count = sum(1 for e in all_ext if e.status == ExtractionStatus.APPROVED)
    rejected_count = sum(1 for e in all_ext if e.status == ExtractionStatus.REJECTED)

    st.caption("OVERVIEW")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pending", pending_count)
    c2.metric("Approved", approved_count)
    c3.metric("Rejected", rejected_count)


# ---------------------------------------------------------------------------
# Upload page
# ---------------------------------------------------------------------------

if page == "Upload":
    st.markdown(
        '<div class="page-header">'
        "<h1>Upload Contract PDF</h1>"
        "<p>Upload a FedEx or UPS shipping contract to extract structured pricing data.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    uploaded = st.file_uploader(
        "Choose a PDF file",
        type=["pdf"],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )

    if uploaded:
        st.markdown(f"**Selected:** {uploaded.name} ({uploaded.size / 1024:.0f} KB)")

        if st.button("Extract Contract Data", type="primary", use_container_width=True):
            with st.spinner("Processing PDF through extraction pipeline..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name

                try:
                    extraction = ingest_pdf(tmp_path)

                    st.success("Extraction complete!")

                    cols = st.columns(4)
                    cols[0].markdown(
                        metric_card(f"{extraction.overall_confidence:.0%}", "Confidence"),
                        unsafe_allow_html=True,
                    )
                    cols[1].markdown(
                        metric_card(str(len(extraction.service_terms)), "Service Terms"),
                        unsafe_allow_html=True,
                    )
                    cols[2].markdown(
                        metric_card(str(len(extraction.surcharges)), "Surcharges"),
                        unsafe_allow_html=True,
                    )
                    cols[3].markdown(
                        metric_card(str(extraction.fields_needing_review), "Needs Review"),
                        unsafe_allow_html=True,
                    )

                    st.markdown("#### Metadata")
                    meta = extraction.metadata
                    html = ""
                    for fname in meta.model_fields:
                        ev = getattr(meta, fname)
                        html += field_row_html(fname.replace("_", " ").title(), ev)
                    st.markdown(html, unsafe_allow_html=True)

                    st.markdown("")
                    st.info(
                        f"Extraction saved with ID `{extraction.id[:8]}...` "
                        "- head to **Review Queue** to review and approve."
                    )

                except Exception as exc:
                    st.error(f"Extraction failed: {exc}")
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
    else:
        st.markdown("")
        st.markdown(
            '<div style="text-align:center;padding:3rem 0;color:var(--text-secondary)">'
            '<div style="font-size:3rem;margin-bottom:0.5rem">PDF</div>'
            "<p>Drag and drop a contract PDF above to get started</p>"
            "</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

elif page == "Review Queue":
    st.markdown(
        '<div class="page-header">'
        "<h1>Review Queue</h1>"
        "<p>Review, edit, and approve or reject contract extractions.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    extractions = list_extractions(status_filter=ExtractionStatus.PENDING)

    if not extractions:
        st.info("No extractions pending review. Upload a contract PDF to get started.")
    else:
        for ext in extractions:
            col_main, col_action = st.columns([5, 1])
            with col_main:
                customer = ext.metadata.customer_name.effective() or "Unknown"
                account = ext.metadata.account_number.effective() or "-"
                carrier = ext.metadata.carrier.effective() or "-"
                st.markdown(
                    f'<div class="extraction-card">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center">'
                    f'<div><strong style="font-size:1.05rem">{ext.file_name}</strong></div>'
                    f'<div>{status_badge(ext.status)}</div>'
                    f'</div>'
                    f'<div style="margin-top:0.75rem;display:flex;gap:2rem;font-size:0.85rem;color:var(--text-secondary)">'
                    f'<span>Customer: <strong style="color:var(--text-primary)">{customer}</strong></span>'
                    f'<span>Account: <strong style="color:var(--text-primary)">{account}</strong></span>'
                    f'<span>Carrier: <strong style="color:var(--text-primary)">{carrier}</strong></span>'
                    f'</div>'
                    f'<div style="margin-top:0.5rem;display:flex;gap:2rem;font-size:0.85rem;color:var(--text-secondary)">'
                    f'<span>Confidence: <strong style="color:var(--text-primary)">{ext.overall_confidence:.0%}</strong></span>'
                    f'<span>Fields: <strong style="color:var(--text-primary)">{ext.total_fields_extracted}</strong></span>'
                    f'<span>Needs review: <strong style="color:var(--text-primary)">{ext.fields_needing_review}</strong></span>'
                    f'</div>'
                    f'<div style="margin-top:0.5rem">{conf_bar(ext.overall_confidence)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_action:
                st.markdown("")
                st.markdown("")
                if st.button("Review", key=f"review_{ext.id}", use_container_width=True, type="primary"):
                    st.session_state.reviewing = ext.id
                    st.rerun()

        st.markdown("---")

        # Detail view
        reviewing_id = st.session_state.get("reviewing")
        if reviewing_id:
            extraction = load_extraction(reviewing_id)
            if not extraction:
                st.error("Extraction not found.")
                st.session_state.pop("reviewing", None)
            else:
                st.markdown(f"### Reviewing: {extraction.file_name}")

                cols = st.columns(5)
                cols[0].markdown(
                    metric_card(f"{extraction.overall_confidence:.0%}", "Confidence"),
                    unsafe_allow_html=True,
                )
                cols[1].markdown(
                    metric_card(str(len(extraction.service_terms)), "Service Terms"),
                    unsafe_allow_html=True,
                )
                cols[2].markdown(
                    metric_card(str(len(extraction.surcharges)), "Surcharges"),
                    unsafe_allow_html=True,
                )
                cols[3].markdown(
                    metric_card(str(len(extraction.dim_rules)), "DIM Rules"),
                    unsafe_allow_html=True,
                )
                cols[4].markdown(
                    metric_card(str(len(extraction.special_terms)), "Special Terms"),
                    unsafe_allow_html=True,
                )

                tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                    "Metadata", "Service Terms", "Surcharges",
                    "DIM Rules", "Special Terms", "Amendments",
                ])

                with tab1:
                    st.markdown("#### Contract Metadata")
                    meta = extraction.metadata
                    html = ""
                    for fname in meta.model_fields:
                        ev = getattr(meta, fname)
                        html += field_row_html(fname.replace("_", " ").title(), ev)
                    st.markdown(html, unsafe_allow_html=True)

                with tab2:
                    st.markdown("#### Service Terms")
                    if not extraction.service_terms:
                        st.info("No service terms extracted.")
                    else:
                        headers = ["#", "Service Type", "Zones", "Discount %", "Conditions", "Conf"]
                        rows = []
                        for i, term in enumerate(extraction.service_terms):
                            conf_pct = int(term.service_type.confidence * 100)
                            color = conf_color(term.service_type.confidence)
                            rows.append([
                                str(i + 1),
                                format_ev(term.service_type),
                                format_ev(term.applicable_zones),
                                format_ev(term.discount_percentage),
                                format_ev(term.conditions),
                                f'<span style="color:{color};font-weight:600">{conf_pct}%</span>',
                            ])
                        st.markdown(build_table_html(headers, rows), unsafe_allow_html=True)

                with tab3:
                    st.markdown("#### Surcharges")
                    if not extraction.surcharges:
                        st.info("No surcharges extracted.")
                    else:
                        headers = ["#", "Surcharge", "Modification", "Discount %", "Conf"]
                        rows = []
                        for i, sc in enumerate(extraction.surcharges):
                            conf_pct = int(sc.surcharge_name.confidence * 100)
                            color = conf_color(sc.surcharge_name.confidence)
                            rows.append([
                                str(i + 1),
                                format_ev(sc.surcharge_name),
                                format_ev(sc.modification),
                                format_ev(sc.discount_percentage),
                                f'<span style="color:{color};font-weight:600">{conf_pct}%</span>',
                            ])
                        st.markdown(build_table_html(headers, rows), unsafe_allow_html=True)

                with tab4:
                    st.markdown("#### DIM Weight Rules")
                    if not extraction.dim_rules:
                        st.info("No DIM rules extracted.")
                    else:
                        for i, dim in enumerate(extraction.dim_rules):
                            with st.expander(f"DIM Rule #{i+1}  -  Divisor: {format_ev(dim.dim_divisor)}", expanded=(i == 0)):
                                html = ""
                                html += field_row_html("DIM Divisor", dim.dim_divisor)
                                html += field_row_html("Applicable Services", dim.applicable_services)
                                html += field_row_html("Conditions", dim.conditions)
                                st.markdown(html, unsafe_allow_html=True)

                with tab5:
                    st.markdown("#### Special Terms")
                    if not extraction.special_terms:
                        st.info("No special terms extracted.")
                    else:
                        for i, sp in enumerate(extraction.special_terms):
                            with st.expander(f"Term #{i+1}  -  {format_ev(sp.term_name)}", expanded=(i == 0)):
                                html = ""
                                html += field_row_html("Term Name", sp.term_name)
                                html += field_row_html("Term Value", sp.term_value)
                                html += field_row_html("Conditions", sp.conditions)
                                st.markdown(html, unsafe_allow_html=True)

                with tab6:
                    st.markdown("#### Amendments")
                    if not extraction.amendments:
                        st.info("No amendments detected.")
                    else:
                        for i, amd in enumerate(extraction.amendments):
                            with st.expander(
                                f"Amendment {amd.amendment_number.effective() or i+1}",
                                expanded=(i == 0),
                            ):
                                html = ""
                                html += field_row_html("Amendment Number", amd.amendment_number)
                                html += field_row_html("Effective Date", amd.effective_date)
                                html += field_row_html("Supersedes", amd.supersedes_version)
                                html += field_row_html("Description", amd.description)
                                st.markdown(html, unsafe_allow_html=True)

                st.markdown("---")

                notes = st.text_area(
                    "Review Notes",
                    value=extraction.review_notes or "",
                    key=f"notes_{reviewing_id}",
                    placeholder="Add any notes about this extraction...",
                )

                col_a, col_r, col_back = st.columns(3)
                with col_a:
                    if st.button("Approve", type="primary", key=f"approve_{reviewing_id}", use_container_width=True):
                        extraction.review_notes = notes
                        extraction = score_extraction(extraction)
                        approve_extraction(reviewing_id)
                        st.session_state.pop("reviewing", None)
                        st.success("Extraction approved!")
                        st.rerun()

                with col_r:
                    if st.button("Reject", key=f"reject_{reviewing_id}", use_container_width=True):
                        extraction.review_notes = notes
                        reject_extraction(reviewing_id)
                        st.session_state.pop("reviewing", None)
                        st.warning("Extraction rejected.")
                        st.rerun()

                with col_back:
                    if st.button("Back to Queue", key=f"back_{reviewing_id}", use_container_width=True):
                        st.session_state.pop("reviewing", None)
                        st.rerun()


# ---------------------------------------------------------------------------
# Approved
# ---------------------------------------------------------------------------

elif page == "Approved":
    st.markdown(
        '<div class="page-header">'
        "<h1>Approved Extractions</h1>"
        "<p>Download approved contract data as JSON for downstream systems.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    approved = list_extractions(status_filter=ExtractionStatus.APPROVED)

    if not approved:
        st.info("No approved extractions yet. Review and approve contracts from the Review Queue.")
    else:
        for ext in approved:
            customer = ext.metadata.customer_name.effective() or "Unknown"
            carrier = ext.metadata.carrier.effective() or "-"
            ts = ext.extraction_timestamp[:10] if ext.extraction_timestamp else "-"

            st.markdown(
                f'<div class="extraction-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<div><strong style="font-size:1.05rem">{ext.file_name}</strong></div>'
                f'<div>{status_badge(ext.status)}</div>'
                f'</div>'
                f'<div style="margin-top:0.5rem;display:flex;gap:2rem;font-size:0.85rem;color:var(--text-secondary)">'
                f'<span>Customer: <strong style="color:var(--text-primary)">{customer}</strong></span>'
                f'<span>Carrier: <strong style="color:var(--text-primary)">{carrier}</strong></span>'
                f'<span>Confidence: <strong style="color:var(--text-primary)">{ext.overall_confidence:.0%}</strong></span>'
                f'<span>Extracted: <strong style="color:var(--text-primary)">{ts}</strong></span>'
                f'</div>'
                f'<div style="margin-top:0.5rem">{conf_bar(ext.overall_confidence)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            col_dl, col_view, col_del = st.columns([2, 2, 1])
            with col_dl:
                st.download_button(
                    "Download JSON",
                    data=ext.model_dump_json(indent=2),
                    file_name=f"{ext.file_name.replace('.pdf', '')}_extraction.json",
                    mime="application/json",
                    key=f"dl_{ext.id}",
                    use_container_width=True,
                )
            with col_view:
                if st.button("View Details", key=f"view_{ext.id}", use_container_width=True):
                    with st.expander("Full Extraction JSON", expanded=True):
                        st.json(json.loads(ext.model_dump_json()), expanded=False)
            with col_del:
                if st.button("Delete", key=f"del_{ext.id}", use_container_width=True):
                    delete_extraction(ext.id)
                    st.rerun()
