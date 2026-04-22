"""
Stage-2 LLM verification for deterministic parser output.

The verifier reviews already-extracted fields against document text and returns
targeted corrections only. If no API key is configured, this stage is skipped.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from app.models.schema import ContractExtraction, ExtractedValue
from app.pipeline.pdf_parser import ParsedDocument

logger = logging.getLogger(__name__)
_MAX_VERIFY_TEXT_CHARS = 60000
_LOCAL_VERIFY_TIMEOUT_SEC = 45


def _is_ollama_base_url() -> bool:
    url = (LLM_BASE_URL or "").lower()
    return "localhost:11434" in url or "127.0.0.1:11434" in url


def _is_groq_base_url() -> bool:
    return "groq.com" in (LLM_BASE_URL or "").lower()


def _supports_json_response_format() -> bool:
    # Groq and OpenAI-style cloud providers support it; Ollama does not.
    return not _is_ollama_base_url()


def _get_max_verify_chars() -> int:
    if _is_ollama_base_url():
        return 6000
    return 60000


def _looks_like_invoice_extraction(extraction: ContractExtraction) -> bool:
    for st in extraction.special_terms:
        name = str(st.term_name.effective() or "").strip().lower()
        value = str(st.term_value.effective() or "").strip().lower()
        if name == "document type" and value == "invoice":
            return True
    return False


def _looks_like_non_contract_text(text: str) -> bool:
    head = (text or "")[:12000].lower()
    non_contract_markers = [
        "statement of work",
        "scope of work",
        "master services agreement",
        "proposal",
        "invoice number",
        "delivery service invoice",
    ]
    contract_markers = [
        "pricing agreement",
        "service terms",
        "surcharge",
        "dim divisor",
        "fedex",
        "ups",
    ]
    return any(m in head for m in non_contract_markers) and not any(m in head for m in contract_markers)

_VERIFY_PROMPT = """You are a shipping contract data quality reviewer. A deterministic parser has extracted structured pricing data from a carrier contract PDF. Your job is to find and correct specific types of extraction errors.

Review the extracted fields below against the contract text and apply corrections ONLY for these specific error types:
1. Discount percentages that appear to be off by a factor (e.g., parser extracted 4.5 when the contract says 45%)
2. Effective dates or expiration dates that were missed or extracted incorrectly
3. DIM divisor extracted as wrong value (contract says 139 but parser returned 166, or vice versa)
4. Fuel surcharge discount marked as null when the contract text contains an explicit percentage reduction
5. GSR status marked as "active" when the contract text contains waiver language
6. Earned discount tiers where a tier threshold was parsed as the wrong dollar amount

For each correction, return ONLY the field path, the original value, your corrected value, and a one-sentence reason citing the specific contract text that supports your correction.

If you find no errors of these specific types, return an empty corrections array. Do not invent corrections. Do not correct formatting or normalize values that are already semantically correct.

