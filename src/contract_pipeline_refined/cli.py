from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.pretty import Pretty

from .pipeline import parse_contract_pdf_refined, to_machine_readable

app = typer.Typer(add_completion=False, help="Refined contract PDF parser (v2 schema with validation and confidence).")
console = Console()


@app.callback()
def main() -> None:
    return


@app.command("parse")
def parse_cmd(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to a PDF contract."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write JSON output to this file."),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty-print JSON output."),
):
    result = parse_contract_pdf_refined(str(pdf))
    payload = to_machine_readable(result)

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
    if result.document.parse_warnings:
        console.print(Pretty({"parse_warnings": result.document.parse_warnings}))
    if result.issues:
        console.print(Pretty({"issue_count": result.validation_summary.total_issues}))


if __name__ == "__main__":
    app()
