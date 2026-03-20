from contract_parser.table_extractor import extract_tables


def test_fedex_multi_page_zone_weight_table_normalization() -> None:
    sections = [
        {
            "page": 1,
            "section_type": "service_pricing",
            "service_name": "FedEx 2Day",
            "tables": [
                {
                    "content": [
                        ["Weight", "Zones 2 3 4 5", "Discount"],
                        ["1.0 - 10.0 lb(s)", "", "57%"],
                    ]
                }
            ],
        },
        {
            "page": 2,
            "section_type": "service_pricing",
            "service_name": "FedEx 2Day",
            "tables": [
                {
                    "content": [
                        ["Weight", "All Zones", "Discount"],
                        ["21.0 + lb", "", "45%"],
                    ]
                }
            ],
        },
    ]

    rows = extract_tables(sections)
    assert len(rows) == 2
    assert rows[0]["zones"] == [2, 3, 4, 5]
    assert rows[0]["weight_range"]["min"] == 1.0
    assert rows[0]["weight_range"]["max"] == 10.0
    assert rows[0]["discount"] == 57.0
    assert rows[1]["zones"] == "all"
    assert rows[1]["weight_range"]["min"] == 21.0


def test_all_applicable_weights_maps_to_all() -> None:
    sections = [
        {
            "page": 1,
            "section_type": "service_pricing",
            "service_name": "UPS Ground",
            "tables": [
                {
                    "content": [
                        ["Weight", "Zones", "Discount"],
                        ["All Applicable Weights", "2 3 4", "12%"],
                    ]
                }
            ],
        }
    ]
    rows = extract_tables(sections)
    assert rows[0]["weight_range"] == "all"
