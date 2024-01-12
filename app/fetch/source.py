# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import asyncio
import io
from typing import Any

from ..appconfig import REQUEST_TIMEOUT
from ..appstate import (DepType, Package, Repository, Source, get_repositories,
                        state)
from ..exttarfile import ExtTarFile
from ..utils import logger
from .utils import check_needs_update, get_content_cached


def parse_desc(t: str) -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}
    cat = None
    values: list[str] = []
    for l in t.splitlines():
        l = l.strip()
        if cat is None:
            cat = l
        elif not l:
            d[cat] = values
            cat = None
            values = []
        else:
            values.append(l)
    if cat is not None:
        d[cat] = values
    return d


async def parse_repo(repo: Repository, include_files: bool = True) -> dict[str, Source]:
    sources: dict[str, Source] = {}

    def add_desc(d: Any) -> None:
        source = Source.from_desc(d, repo)
        if source.name not in sources:
            sources[source.name] = source
        else:
            source = sources[source.name]

        source.add_desc(d, repo)

    repo_url = repo.files_url if include_files else repo.db_url
    logger.info("Loading %r" % repo_url)
    data = await get_content_cached(repo_url, timeout=REQUEST_TIMEOUT)

    with io.BytesIO(data) as f:
        with ExtTarFile.open(fileobj=f, mode="r") as tar:
            packages: dict[str, list] = {}
            for info in tar:
                package_name = info.name.split("/", 1)[0]
                infofile = tar.extractfile(info)
                if infofile is None:
                    continue
                with infofile:
                    packages.setdefault(package_name, []).append(
                        (info.name, infofile.read()))

    for package_name, infos in sorted(packages.items()):
        t = ""
        for name, data in sorted(infos):
            if name.endswith("/desc"):
                t += data.decode("utf-8")
            elif name.endswith("/depends"):
                t += data.decode("utf-8")
            elif name.endswith("/files"):
                t += data.decode("utf-8")
        desc = parse_desc(t)
        add_desc(desc)

    return sources


def fill_rdepends(sources: dict[str, Source]) -> None:
    deps: dict[str, dict[Package, set[DepType]]] = {}
    for s in sources.values():
        for p in s.packages.values():
            for n, r in p.depends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.NORMAL)
            for n, r in p.makedepends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.MAKE)
            for n, r in p.optdepends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.OPTIONAL)
            for n, r in p.checkdepends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.CHECK)

    for s in sources.values():
        for p in s.packages.values():
            rdeps = [deps.get(p.name, dict())]
            for prov in p.provides:
                rdeps.append(deps.get(prov, dict()))

            merged: dict[Package, set[DepType]] = {}
            for rd in rdeps:
                for rp, rs in rd.items():
                    merged.setdefault(rp, set()).update(rs)

            p.rdepends = merged


def fill_provided_by(sources: dict[str, Source]) -> None:

    provided_by: dict[str, set[Package]] = {}
    for s in sources.values():
        for p in s.packages.values():
            for provides in p.provides.keys():
                provided_by.setdefault(provides, set()).add(p)
    for s in sources.values():
        for p in s.packages.values():
            if p.name in provided_by:
                p.provided_by = provided_by[p.name]


async def update_source() -> None:
    """Raises RequestException"""

    urls = [repo.files_url for repo in get_repositories()]
    if not await check_needs_update(urls):
        return

    logger.info("update source")

    final: dict[str, Source] = {}
    awaitables = []
    for repo in get_repositories():
        awaitables.append(parse_repo(repo))
    for sources in await asyncio.gather(*awaitables):
        for name, source in sources.items():
            if name in final:
                final[name].packages.update(source.packages)
            else:
                final[name] = source

    fill_rdepends(final)
    fill_provided_by(final)
    state.sources = final
