from __future__ import annotations

import json
from typing import Any, Callable


PROMPT = """You are extracting structured pricing data from shipping contracts.

Return STRICT JSON matching schema.

Input:
{chunk}

Output:
<json>
"""


class LLMExtractor:
    def __init__(self, llm_call: Callable[[str], str] | None = None) -> None:
        self.llm_call = llm_call

    def extract_section(self, chunk: dict[str, Any]) -> dict[str, Any]:
        if self.llm_call is None:
            return {}
        prompt = PROMPT.format(chunk=json.dumps(chunk))
        raw = self.llm_call(prompt)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}


def needs_llm(section: dict[str, Any]) -> bool:
    st = section.get("section_type")
    if st in {"earned_discount", "surcharge"}:
        return True
    text = (section.get("text_blob") or "").lower()
    return "grace discount" in text or "incentive" in text
