from typing import Any

__all__ = ["parse_contract_pdf"]


def __getattr__(name: str) -> Any:
    if name == "parse_contract_pdf":
        from .pipeline import parse_contract_pdf

        return parse_contract_pdf
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
