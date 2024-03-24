# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import gzip
import json

from ..appconfig import REQUEST_TIMEOUT, SRCINFO_URLS
from ..appstate import PkgExtra, SrcInfoPackage, state
from ..pkgextra import extra_to_pkgextra_entry
from ..utils import logger
from .pypi import update_pypi_versions
from .utils import check_needs_update, get_content_cached


async def update_sourceinfos() -> None:
    urls = SRCINFO_URLS
    if not await check_needs_update(urls):
        return

    logger.info("update sourceinfos")
    result: dict[str, SrcInfoPackage] = {}
    pkgextra = PkgExtra(packages={})

    for url in urls:
        logger.info("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        json_obj = json.loads(gzip.decompress(data).decode("utf-8"))
        for hash_, m in json_obj.items():
            extra = m.get("extra", {})
            pkgbase = None
            for repo, srcinfo in m["srcinfo"].items():
                for pkg in SrcInfoPackage.for_srcinfo(srcinfo, repo, m["repo"], m["path"], m["date"]):
                    pkgbase = pkg.pkgbase
                    if pkg.pkgname in result:
                        logger.info(f"WARN: duplicate: {pkg.pkgname} provided by "
                                    f"{pkg.pkgbase} and {result[pkg.pkgname].pkgbase}")
                    result[pkg.pkgname] = pkg
            if pkgbase is not None:
                pkgextra.packages[pkgbase] = extra_to_pkgextra_entry(extra)

    state.pkgextra = pkgextra
    state.sourceinfos = result
    await update_pypi_versions(pkgextra)
