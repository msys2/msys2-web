# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import datetime
import gzip
import json

from ..appconfig import PYPI_URLS, REQUEST_TIMEOUT
from ..appstate import ExtId, ExtInfo, state
from ..pkgextra import PkgExtra
from ..utils import logger
from .utils import check_needs_update, get_content_cached


async def update_pypi_versions(pkgextra: PkgExtra) -> None:
    urls = PYPI_URLS
    if not await check_needs_update(urls):
        return

    projects = {}
    for url in urls:
        logger.info("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        json_obj = json.loads(gzip.decompress(data).decode("utf-8"))
        projects.update(json_obj.get("projects", {}))

    pypi_versions = {}
    for entry in pkgextra.packages.values():
        if "pypi" not in entry.references:
            continue
        pypi_name = entry.references["pypi"]
        assert isinstance(pypi_name, str)
        if pypi_name in projects:
            project = projects[pypi_name]
            info = project["info"]
            project_urls = project.get("urls", [])
            oldest_timestamp = 0
            for url_entry in project_urls:
                dt = datetime.datetime.fromisoformat(
                    url_entry["upload_time_iso_8601"].replace("Z", "+00:00"))
                timestamp = int(dt.timestamp())
                if oldest_timestamp == 0 or timestamp < oldest_timestamp:
                    oldest_timestamp = timestamp
            pypi_versions[pypi_name] = ExtInfo(
                pypi_name, info["version"], oldest_timestamp, info["project_url"], {})

    state.set_ext_infos(ExtId("pypi", "PyPI", True), pypi_versions)
