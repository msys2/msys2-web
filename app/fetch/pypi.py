# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import datetime
import gzip
import json
import re
from urllib.parse import unquote

from ..appconfig import PYPI_URLS, REQUEST_TIMEOUT
from ..appstate import ExtId, ExtInfo, state
from ..pkgextra import PkgExtra
from ..utils import logger
from .utils import check_needs_update, get_content_cached


def normalize(name: str) -> str:
    # https://packaging.python.org/en/latest/specifications/name-normalization/
    return re.sub(r"[-_.]+", "-", name).lower()


def extract_pypi_project_from_purl(purl: str) -> str | None:
    """Extract the project name from a PyPI PURL.
    If not a proper PyPI PURL, return None.
    """

    if not purl.startswith("pkg:pypi/"):
        return None
    path_and_rest = purl[len("pkg:pypi/"):]
    path_part = path_and_rest.split("@", 1)[0].split("?", 1)[0].split("#", 1)[0]
    parts = path_part.rsplit("/", 1)
    if not parts or not parts[-1]:
        return None
    return unquote(parts[-1])


def extract_pypi_project_from_references(references: dict[str, list[str | None]]) -> str | None:
    for purl in references.get("purl", []):
        if purl is None:
            continue
        project = extract_pypi_project_from_purl(purl)
        if project is not None:
            return project

    return None


class PyPIExtId(ExtId):

    def get_key_from_references(self, references: dict[str, list[str | None]]) -> str | None:
        return extract_pypi_project_from_references(references)


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
        pypi_name = extract_pypi_project_from_references(entry.references)
        if pypi_name is None:
            continue
        assert isinstance(pypi_name, str)
        normalized_name = normalize(pypi_name)
        if normalized_name in projects:
            project = projects[normalized_name]
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

    state.set_ext_infos(PyPIExtId("pypi", "PyPI", False, False), pypi_versions)
