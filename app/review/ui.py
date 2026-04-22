"""
Streamlit review UI for contract extractions.

Run with: python run_ui.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import io
import csv
import uuid
import subprocess
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app.models.schema import ContractExtraction, ExtractionStatus, ExtractedValue
from app.invoice.audit import (
    render_discrepancy_text_report,
    run_invoice_audit_from_files,
    save_audit_report,
)
from app.pipeline.ingestion import ingest_pdf
from app.pipeline.resolver import resolve_active_terms
from app.reference.health import summarize_health
from app.validation.parallel_study import (
    ParallelStudyRecord,
    compute_metrics,
)
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
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="71lbs Pricing Agreement Review",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme state (dark is default via .streamlit/config.toml)
# ---------------------------------------------------------------------------

if "theme" not in st.session_state:
    st.session_state.theme = "dark"

LIGHT_OVERRIDE = """
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background-color: #ffffff !important;
    color: #1f2328 !important;
}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {
    background-color: #f6f8fa !important;
    color: #1f2328 !important;
}
[data-testid="stHeader"] {
    background-color: #ffffff !important;
}
.stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown h1, .stMarkdown h2,
.stMarkdown h3, .stMarkdown h4, .stCaption, label, .stRadio label,
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
    color: #1f2328 !important;
}
.stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
    background-color: #f6f8fa !important;
    color: #1f2328 !important;
    border-color: #d1d9e0 !important;
}
[data-testid="stExpander"] {
    background-color: #f6f8fa !important;
    border-color: #d1d9e0 !important;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] p {
    color: #1f2328 !important;
}
hr { border-color: #d1d9e0 !important; }
.stTabs [data-baseweb="tab-list"] { border-color: #d1d9e0 !important; }
.stTabs [data-baseweb="tab"] { color: #656d76 !important; }
.stTabs [aria-selected="true"] { color: #1f2328 !important; }
.stAlert { color: #1f2328 !important; }
[data-testid="stFileUploader"] { border-color: #d1d9e0 !important; }
[data-testid="stFileUploader"] label { color: #1f2328 !important; }
</style>
"""


# ---------------------------------------------------------------------------
# Custom CSS (works on top of Streamlit's native theme)
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
<style>
.main .block-container { max-width: 1200px; padding-top: 1.5rem; }

.metric-card {
    border: 1px solid rgba(128,128,128,0.2);
    border-radius: 12px;
    padding: 1.2rem 1rem;
    text-align: center;
    margin-bottom: 0.5rem;
}
.metric-card .metric-value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
}
.metric-card .metric-label {
    font-size: 0.78rem;
    opacity: 0.6;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.25rem;
}

.conf-bar-bg {
    background: rgba(128,128,128,0.2);
    border-radius: 6px;
    height: 8px;
    overflow: hidden;
    margin: 0.3rem 0;
}
.conf-bar-fg {
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
}

.extraction-card {
    border: 1px solid rgba(128,128,128,0.2);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem;
}

.badge {
    display: inline-block;
    padding: 0.15rem 0.7rem;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.badge-pending  { background: rgba(210,153,34,0.15); color: #d29922; }
.badge-approved { background: rgba(63,185,80,0.15);  color: #3fb950; }
.badge-rejected { background: rgba(248,81,73,0.15);  color: #f85149; }

.field-row {
    display: flex;
    align-items: center;
    padding: 0.55rem 0;
    border-bottom: 1px solid rgba(128,128,128,0.15);
    gap: 0.75rem;
}
.field-label {
    flex: 0 0 180px;
    font-size: 0.82rem;
    opacity: 0.6;
    font-weight: 500;
}
.field-value {
    flex: 1;
    font-size: 0.92rem;
    font-weight: 400;
}
.field-conf {
    flex: 0 0 80px;
    text-align: right;
    font-size: 0.8rem;
    font-weight: 600;
}

.issue-flag {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    margin-left: 0.4rem;
    background: rgba(248,81,73,0.12);
    color: #f85149;
}

.data-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.84rem;
}
.data-table th {
    padding: 0.55rem 0.7rem;
    text-align: left;
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.6;
    border-bottom: 2px solid rgba(128,128,128,0.2);
}
.data-table td {
    padding: 0.55rem 0.7rem;
    border-bottom: 1px solid rgba(128,128,128,0.1);
}
.data-table tr:hover td { background: rgba(128,128,128,0.05); }

.conf-high { color: #3fb950; }
.conf-mid  { color: #d29922; }
.conf-low  { color: #f85149; }

/* Bigger sidebar radio buttons */
[data-testid="stSidebar"] .stRadio label {
    font-size: 1.1rem !important;
    padding: 0.6rem 0.3rem !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] {
    gap: 0.3rem !important;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if st.session_state.theme == "light":
    st.markdown(LIGHT_OVERRIDE, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def conf_cls(score: float) -> str:
    if score >= 0.85: return "conf-high"
    if score >= 0.7: return "conf-mid"
    return "conf-low"


def conf_hex(score: float) -> str:
    if score >= 0.85: return "#3fb950"
    if score >= 0.7: return "#d29922"
    return "#f85149"


def conf_bar_html(score: float) -> str:
    pct = max(int(score * 100), 2)
    return (
        f'<div class="conf-bar-bg">'
        f'<div class="conf-bar-fg" style="width:{pct}%;background:{conf_hex(score)}"></div>'
        f'</div>'
    )


def badge_html(status: ExtractionStatus) -> str:
    label = status.value.replace("_", " ").title()
    cls_map = {
        ExtractionStatus.PENDING: "badge-pending",
        ExtractionStatus.APPROVED: "badge-approved",
        ExtractionStatus.REJECTED: "badge-rejected",
    }
    return f'<span class="badge {cls_map.get(status, "badge-pending")}">{label}</span>'


def metric_html(value: str, label: str) -> str:
    return (
        f'<div class="metric-card">'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-label">{label}</div>'
        f'</div>'
    )


def fmt(ev: ExtractedValue) -> str:
    val = ev.effective()
    if isinstance(val, list):
        if not val:
            return "Item not found"
        return ", ".join(str(v) for v in val)
    if val is None:
        return "Item not found"
    if isinstance(val, str) and not val.strip():
        return "Item not found"
    return str(val)


def _fmt_parser_value(ev: ExtractedValue) -> str:
    v = ev.original_parser_value
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "Item not found"
    if v is None:
        return "Item not found"
    if isinstance(v, str) and not v.strip():
        return "Item not found"
    return str(v)


def _fmt_with_correction(ev: ExtractedValue) -> str:
    if ev.was_llm_corrected:
        return f"{_fmt_parser_value(ev)} -> {fmt(ev)}"
    return fmt(ev)


def _first_correction_reason(evs: list[ExtractedValue]) -> str:
    for ev in evs:
        if ev.was_llm_corrected and ev.correction_reason:
            return ev.correction_reason
    return "-"


def _is_empty_effective_value(ev: ExtractedValue) -> bool:
    val = ev.effective()
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    if isinstance(val, list) and not val:
        return True
    return False


def field_html(label: str, ev: ExtractedValue) -> str:
    val = fmt(ev)
    is_empty = _is_empty_effective_value(ev)
    pct_text = "Item not found" if is_empty else f"{int(ev.confidence * 100)}%"
    cls = "conf-mid" if is_empty else conf_cls(ev.confidence)
    flag = ""
    if is_empty:
        flag = ""
    elif ev.needs_review:
        flag = '<span class="issue-flag">REVIEW</span>'
    elif ev.confidence < 0.7:
        flag = '<span class="issue-flag">LOW</span>'
    if ev.was_llm_corrected:
        reason = ev.correction_reason or "LLM verification update"
        conf_note = ev.confidence_rationale or ""
        value_html = (
            f'<div><strong>Parser:</strong> {_fmt_parser_value(ev)}</div>'
            f'<div><strong>LLM:</strong> {val}</div>'
            f'<div style="opacity:0.75;font-size:0.78rem;"><strong>Reason:</strong> {reason}</div>'
            f'<div style="opacity:0.75;font-size:0.78rem;">{conf_note}</div>'
        )
    else:
        value_html = val

    return (
        f'<div class="field-row">'
        f'<div class="field-label">{label}</div>'
        f'<div class="field-value">{value_html}</div>'
        f'<div class="field-conf"><span class="{cls}">{pct_text}</span>{flag}</div>'
        f'</div>'
    )


def table_html(headers: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th>{h}</th>" for h in headers)
    trs = ""
    for row in rows:
        tds = "".join(f"<td>{c}</td>" for c in row)
        trs += f"<tr>{tds}</tr>"
    return f'<table class="data-table"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>'


def _normalized_company_key(name: str) -> str:
    parts = "".join(ch.lower() if ch.isalnum() else " " for ch in name).split()
    return " ".join(parts)


def _display_company_name(extraction: ContractExtraction) -> str:
    raw = extraction.metadata.customer_name.effective()
    text = str(raw).strip() if raw is not None else ""
    return text or "Unknown Company"


def _is_non_empty_ev(ev: ExtractedValue) -> bool:
    value = ev.effective()
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, list) and not value:
        return False
    return True


def _pick_best_extracted_value(values: list[ExtractedValue]) -> ExtractedValue:
    non_empty = [v for v in values if _is_non_empty_ev(v)]
    pool = non_empty if non_empty else values
    best = max(pool, key=lambda v: v.confidence, default=ExtractedValue())
    return best.model_copy(deep=True)


def _dedupe_model_list(items: list) -> list:
    seen = set()
    unique = []
    for item in items:
        key = item.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _merge_company_group(extractions: list[ContractExtraction], company_name: str) -> ContractExtraction:
    # Resolve package supersession across documents first (base/addendum/amendment).
    resolved = resolve_active_terms(extractions)
    merged = resolved.model_copy(deep=True)
    merged.id = str(uuid.uuid4())
    merged.file_name = f"{company_name} ({len(extractions)} files).pdf"
    merged.file_path = " | ".join(
        sorted({e.file_path for e in extractions if e.file_path})
    )
    merged.status = ExtractionStatus.PENDING

    merged = score_extraction(merged)
    merged = resolve_active_terms(merged)
    return merged


def _collapse_uploads_by_company(
    extractions: list[ContractExtraction],
) -> tuple[list[ContractExtraction], list[dict]]:
    grouped: dict[str, list[ContractExtraction]] = defaultdict(list)
    names_by_key: dict[str, str] = {}
    for ext in extractions:
        company = _display_company_name(ext)
        key = _normalized_company_key(company)
        grouped[key].append(ext)
        names_by_key.setdefault(key, company)

    collapsed: list[ContractExtraction] = []
    merged_info: list[dict] = []
    for key, group in grouped.items():
        if len(group) == 1:
            collapsed.append(group[0])
            continue
        merged = _merge_company_group(group, names_by_key[key])
        update_extraction(merged)
        for ext in group:
            delete_extraction(ext.id)
        collapsed.append(merged)
        merged_info.append(
            {"company": names_by_key[key], "files_merged": len(group), "result_id": merged.id}
        )
    return collapsed, merged_info


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 71lbs")
    st.caption("Pricing Agreement Extraction")

    is_dark = st.session_state.theme == "dark"
    toggle_label = "Switch to Light Mode" if is_dark else "Switch to Dark Mode"
    if st.button(toggle_label, use_container_width=True):
        st.session_state.theme = "light" if is_dark else "dark"
        st.rerun()

    st.divider()

    page = st.radio(
        "Navigation",
        ["Upload Pricing Agreement", "Review Queue", "Approved", "Invoice Audit", "Parallel Study"],
        label_visibility="collapsed",
    )

    st.divider()

    all_ext = list_extractions()
    n_pending = sum(1 for e in all_ext if e.status == ExtractionStatus.PENDING)
    n_approved = sum(1 for e in all_ext if e.status == ExtractionStatus.APPROVED)
    n_rejected = sum(1 for e in all_ext if e.status == ExtractionStatus.REJECTED)

    st.caption("DASHBOARD")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pending", n_pending)
    c2.metric("Approved", n_approved)
    c3.metric("Rejected", n_rejected)

    st.divider()
    with st.expander("Developer Tools", expanded=False):
        if st.button("Run E2E Test", use_container_width=True):
            root = Path(__file__).resolve().parent.parent.parent
            cmd = [sys.executable, "-m", "scripts.run_sample_e2e"]
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            st.session_state["e2e_output"] = output.strip()
            for key in ("e2e_txt_path", "e2e_json_path"):
                st.session_state.pop(key, None)
            for line in (proc.stdout or "").splitlines():
                if line.startswith("audit_txt="):
                    st.session_state["e2e_txt_path"] = line.split("=", 1)[1].strip()
                if line.startswith("audit_json="):
                    st.session_state["e2e_json_path"] = line.split("=", 1)[1].strip()

        if st.session_state.get("e2e_output"):
            st.code(st.session_state["e2e_output"], language="text")
            txt_path = st.session_state.get("e2e_txt_path")
            json_path = st.session_state.get("e2e_json_path")
            if txt_path and Path(txt_path).exists():
                st.download_button(
                    "Download E2E TXT",
                    data=Path(txt_path).read_text(encoding="utf-8"),
                    file_name=Path(txt_path).name,
                    mime="text/plain",
                    use_container_width=True,
                )
            if json_path and Path(json_path).exists():
                st.download_button(
                    "Download E2E JSON",
                    data=Path(json_path).read_text(encoding="utf-8"),
                    file_name=Path(json_path).name,
                    mime="application/json",
                    use_container_width=True,
                )


# ===================================================================
# UPLOAD PAGE
# ===================================================================

if page == "Upload Pricing Agreement":
    st.title("Upload Pricing Agreement")
    st.markdown(
        "Upload one or more **FedEx or UPS pricing agreement** PDFs to extract structured "
        "pricing data (discounts, surcharges, DIM rules, service terms). "
        "Multiple files can be downloaded as **one combined JSON**."
    )

    st.info(
        "**Only upload pricing agreements** -- the PDFs that define your negotiated "
        "shipping rates with FedEx or UPS. Amendments and addendums are also accepted.\n\n"
        "**Do NOT upload** invoices, shipment receipts, tracking documents, or "
        "shipping labels. Those are not pricing agreements and will not parse correctly.",
        icon="📋",
    )

    uploaded_files = st.file_uploader(
        "Drag and drop pricing agreement PDF(s) here",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        total_kb = sum(f.size for f in uploaded_files) / 1024
        names_line = ", ".join(f"`{f.name}`" for f in uploaded_files)
        st.markdown(
            f"**{len(uploaded_files)} file(s):** {names_line} &nbsp; (~{total_kb:.0f} KB total)"
        )

        if st.button("Extract Pricing Data", type="primary", use_container_width=True):
            progress = st.progress(0, text="Starting extraction pipeline...")
            extractions: list[ContractExtraction] = []
            failures: list[dict] = []
            n = len(uploaded_files)

            try:
                for i, up_file in enumerate(uploaded_files):
                    pct = int(20 + 75 * (i / max(n, 1)))
                    progress.progress(pct, text=f"Processing {i + 1}/{n}: {up_file.name}...")
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(up_file.getvalue())
                        tmp_path = tmp.name
                    try:
                        extractions.append(ingest_pdf(tmp_path))
                    except Exception as exc:
                        failures.append({"name": up_file.name, "error": str(exc)})
                    finally:
                        Path(tmp_path).unlink(missing_ok=True)

                progress.progress(100, text="Complete!")

                if extractions:
                    st.success(
                        f"Finished **{len(extractions)}** extraction(s)."
                        + (f" **{len(failures)}** failed." if failures else "")
                    )
                for fail in failures:
                    st.error(f"**{fail['name']}:** {fail['error']}")

                if not extractions:
                    progress.empty()
                else:
                    grouped_extractions, merged_info = _collapse_uploads_by_company(extractions)
                    if merged_info:
                        merged_names = ", ".join(
                            f"{x['company']} ({x['files_merged']} files)"
                            for x in merged_info
                        )
                        st.info(
                            "Grouped uploads into one agreement per company: "
                            f"{merged_names}"
                        )
                    extractions = grouped_extractions

                    if len(extractions) == 1:
                        extraction = extractions[0]
                        st.markdown("#### Summary")
                        cols = st.columns(4)
                        cols[0].markdown(
                            metric_html(f"{extraction.overall_confidence:.0%}", "Confidence"),
                            unsafe_allow_html=True,
                        )
                        cols[1].markdown(
                            metric_html(str(len(extraction.service_terms)), "Service Terms"),
                            unsafe_allow_html=True,
                        )
                        cols[2].markdown(
                            metric_html(str(len(extraction.surcharges)), "Surcharges"),
                            unsafe_allow_html=True,
                        )
                        cols[3].markdown(
                            metric_html(str(extraction.fields_needing_review), "Needs Review"),
                            unsafe_allow_html=True,
                        )

                        if extraction.fields_needing_review > 0:
                            st.warning(
                                f"**{extraction.fields_needing_review}** field(s) have low confidence "
                                f"and may need manual review. Go to **Review Queue** to inspect.",
                                icon="⚠️",
                            )

                        st.markdown("#### Extracted Metadata")
                        meta = extraction.metadata
                        html = ""
                        for fname in meta.model_fields:
                            ev = getattr(meta, fname)
                            html += field_html(fname.replace("_", " ").title(), ev)
                        st.markdown(html, unsafe_allow_html=True)

                        st.download_button(
                            "Download JSON",
                            data=extraction.model_dump_json(indent=2),
                            file_name=f"{extraction.file_name.replace('.pdf', '')}_extraction.json",
                            mime="application/json",
                            use_container_width=True,
                            key="dl_single_upload",
                        )
                    else:
                        st.markdown("#### Per-file summary")
                        for ext in extractions:
                            with st.expander(
                                f"{ext.file_name} - {ext.overall_confidence:.0%} confidence",
                                expanded=False,
                            ):
                                c1, c2, c3, c4 = st.columns(4)
                                c1.caption("Confidence")
                                c1.write(f"{ext.overall_confidence:.0%}")
                                c2.caption("Service terms")
                                c2.write(len(ext.service_terms))
                                c3.caption("Surcharges")
                                c3.write(len(ext.surcharges))
                                c4.caption("Needs review")
                                c4.write(ext.fields_needing_review)

                        batch_payload = {
                            "batch_version": 1,
                            "document_count": len(extractions),
                            "documents": [
                                json.loads(e.model_dump_json()) for e in extractions
                            ],
                            "failed": failures,
                        }
                        st.download_button(
                            "Download combined JSON",
                            data=json.dumps(batch_payload, indent=2, default=str),
                            file_name="batch_extraction.json",
                            mime="application/json",
                            use_container_width=True,
                            key="dl_batch_upload",
                        )

                    st.divider()
                    if len(extractions) == 1:
                        ext_note = f"`{extractions[0].id[:8]}...`"
                    else:
                        ext_note = f"{len(extractions)} items"
                    st.info(
                        f"Saved {ext_note} - go to **Review Queue** to review, approve, or reject.",
                        icon="💾",
                    )

            except Exception as exc:
                progress.empty()
                st.error(f"Extraction failed: {exc}")

    else:
        st.markdown("")
        st.markdown(
            "<div style='text-align:center;padding:2.5rem 0;opacity:0.4'>"
            "<div style='font-size:3rem;margin-bottom:0.5rem'>📄</div>"
            "<p>Drag and drop one or more pricing agreement PDFs above, or click Browse files</p>"
            "</div>",
            unsafe_allow_html=True,
        )


# ===================================================================
# REVIEW QUEUE
# ===================================================================

elif page == "Review Queue":
    st.title("Review Queue")
    st.markdown("Review extracted data, check confidence scores, and approve or reject.")

    extractions = list_extractions(status_filter=ExtractionStatus.PENDING)

    if not extractions:
        st.info("No pricing agreements pending review. Upload one from the **Upload Pricing Agreement** page.")
    else:
        st.markdown(f"**{len(extractions)}** pricing agreement(s) pending review")

        selected_id = st.selectbox(
            "Select a pricing agreement to review",
            options=[e.id for e in extractions],
            format_func=lambda eid: next(
                (
                    f"{e.file_name}  --  "
                    f"Confidence: {e.overall_confidence:.0%}  |  "
                    f"Fields: {e.total_fields_extracted}  |  "
                    f"Needs review: {e.fields_needing_review}"
                    for e in extractions if e.id == eid
                ),
                eid,
            ),
        )

        if selected_id:
            extraction = load_extraction(selected_id)
            if not extraction:
                st.error("Extraction not found.")
            else:
                st.divider()

                # Summary metrics
                cols = st.columns(5)
                cols[0].markdown(metric_html(f"{extraction.overall_confidence:.0%}", "Confidence"), unsafe_allow_html=True)
                cols[1].markdown(metric_html(str(len(extraction.service_terms)), "Service Terms"), unsafe_allow_html=True)
                cols[2].markdown(metric_html(str(len(extraction.surcharges)), "Surcharges"), unsafe_allow_html=True)
                cols[3].markdown(metric_html(str(len(extraction.dim_rules)), "DIM Rules"), unsafe_allow_html=True)
                cols[4].markdown(metric_html(str(len(extraction.special_terms)), "Special Terms"), unsafe_allow_html=True)

                # Confidence bar
                st.markdown(conf_bar_html(extraction.overall_confidence), unsafe_allow_html=True)

                if extraction.fields_needing_review > 0:
                    st.warning(
                        f"**{extraction.fields_needing_review}** of "
                        f"**{extraction.total_fields_extracted}** fields "
                        f"flagged for review (below 70% confidence). "
                        f"Look for fields marked **LOW** or **REVIEW** below.",
                        icon="⚠️",
                    )

                # Tabs
                tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                    "Metadata", "Service Terms", "Surcharges",
                    "DIM Rules", "Special Terms", "Amendments",
                ])

                with tab1:
                    st.markdown("#### Agreement Metadata")
                    meta = extraction.metadata
                    html = ""
                    for fname in meta.model_fields:
                        ev = getattr(meta, fname)
                        html += field_html(fname.replace("_", " ").title(), ev)
                    st.markdown(html, unsafe_allow_html=True)

                with tab2:
                    st.markdown("#### Service Terms")
                    if not extraction.service_terms:
                        st.info("No service terms extracted.")
                    else:
                        st.caption(
                            "Each row is a unique combination of service type, weight range, "
                            "and zone. The same service name appears multiple times because "
                            "it has different discount rates for different weight tiers or "
                            "packaging types (see the Conditions column)."
                        )
                        headers = ["#", "Service Type", "Zones", "Discount %", "Conditions", "LLM Reason", "Confidence"]
                        rows = []
                        for i, t in enumerate(extraction.service_terms):
                            pct = int(t.service_type.confidence * 100)
                            cls = conf_cls(t.service_type.confidence)
                            flag = ""
                            if t.service_type.needs_review or t.service_type.confidence < 0.7:
                                flag = ' <span class="issue-flag">LOW</span>'
                            rows.append([
                                str(i + 1),
                                _fmt_with_correction(t.service_type),
                                _fmt_with_correction(t.applicable_zones),
                                _fmt_with_correction(t.discount_percentage),
                                _fmt_with_correction(t.conditions),
                                _first_correction_reason(
                                    [t.service_type, t.applicable_zones, t.discount_percentage, t.conditions]
                                ),
                                f'<span class="{cls}">{pct}%</span>{flag}',
                            ])
                        st.markdown(table_html(headers, rows), unsafe_allow_html=True)

                with tab3:
                    st.markdown("#### Surcharges")
                    if not extraction.surcharges:
                        st.info("No surcharges extracted.")
                    else:
                        headers = ["#", "Surcharge", "Modification", "Discount %", "LLM Reason", "Confidence"]
                        rows = []
                        for i, sc in enumerate(extraction.surcharges):
                            pct = int(sc.surcharge_name.confidence * 100)
                            cls = conf_cls(sc.surcharge_name.confidence)
                            flag = ""
                            if sc.surcharge_name.needs_review or sc.surcharge_name.confidence < 0.7:
                                flag = ' <span class="issue-flag">LOW</span>'
                            rows.append([
                                str(i + 1),
                                _fmt_with_correction(sc.surcharge_name),
                                _fmt_with_correction(sc.modification),
                                _fmt_with_correction(sc.discount_percentage),
                                _first_correction_reason(
                                    [sc.surcharge_name, sc.modification, sc.discount_percentage]
                                ),
                                f'<span class="{cls}">{pct}%</span>{flag}',
                            ])
                        st.markdown(table_html(headers, rows), unsafe_allow_html=True)

                with tab4:
                    st.markdown("#### DIM Weight Rules")
                    if not extraction.dim_rules:
                        st.info("No DIM rules extracted.")
                    else:
                        for i, dim in enumerate(extraction.dim_rules):
                            with st.expander(f"DIM Rule #{i+1} -- Divisor: {fmt(dim.dim_divisor)}", expanded=(i == 0)):
                                html = ""
                                html += field_html("DIM Divisor", dim.dim_divisor)
                                html += field_html("Applicable Services", dim.applicable_services)
                                html += field_html("Conditions", dim.conditions)
                                st.markdown(html, unsafe_allow_html=True)

                with tab5:
                    st.markdown("#### Special Terms")
                    if not extraction.special_terms:
                        st.info("No special terms extracted.")
                    else:
                        for i, sp in enumerate(extraction.special_terms):
                            with st.expander(f"Term #{i+1} -- {fmt(sp.term_name)}", expanded=(i == 0)):
                                html = ""
                                html += field_html("Term Name", sp.term_name)
                                html += field_html("Term Value", sp.term_value)
                                html += field_html("Conditions", sp.conditions)
                                st.markdown(html, unsafe_allow_html=True)

                with tab6:
                    st.markdown("#### Amendments")
                    if not extraction.amendments:
                        st.info("No amendments detected in this document.")
                    else:
                        for i, amd in enumerate(extraction.amendments):
                            with st.expander(f"Amendment {amd.amendment_number.effective() or i+1}", expanded=(i == 0)):
                                html = ""
                                html += field_html("Amendment Number", amd.amendment_number)
                                html += field_html("Effective Date", amd.effective_date)
                                html += field_html("Supersedes", amd.supersedes_version)
                                html += field_html("Description", amd.description)
                                st.markdown(html, unsafe_allow_html=True)

                # Actions
                st.divider()

                notes = st.text_area(
                    "Review Notes",
                    value=extraction.review_notes or "",
                    key=f"notes_{selected_id}",
                    placeholder="Add any notes about this extraction...",
                )

                col_a, col_r = st.columns(2)
                with col_a:
                    if st.button("Approve", type="primary", key=f"approve_{selected_id}", use_container_width=True):
                        extraction.review_notes = notes
                        extraction = score_extraction(extraction)
                        approve_extraction(selected_id)
                        st.success("Approved!")
                        st.rerun()

                with col_r:
                    if st.button("Reject", key=f"reject_{selected_id}", use_container_width=True):
                        extraction.review_notes = notes
                        reject_extraction(selected_id)
                        st.warning("Rejected.")
                        st.rerun()


# ===================================================================
# APPROVED
# ===================================================================

elif page == "Approved":
    st.title("Approved Extractions")
    st.markdown("Download approved pricing agreement data as JSON.")

    approved = list_extractions(status_filter=ExtractionStatus.APPROVED)

    if not approved:
        st.info("No approved extractions yet. Review and approve pricing agreements from the **Review Queue**.")
    else:
        for ext in approved:
            customer = ext.metadata.customer_name.effective() or "Unknown"
            carrier = ext.metadata.carrier.effective() or "-"
            ts = ext.extraction_timestamp[:10] if ext.extraction_timestamp else "-"

            st.markdown(
                f'<div class="extraction-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<div><strong>{ext.file_name}</strong></div>'
                f'<div>{badge_html(ext.status)}</div>'
                f'</div>'
                f'<div style="margin-top:0.5rem;opacity:0.7;font-size:0.85rem">'
                f'Customer: <strong>{customer}</strong> &nbsp; '
                f'Carrier: <strong>{carrier}</strong> &nbsp; '
                f'Confidence: <strong>{ext.overall_confidence:.0%}</strong> &nbsp; '
                f'Date: <strong>{ts}</strong>'
                f'</div>'
                f'{conf_bar_html(ext.overall_confidence)}'
                f'</div>',
                unsafe_allow_html=True,
            )

            col_dl, col_json, col_del = st.columns([2, 2, 1])
            with col_dl:
                st.download_button(
                    "Download JSON",
                    data=ext.model_dump_json(indent=2),
                    file_name=f"{ext.file_name.replace('.pdf', '')}_extraction.json",
                    mime="application/json",
                    key=f"dl_{ext.id}",
                    use_container_width=True,
                )
            with col_json:
                with st.expander("View JSON"):
                    st.json(json.loads(ext.model_dump_json()), expanded=False)
            with col_del:
                if st.button("Delete", key=f"del_{ext.id}", use_container_width=True):
                    delete_extraction(ext.id)
                    st.rerun()


# ===================================================================
# INVOICE AUDIT
# ===================================================================

elif page == "Invoice Audit":
    st.title("Invoice Audit")
    st.markdown(
        "Compare invoice charges against a **human-approved** agreement snapshot. "
        "Discrepancies are classified and exported as TXT + JSON."
    )
    st.info(
        "This audit only runs against agreements in **Approved** status to preserve "
        "the human validation gate before invoice comparison.",
        icon="✅",
    )

    approved = list_extractions(status_filter=ExtractionStatus.APPROVED)
    health = summarize_health()
    if health["stale_or_missing"] > 0:
        st.warning(
            "Reference data is stale/missing for one or more feeds. "
            "Audit outcomes may include ambiguous checks until refreshed."
        )
        with st.expander("Reference data health details"):
            st.json(health)

    if not approved:
        st.warning("No approved agreements found. Approve at least one agreement first.")
    else:
        selected_id = st.selectbox(
            "Select approved company agreement",
            options=[e.id for e in approved],
            format_func=lambda eid: next(
                (
                    f"{(e.metadata.customer_name.effective() or 'Unknown Company')} "
                    f"-- {e.file_name}"
                    for e in approved
                    if e.id == eid
                ),
                eid,
            ),
        )
        agreement = load_extraction(selected_id) if selected_id else None
        if not agreement:
            st.error("Selected agreement could not be loaded.")
        else:
            uploaded_invoices = st.file_uploader(
                "Upload invoice file(s) for this company (PDF or CSV)",
                type=["pdf", "csv"],
                accept_multiple_files=True,
                key="invoice_uploader",
            )
            api_invoice_ids_raw = st.text_input(
                "Optional carrier API invoice ID(s) (comma-separated, API-first path)",
                value="",
                help="When configured, the system attempts carrier API ingestion first, then falls back to files.",
            )
            api_invoice_ids = [
                x.strip() for x in api_invoice_ids_raw.split(",") if x.strip()
            ]

            if uploaded_invoices or api_invoice_ids:
                st.caption(
                    f"{len(uploaded_invoices or [])} file invoice(s), "
                    f"{len(api_invoice_ids)} API invoice ID(s) selected"
                )
                if st.button("Run Invoice Audit", type="primary", use_container_width=True):
                    temp_paths: list[Path] = []
                    try:
                        for inv in uploaded_invoices or []:
                            suffix = Path(inv.name).suffix or ".pdf"
                            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                                tmp.write(inv.getvalue())
                                temp_paths.append(Path(tmp.name))

                        report = run_invoice_audit_from_files(
                            agreement,
                            temp_paths,
                            carrier_invoice_ids=api_invoice_ids,
                        )
                        json_path, txt_path = save_audit_report(report)
                        txt_payload = render_discrepancy_text_report(report)

                        st.success(
                            f"Audit complete: {len(report.discrepancies)} discrepancy record(s)."
                        )
                        st.caption(f"Saved report files: `{json_path.name}`, `{txt_path.name}`")

                        if report.discrepancies:
                            def _action_for_ui(d):
                                field = (d.field or "").lower()
                                kind = d.discrepancy_type.value
                                if field == "service_refund":
                                    return "File GSR claim"
                                if field == "fuel_surcharge":
                                    return "Request fuel adjustment"
                                if field == "rated_weight_lbs":
                                    return "Dispute DIM/rated weight"
                                if kind == "missing_discount":
                                    return "Request discount rebill"
                                if kind == "unsupported_fee":
                                    return "Dispute unsupported fee"
                                return "Review and submit claim"

                            rows = [
                                {
                                    "Type": d.discrepancy_type.value,
                                    "Tracking Number": d.tracking_number or d.transaction_id or "-",
                                    "Ship Date": d.ship_date or "-",
                                    "Billed": d.billed_value if d.billed_value is not None else d.billed_amount,
                                    "Expected": d.expected_value if d.expected_value is not None else d.expected_amount,
                                    "Discrepancy $": d.dollar_impact,
                                    "Action": _action_for_ui(d),
                                }
                                for d in report.discrepancies
                            ]
                            st.dataframe(rows, use_container_width=True, hide_index=True)
                        else:
                            st.info("No discrepancies detected for uploaded invoices.")

                        col_txt, col_json = st.columns(2)
                        with col_txt:
                            st.download_button(
                                "Download TXT",
                                data=txt_payload,
                                file_name=f"{report.company_name}_invoice_audit.txt".replace(" ", "_"),
                                mime="text/plain",
                                use_container_width=True,
                            )
                        with col_json:
                            st.download_button(
                                "Download JSON",
                                data=report.model_dump_json(indent=2),
                                file_name=f"{report.company_name}_invoice_audit.json".replace(" ", "_"),
                                mime="application/json",
                                use_container_width=True,
                            )
                    except Exception as exc:
                        st.error(f"Invoice audit failed: {exc}")
                    finally:
                        for p in temp_paths:
                            p.unlink(missing_ok=True)


# ===================================================================
# PARALLEL STUDY
# ===================================================================

elif page == "Parallel Study":
    st.title("Parallel Study")
    st.markdown(
        "Compare AI findings with human auditor findings and compute precision/recall/F1."
    )
    template_csv = "tracking_number,discrepancy_found,discrepancy_type,dollar_amount\n"
    st.download_button(
        "Download human CSV template",
        data=template_csv,
        file_name="parallel_study_template.csv",
        mime="text/csv",
    )

    ai_json = st.file_uploader(
        "Upload AI audit report JSON",
        type=["json"],
        key="parallel_ai_json",
    )
    human_csv = st.file_uploader(
        "Upload human findings CSV",
        type=["csv"],
        key="parallel_human_csv",
    )

    if ai_json and human_csv:
        try:
            ai_data = json.loads(ai_json.getvalue().decode("utf-8"))
            ai_discrepancies = ai_data.get("discrepancies", [])
            ai_by_tracking: dict[str, list[dict]] = {}
            for d in ai_discrepancies:
                tracking = str(d.get("tracking_number") or d.get("transaction_id") or "").strip()
                if tracking:
                    ai_by_tracking.setdefault(tracking, []).append(d)

            human_rows = list(csv.DictReader(io.StringIO(human_csv.getvalue().decode("utf-8"))))
            records: list[ParallelStudyRecord] = []
            for row in human_rows:
                tracking = str(row.get("tracking_number") or "").strip()
                ai_rows = ai_by_tracking.get(tracking, [])
                ai = ai_rows[0] if ai_rows else {}
                human_found = str(row.get("discrepancy_found", "")).strip().lower() in {"1", "true", "yes", "y"}
                records.append(
                    ParallelStudyRecord(
                        shipment_id=str(row.get("shipment_id") or tracking),
                        tracking_number=tracking,
                        ai_found_discrepancy=bool(ai_rows),
                        ai_discrepancy_type=ai.get("discrepancy_type"),
                        ai_dollar_impact=float(ai.get("dollar_impact") or 0) if ai else None,
                        human_found_discrepancy=human_found,
                        human_discrepancy_type=row.get("discrepancy_type") or None,
                        human_dollar_impact=float(row.get("dollar_amount") or 0) if row.get("dollar_amount") else None,
                    )
                )

            metrics = compute_metrics(records)
            recall_color = "green" if metrics["recall"] >= 0.90 else "red"
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"### Precision\n<span style='color:#4fc3f7;font-size:2rem'>{metrics['precision']:.2%}</span>", unsafe_allow_html=True)
            c2.markdown(f"### Recall\n<span style='color:{recall_color};font-size:2rem'>{metrics['recall']:.2%}</span>", unsafe_allow_html=True)
            c3.markdown(f"### F1\n<span style='color:#ffd54f;font-size:2rem'>{metrics['f1']:.2%}</span>", unsafe_allow_html=True)

            tp = metrics["true_positives"]
            fp = metrics["false_positives"]
            fn = metrics["false_negatives"]
            tn = metrics["true_negatives"]
            st.table([{"TP": tp, "FP": fp, "FN": fn, "TN": tn}])

            total_ai_recovery = sum(float(d.get("dollar_impact") or 0.0) for d in ai_discrepancies)
            total_human_recovery = sum(float((r.human_dollar_impact or 0.0)) for r in records if r.human_found_discrepancy)
            fp_rows = [r.model_dump() for r in records if r.outcome == "FP"]
            fn_rows = [r.model_dump() for r in records if r.outcome == "FN"]
            additional_ai_only = sum(float((r.ai_dollar_impact or 0.0)) for r in records if r.outcome == "FP")
            st.markdown(
                f"**Total AI recovery:** ${total_ai_recovery:.2f}  \n"
                f"**Total human recovery:** ${total_human_recovery:.2f}  \n"
                f"**AI-only additional recovery (FP to verify):** ${additional_ai_only:.2f}"
            )

            with st.expander("Discrepancies AI found that humans missed (FP — verify these)", expanded=False):
                st.dataframe(fp_rows, use_container_width=True, hide_index=True)
            with st.expander("Discrepancies humans found that AI missed (FN — system gaps)", expanded=True):
                st.dataframe(fn_rows, use_container_width=True, hide_index=True)

            out = io.StringIO()
            fieldnames = list(fn_rows[0].keys()) if fn_rows else ["tracking_number", "outcome"]
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            for row in fn_rows:
                writer.writerow(row)
            st.download_button(
                "Download FN CSV",
                data=out.getvalue(),
                file_name="parallel_study_fn_gaps.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Parallel study processing failed: {exc}")
