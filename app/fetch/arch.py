# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import asyncio
import json

from ..appconfig import ARCH_REPO_CONFIG, AUR_METADATA_URL, REQUEST_TIMEOUT
from ..appstate import ExtId, ExtInfo, Repository, state
from ..utils import (arch_version_to_msys, extract_upstream_version, logger,
                     version_is_newer_than)
from .source import parse_repo
from .utils import check_needs_update, get_content_cached


async def update_arch_versions() -> None:
    urls = [i[0] for i in ARCH_REPO_CONFIG]
    if not await check_needs_update(urls):
        return

    logger.info("update versions")
    arch_versions: dict[str, ExtInfo] = {}
    awaitables = []
    for (url, repo) in ARCH_REPO_CONFIG:
        download_url = url.rsplit("/", 1)[0]
        awaitables.append(
            parse_repo(
                Repository(repo, "", "", "", download_url, download_url, ""),
                False
            )
        )

    # priority: real packages > real provides > aur packages > aur provides

    for sources in (await asyncio.gather(*awaitables)):
        for source in sources.values():
            version = extract_upstream_version(arch_version_to_msys(source.version))
            for p in source.packages.values():
                url = f"https://archlinux.org/packages/{p.repo}/{p.arch}/{p.name}/"

                if p.name in arch_versions:
                    old_ver = arch_versions[p.name][0]
                    if version_is_newer_than(version, old_ver):
                        arch_versions[p.name] = ExtInfo(p.name, version, p.builddate, url, {})
                else:
                    arch_versions[p.name] = ExtInfo(p.name, version, p.builddate, url, {})

            url = f"https://archlinux.org/packages/{source.repos[0]}/{source.arches[0]}/{source.name}/"
            if source.name in arch_versions:
                old_ver = arch_versions[source.name][0]
                if version_is_newer_than(version, old_ver):
                    arch_versions[source.name] = ExtInfo(source.name, version, source.date, url, {})
            else:
                arch_versions[source.name] = ExtInfo(source.name, version, source.date, url, {})

            # use provides as fallback
            for p in source.packages.values():
                url = f"https://archlinux.org/packages/{p.repo}/{p.arch}/{p.name}/"

                for provides in sorted(p.provides.keys()):
                    if provides not in arch_versions:
                        arch_versions[provides] = ExtInfo(provides, version, p.builddate, url, {})

    logger.info("done")
    state.set_ext_infos(ExtId("archlinux", "Arch Linux", False, True), arch_versions)

    logger.info("update versions from AUR")
    aur_versions: dict[str, ExtInfo] = {}
    r = await get_content_cached(AUR_METADATA_URL,
                                 timeout=REQUEST_TIMEOUT)
    items = json.loads(r)
    for item in items:
        name = item["Name"]
        if name in aur_versions:
            continue
        version = item["Version"]
        msys_ver = extract_upstream_version(arch_version_to_msys(version))
        last_modified = item["LastModified"]
        url = f"https://aur.archlinux.org/packages/{name}"
        aur_versions[name] = ExtInfo(name, msys_ver, last_modified, url, {})

    for item in items:
        name = item["Name"]
        for provides in sorted(item.get("Provides", [])):
            if provides in aur_versions:
                continue
            version = item["Version"]
            msys_ver = extract_upstream_version(arch_version_to_msys(version))
            last_modified = item["LastModified"]
            url = f"https://aur.archlinux.org/packages/{name}"
            aur_versions[provides] = ExtInfo(provides, msys_ver, last_modified, url, {})

    logger.info("done")
    state.set_ext_infos(ExtId("aur", "AUR", True, True), aur_versions)
