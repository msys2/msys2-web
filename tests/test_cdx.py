import json

from app.fetch.cdx import parse_cdx


def test_parse_cdx_unaffected_versions_and_ranges():
    bom_ref = "BomRef.component"
    data = {
        "components": [
            {
                "bom-ref": bom_ref,
                "properties": [{"name": "msys2:pkgbase", "value": "example"}],
            }
        ],
        "vulnerabilities": [
            {
                "id": "CVE-2026-0001",
                "source": {"url": "https://example.com/CVE-2026-0001"},
                "ratings": [{"severity": "high"}],
                "affects": [
                    {
                        "ref": bom_ref,
                        "versions": [
                            {"version": "0.22.0", "status": "affected"},
                            {"version": "0.23.0", "status": "unaffected"},
                            {"range": "vers:pypi/>=0.32.0", "status": "unaffected"},
                            {"range": "vers:generic/>=3.0.14", "status": "unaffected"},
                            {"range": "vers:generic/>=4.0.7", "status": "unaffected"},
                            {"range": "vers:generic/>=5.0.4", "status": "unaffected"},
                            {
                                "range": "vers:npm/>=1.0.2|<2.0.0",
                                "status": "unaffected",
                            },
                            {
                                "range": "vers:generic/>=1.0%3Ebeta|<2.0%7Crc|3.0%2525",
                                "status": "unaffected",
                            },
                            {"range": "vers:pypi/<0.22.0", "status": "affected"},
                        ],
                    }
                ],
            }
        ],
    }

    vulnerabilities = parse_cdx(json.dumps(data).encode())

    assert vulnerabilities["example"][0].unaffected_versions == [
        "0.23.0",
        ">=0.32.0",
        ">=3.0.14",
        ">=4.0.7",
        ">=5.0.4",
        ">=1.0.2|<2.0.0",
        ">=1.0>beta|<2.0|rc|3.0%25",
    ]
