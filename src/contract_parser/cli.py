from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.pretty import Pretty

from .pipeline import parse_contract_pdf, to_machine_readable

app = typer.Typer(add_completion=False, help="Parse carrier/vendor contract PDFs into canonical JSON.")
console = Console()


@app.callback()
def main() -> None:
    """Contract parser CLI."""
    return


@app.command("parse")
def parse(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to a PDF contract."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write JSON output to this file (defaults to stdout)."),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty-print JSON output."),
):
    doc = parse_contract_pdf(str(pdf))
    payload = to_machine_readable(doc)

    if out is None:
        if pretty:
            console.print_json(json.dumps(payload, indent=2, sort_keys=False))
        else:
            console.print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2 if pretty else None, ensure_ascii=False)

    console.print(f"Wrote {out}")
    if doc.parse_warnings:
        console.print(Pretty({"warnings": doc.parse_warnings}))


if __name__ == "__main__":
    app()