Return JSON only: {"corrections": [{"field": "...", "original": ..., "corrected": ..., "reason": "..."}]}
"""


def _safe_preview(extraction: ContractExtraction) -> dict[str, Any]:
    """Compact but complete extraction payload for the verifier."""
    return extraction.model_dump()


def _collect_verifier_candidates(
    value: Any,
    path: str,
    out: list[dict[str, Any]],
    review_paths: set[str],
) -> None:
    if isinstance(value, ExtractedValue):
        if value.confidence < 0.85 or value.needs_review or path in review_paths:
            out.append(
                {
                    "field_path": path,
                    "value": value.value,
                    "confidence": value.confidence,
                    "needs_review": value.needs_review,
                    "source_page": value.source_page,
                    "source_text": (value.source_text or "")[:240],
                }
            )
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _collect_verifier_candidates(item, f"{path}[{idx}]" if path else f"[{idx}]", out, review_paths)
        return
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        for key in dumped:
            _collect_verifier_candidates(
                getattr(value, key),
                f"{path}.{key}" if path else key,
                out,
                review_paths,
            )


def _low_confidence_json_for_verifier(extraction: ContractExtraction, max_chars: int = 4000) -> tuple[str, list[dict[str, Any]]]:
    review_paths = set(
        str(p).strip()
        for p in getattr(extraction, "fields_requiring_review", []) or []
        if str(p).strip()
    )
    candidates: list[dict[str, Any]] = []
    _collect_verifier_candidates(extraction, "", candidates, review_paths)
    candidates.sort(key=lambda c: (float(c.get("confidence") or 0.0), c.get("field_path") or ""))

    chosen: list[dict[str, Any]] = []
    for c in candidates:
        probe = chosen + [c]
        payload = json.dumps({"low_confidence_fields": probe}, default=str)
        if len(payload) > max_chars:
            break
        chosen = probe

    if not chosen:
        return "", []
    return json.dumps({"low_confidence_fields": chosen}, default=str), chosen


def _keyword_sections_for_verifier(doc: ParsedDocument, candidate_fields: list[dict[str, Any]], max_chars: int = 12000) -> str:
    text = doc.full_text or ""
    if not text:
        return ""
    head = text[:8000]
    keywords = {"discount", "fuel", "gsr", "dim", "minimum", "accessorial"}
    for field in candidate_fields:
        path = str(field.get("field_path") or "").lower()
        for token in re.split(r"[^a-z0-9_]+", path):
            if token and len(token) > 2:
                keywords.add(token)

    lower = text.lower()
    spans: list[tuple[int, int]] = []
    for kw in sorted(keywords):
        for m in re.finditer(re.escape(kw), lower):
            spans.append((max(0, m.start() - 500), min(len(text), m.end() + 500)))
            if len(spans) >= 24:
                break
        if len(spans) >= 24:
            break
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    sections = [text[s:e] for s, e in merged]
    payload = head
    if sections:
        payload += "\n\n--- TARGETED KEYWORD SECTIONS ---\n\n" + "\n\n---\n\n".join(sections)
    return payload[: min(max_chars, _get_max_verify_chars())]


def _parse_json_lenient(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        # Fallback for local models that wrap JSON in prose/code fences.
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return {}
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def _iter_path_parts(path: str) -> list[str]:
    return [p for p in re.split(r"\.(?![^\[]*\])", path) if p]


def _resolve_object_at_path(root: Any, path: str) -> tuple[Any | None, str | None]:
    """Resolve parent object and last field key from a path."""
    parts = _iter_path_parts(path)
    if not parts:
        return None, None

    obj = root
    for part in parts[:-1]:
        list_match = re.match(r"^([a-zA-Z_]\w*)\[(\d+)\]$", part)
        if list_match:
            name, idx = list_match.group(1), int(list_match.group(2))
            seq = getattr(obj, name, None)
            if seq is None or idx >= len(seq):
                return None, None
            obj = seq[idx]
            continue
        if not hasattr(obj, part):
            return None, None
        obj = getattr(obj, part)
    return obj, parts[-1]


def _apply_single_correction(extraction: ContractExtraction, corr: dict[str, Any]) -> None:
    path = str(corr.get("field_path") or corr.get("field") or "").strip()
    if not path:
        return

    parent, last = _resolve_object_at_path(extraction, path)
    if parent is None or last is None or not hasattr(parent, last):
        logger.warning("LLM verifier skipped unknown field path: %s", path)
        return

    field_obj = getattr(parent, last)
    if not isinstance(field_obj, ExtractedValue):
        logger.warning("LLM verifier target is not ExtractedValue: %s", path)
        return

    old_value = field_obj.value
    new_value = corr.get("corrected_value", corr.get("corrected"))
    if old_value == new_value:
        return

    field_obj.original_parser_value = old_value
    field_obj.llm_corrected_value = new_value
    field_obj.was_llm_corrected = True
    field_obj.correction_reason = corr.get("correction_reason", corr.get("reason"))
    field_obj.confidence_rationale = corr.get("confidence_rationale")
    field_obj.value = new_value

    conf = corr.get("confidence")
    if isinstance(conf, (int, float)):
        field_obj.confidence = max(0.0, min(1.0, float(conf)))
    if corr.get("source_page") is not None:
        field_obj.source_page = corr.get("source_page")
    if corr.get("source_text"):
        field_obj.source_text = str(corr.get("source_text"))[:240]


def _set_diag(
    extraction: ContractExtraction,
    *,
    verifier_called: bool,
    verifier_skipped_reason: str | None,
    corrections_proposed: int = 0,
    corrections_accepted: int = 0,
    verifier_timeout: bool = False,
    verifier_raw_response_preview: str | None = None,
) -> None:
    extraction.verifier_diagnostics = {
        "verifier_called": verifier_called,
        "verifier_skipped_reason": verifier_skipped_reason,
        "verifier_model_used": LLM_MODEL,
        "corrections_proposed": corrections_proposed,
        "corrections_accepted": corrections_accepted,
        "verifier_timeout": verifier_timeout,
        "verifier_raw_response_preview": verifier_raw_response_preview,
    }


def verify_extraction_with_llm(
    extraction: ContractExtraction,
    doc: ParsedDocument,
) -> ContractExtraction:
    """
    Verify and optionally correct deterministic extraction output.

    Returns extraction unchanged when API key is unavailable or verification fails.
    """
    if not LLM_API_KEY:
        _set_diag(
            extraction,
            verifier_called=False,
            verifier_skipped_reason="no LLM_API_KEY configured",
        )
        logger.info("Stage 2 verifier skipped: no LLM_API_KEY configured")
        return extraction
    if _looks_like_invoice_extraction(extraction):
        _set_diag(
            extraction,
            verifier_called=False,
            verifier_skipped_reason="invoice-classified document",
        )
        logger.info("Stage 2 verifier skipped: invoice-classified document")
        return extraction
    if _is_groq_base_url() and LLM_MODEL == "llama-3.3-70b-versatile" and _looks_like_non_contract_text(doc.full_text):
        _set_diag(
            extraction,
            verifier_called=False,
            verifier_skipped_reason="non-contract document detected",
        )
        logger.info("Stage 2 verifier skipped: non-contract document detected")
        return extraction

    low_conf_json, candidate_fields = _low_confidence_json_for_verifier(extraction, max_chars=4000)
    if not candidate_fields:
        _set_diag(
            extraction,
            verifier_called=False,
            verifier_skipped_reason="all fields high confidence, verification not needed",
        )
        logger.info("Stage 2 verifier skipped: all fields high confidence")
        return extraction

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            timeout=_LOCAL_VERIFY_TIMEOUT_SEC if _is_ollama_base_url() else None,
            max_retries=0 if _is_ollama_base_url() else 2,
        )
        payload = (
            "EXTRACTED DATA:\n"
            f"{low_conf_json}\n\n"
            "CONTRACT TEXT (relevant sections):\n"
            f"{_keyword_sections_for_verifier(doc, candidate_fields, max_chars=12000)}"
        )
        create_kwargs: dict[str, Any] = {
            "model": LLM_MODEL,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _VERIFY_PROMPT},
                {"role": "user", "content": payload},
            ],
        }
        # Some local OpenAI-compatible servers reject response_format.
        if _supports_json_response_format():
            create_kwargs["response_format"] = {"type": "json_object"}
        else:
            # Keep local-memory footprint low for smaller machines.
            create_kwargs["extra_body"] = {"options": {"num_ctx": 512}}
        response = client.chat.completions.create(**create_kwargs)
        raw = response.choices[0].message.content or "{}"
        parsed = _parse_json_lenient(raw)
        corrections = parsed.get("corrections", [])
        if not isinstance(corrections, list):
            _set_diag(
                extraction,
                verifier_called=True,
                verifier_skipped_reason="invalid corrections payload",
            )
            logger.warning("Stage 2 verifier returned invalid corrections payload")
            return extraction

        accepted = 0
        for corr in corrections:
            if isinstance(corr, dict):
                before = extraction.model_dump()
                _apply_single_correction(extraction, corr)
                if extraction.model_dump() != before:
                    accepted += 1

        _set_diag(
            extraction,
            verifier_called=True,
            verifier_skipped_reason=None,
            corrections_proposed=len(corrections),
            corrections_accepted=accepted,
            verifier_timeout=False,
            verifier_raw_response_preview=(raw or "")[:1000],
        )
        logger.info("Stage 2 verifier applied %d correction(s)", len(corrections))
        return extraction
    except Exception as exc:
        msg = str(exc)
        low = msg.lower()
        is_rate_limit = "429" in low or "rate limit" in low or "insufficient_quota" in low
        is_auth = "unauthorized" in low or "authentication" in low or "invalid api key" in low or "forbidden" in low
        if is_rate_limit:
            logger.error("Stage 2 verifier provider returned 429/rate-limit: %s", msg)
        elif is_auth:
            logger.error("Stage 2 verifier provider authentication error: %s", msg)
        else:
            logger.error("Stage 2 verifier failed: %s", msg)
        _set_diag(
            extraction,
            verifier_called=True,
            verifier_skipped_reason=msg[:180],
            verifier_timeout="timed out" in low or "timeout" in low,
            verifier_raw_response_preview=msg[:1000],
        )
        return extraction

