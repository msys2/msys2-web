# Copyright 2024 Christoph Reiter
# SPDX-License-Identifier: MIT

import json

from ..appconfig import CDX_URLS, REQUEST_TIMEOUT
from ..appstate import Severity, Vulnerability, state
from ..utils import logger
from .utils import check_needs_update, get_content_cached


def parse_cdx(data: bytes) -> dict[str, list[Vulnerability]]:
    """Parse the cdx data and returns a mapping of pkgbase names to a list of
    vulnerabilities."""

    cdx = json.loads(data)

    mapping = {}
    for component in cdx["components"]:
        name = component["name"]
        bom_ref = component["bom-ref"]
        mapping[bom_ref] = name

    def parse_vuln(vuln: dict) -> Vulnerability:
        severity = Severity.UNKNOWN
        for ratings in vuln["ratings"]:
            severity = Severity(ratings["severity"])
            break
        return Vulnerability(
            id=vuln["id"],
            url=vuln["source"]["url"],
            severity=severity)

    vuln_mapping: dict[str, list[Vulnerability]] = {}
    for vuln in cdx["vulnerabilities"]:
        for affected in vuln["affects"]:
            bom_ref = affected["ref"]
            name = mapping[bom_ref]
            vuln_mapping.setdefault(name, []).append(parse_vuln(vuln))

    return vuln_mapping


async def update_cdx() -> None:
    urls = CDX_URLS
    if not await check_needs_update(urls):
        return

    logger.info("update cdx")
    vuln_mapping = {}
    for url in urls:
        logger.info("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        logger.info(f"Done: {url!r}")
        vuln_mapping.update(parse_cdx(data))

    state.vulnerabilities = vuln_mapping
