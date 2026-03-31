"""
Streamlit review UI for contract extractions.

Provides a minimal interface to:
- Upload contract PDFs
- View extraction results with confidence indicators
- Edit low-confidence fields
- Approve or reject extractions
- Export approved JSON

Run with: streamlit run app/review/ui.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from app.models.schema import ContractExtraction, ExtractionStatus, ExtractedValue
from app.pipeline.ingestion import ingest_pdf
from app.storage.store import (
    approve_extraction,
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
    page_title="71lbs Contract Review",
    page_icon="📦",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def confidence_color(score: float) -> str:
    if score >= 0.85:
        return "🟢"
    elif score >= 0.7:
        return "🟡"
    else:
        return "🔴"


def render_extracted_value(
    label: str, ev: ExtractedValue, key_prefix: str,
) -> ExtractedValue:
    """Render an ExtractedValue field with edit controls. Returns updated EV."""
    col1, col2, col3 = st.columns([3, 1, 2])

    display_val = ev.effective()
    if isinstance(display_val, list):
        display_val = ", ".join(str(v) for v in display_val)
    elif display_val is None:
        display_val = ""

    with col1:
        new_val = st.text_input(
            f"{confidence_color(ev.confidence)} {label}",
            value=str(display_val),
            key=f"{key_prefix}_{label}",
        )

    with col2:
        st.caption(f"Conf: {ev.confidence:.0%}")
        if ev.needs_review:
            st.warning("Needs review", icon="⚠️")

    with col3:
        if ev.source_text:
            st.caption(f"📄 p.{ev.source_page or '?'}: _{ev.source_text[:80]}_")

    # Track edits
    original = str(display_val)
    if new_val != original:
        ev.reviewer_override = new_val

    return ev


def render_metadata(extraction: ContractExtraction, prefix: str):
    st.subheader("Contract Metadata")
    meta = extraction.metadata
    for field_name in meta.model_fields:
        ev = getattr(meta, field_name)
        render_extracted_value(
            field_name.replace("_", " ").title(),
            ev, f"{prefix}_meta",
        )


def render_list_section(
    title: str,
    items: list,
    field_names: list[str],
    prefix: str,
):
    st.subheader(title)
    if not items:
        st.info(f"No {title.lower()} extracted.")
        return

    for i, item in enumerate(items):
        with st.expander(f"{title} #{i+1}", expanded=(i == 0)):
            for field_name in field_names:
                ev = getattr(item, field_name, None)
                if ev and isinstance(ev, ExtractedValue):
                    render_extracted_value(
                        field_name.replace("_", " ").title(),
                        ev, f"{prefix}_{i}",
                    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("71lbs Contract Review")
page = st.sidebar.radio(
    "Navigate",
    ["Upload", "Review Queue", "Approved"],
    index=0,
)

# ---------------------------------------------------------------------------
# Upload page
# ---------------------------------------------------------------------------

if page == "Upload":
    st.title("Upload Contract PDF")
    st.markdown(
        "Upload a shipping carrier contract PDF to extract structured "
        "pricing and audit rules."
    )

    uploaded = st.file_uploader(
        "Choose a PDF file",
        type=["pdf"],
        accept_multiple_files=False,
    )

    if uploaded and st.button("Extract Contract Data", type="primary"):
        with st.spinner("Processing PDF... This may take a moment."):
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf"
            ) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name

            try:
                extraction = ingest_pdf(tmp_path)
                st.success(
                    f"Extraction complete! ID: `{extraction.id}`\n\n"
                    f"Overall confidence: **{extraction.overall_confidence:.0%}** | "
                    f"Fields needing review: **{extraction.fields_needing_review}**"
                )
                st.json(json.loads(extraction.model_dump_json()), expanded=False)
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

elif page == "Review Queue":
    st.title("Review Queue")

    extractions = list_extractions(status_filter=ExtractionStatus.PENDING)

    if not extractions:
        st.info("No extractions pending review. Upload a contract PDF first.")
    else:
        st.markdown(f"**{len(extractions)}** extraction(s) pending review.")

        selected_id = st.selectbox(
            "Select extraction to review",
            options=[e.id for e in extractions],
            format_func=lambda eid: next(
                (f"{e.file_name} ({e.id[:8]}…) — {e.overall_confidence:.0%}"
                 for e in extractions if e.id == eid),
                eid,
            ),
        )

        if selected_id:
            extraction = load_extraction(selected_id)
            if not extraction:
                st.error("Failed to load extraction")
            else:
                st.markdown("---")
                st.markdown(
                    f"**File:** {extraction.file_name} | "
                    f"**Confidence:** {extraction.overall_confidence:.0%} | "
                    f"**Review fields:** {extraction.fields_needing_review} / "
                    f"{extraction.total_fields_extracted}"
                )

                tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                    "Metadata", "Service Terms", "Surcharges",
                    "DIM Rules", "Special Terms", "Amendments",
                ])

                with tab1:
                    render_metadata(extraction, selected_id)

                with tab2:
                    render_list_section(
                        "Service Terms", extraction.service_terms,
                        ["service_type", "applicable_zones", "discount_percentage",
                         "base_rate_adjustment", "conditions", "effective_date"],
                        f"{selected_id}_st",
                    )

                with tab3:
                    render_list_section(
                        "Surcharges", extraction.surcharges,
                        ["surcharge_name", "application", "applicable_zones",
                         "modification", "discount_percentage", "effective_date"],
                        f"{selected_id}_sc",
                    )

                with tab4:
                    render_list_section(
                        "DIM Rules", extraction.dim_rules,
                        ["dim_divisor", "applicable_services", "conditions"],
                        f"{selected_id}_dr",
                    )

                with tab5:
                    render_list_section(
                        "Special Terms", extraction.special_terms,
                        ["term_name", "term_value", "conditions"],
                        f"{selected_id}_sp",
                    )

                with tab6:
                    st.subheader("Amendments")
                    for i, amd in enumerate(extraction.amendments):
                        with st.expander(
                            f"Amendment {amd.amendment_number.effective() or i+1}"
                        ):
                            for fn in ["amendment_number", "effective_date",
                                        "supersedes_version", "description"]:
                                ev = getattr(amd, fn)
                                render_extracted_value(
                                    fn.replace("_", " ").title(),
                                    ev, f"{selected_id}_amd_{i}",
                                )

                st.markdown("---")
                notes = st.text_area(
                    "Review notes",
                    value=extraction.review_notes or "",
                    key=f"notes_{selected_id}",
                )

                col_a, col_r, col_s = st.columns(3)
                with col_a:
                    if st.button("Approve", type="primary", key=f"approve_{selected_id}"):
                        extraction.review_notes = notes
                        extraction = score_extraction(extraction)
                        approve_extraction(selected_id)
                        st.success("Extraction approved!")
                        st.rerun()

                with col_r:
                    if st.button("Reject", key=f"reject_{selected_id}"):
                        extraction.review_notes = notes
                        reject_extraction(selected_id)
                        st.warning("Extraction rejected.")
                        st.rerun()

                with col_s:
                    if st.button("Save Edits", key=f"save_{selected_id}"):
                        extraction.review_notes = notes
                        extraction = score_extraction(extraction)
                        update_extraction(extraction)
                        st.success("Edits saved.")
                        st.rerun()


# ---------------------------------------------------------------------------
# Approved exports
# ---------------------------------------------------------------------------

elif page == "Approved":
    st.title("Approved Extractions")

    approved = list_extractions(status_filter=ExtractionStatus.APPROVED)

    if not approved:
        st.info("No approved extractions yet.")
    else:
        for ext in approved:
            with st.expander(
                f"{ext.file_name} — {ext.overall_confidence:.0%} "
                f"(approved {ext.extraction_timestamp[:10]})"
            ):
                st.json(json.loads(ext.model_dump_json()), expanded=False)

                json_str = ext.model_dump_json(indent=2)
                st.download_button(
                    "Download JSON",
                    data=json_str,
                    file_name=f"{ext.id}.json",
                    mime="application/json",
                    key=f"dl_{ext.id}",
                )
