from contract_parser.pipeline import run_pipeline
from contract_parser.types import Contract, Metadata, PricingRule, Service
from contract_parser.validator import validate


def test_validation_flags_bad_ranges_and_zones() -> None:
    contract = Contract(
        metadata=Metadata(carrier="ups", customer_name="", agreement_number="", effective_date=""),
        services=[
            Service(
                service_name="UPS Ground",
                pricing=[
                    PricingRule(zones=[0, 9], weight_range={"min": 10.0, "max": 10.0}, discount=120.0),
                ],
            )
        ],
    )
    result = validate(contract)
    assert result["confidence"] < 1.0
    assert any("invalid discount" in i for i in result["issues"])
    assert any("invalid zones" in i for i in result["issues"])


def test_pipeline_output_shape(monkeypatch) -> None:
    def fake_ingest(_: str) -> list[dict]:
        return [
            {
                "page": 1,
                "blocks": [
                    {"type": "text", "content": "UPS Agreement Number ABC123", "bbox": [0, 0, 1, 1], "font_size": 10},
                    {"type": "text", "content": "Effective Date 01/01/2026", "bbox": [0, 0, 1, 1], "font_size": 10},
                    {
                        "type": "table",
                        "content": [
                            ["Weight", "Zones 2 3 4", "Discount"],
                            ["1.0 - 10.0 lb", "", "30%"],
                        ],
                    },
                ],
            }
        ]

    monkeypatch.setattr("contract_parser.pipeline.ingest_pdf", fake_ingest)
    output = run_pipeline("dummy.pdf")
    assert "contract" in output
    assert "confidence" in output
    assert "raw_sections" in output
    assert output["contract"]["metadata"]["carrier"] == "ups"
