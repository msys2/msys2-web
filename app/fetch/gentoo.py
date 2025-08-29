# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import asyncio
import functools
import io
import tarfile

from ..appconfig import GENTOO_SNAPSHOT_URL, REQUEST_TIMEOUT
from ..appstate import ExtId, ExtInfo, state
from ..utils import logger, vercmp
from .utils import check_needs_update, get_content_cached


async def update_gentoo_versions() -> None:
    url = GENTOO_SNAPSHOT_URL
    if not await check_needs_update([url]):
        return
    logger.info("update gentoo info")
    logger.info(f"Loading {url!r}")
    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
    gentoo_versions = await asyncio.to_thread(parse_gentoo_versions, data)
    # fallback, since parsing isn't perfect and we include unstable versions
    state.set_ext_infos(ExtId("gentoo", "Gentoo", True, True), gentoo_versions)


def parse_gentoo_versions(data: bytes) -> dict[str, ExtInfo]:
    packages: dict[str, dict[str, int]] = {}
    masked = set()
    with io.BytesIO(data) as f:
        with tarfile.open(fileobj=f, mode="r") as tar:
            for tarinfo in tar:
                name = tarinfo.name

                # Find package versions that are masked because they are unstable
                # This only covers a tiny amount of packages, but it's better than nothing
                if name.endswith("/profiles/package.mask") and tarinfo.isreg():
                    content = tar.extractfile(tarinfo)
                    assert content is not None
                    for line in content.read().decode().splitlines():
                        if line.startswith("~"):
                            masked.add(line[1:])

                # All packages
                if name.endswith(".ebuild") and name.count("/") > 1 and tarinfo.isreg():
                    gentoo_name = name.rsplit("/", 1)[0].split("/", 1)[-1]
                    mtime = tarinfo.mtime
                    package_name = gentoo_name.split("/", 1)[1]
                    basename = name.rsplit("/", 1)[-1]
                    version = basename[len(package_name) + 1:].rsplit(".", 1)[0]
                    packages.setdefault(gentoo_name, {})[version] = int(mtime)

    infos = {}
    for gentoo_name, versions in packages.items():

        # Remove all masked versions and live ebuilds using 9999 as a version
        # We are not parsing the KEYWORDS to see which versions are stable, so
        # we also get testing packages :/
        for version in list(versions):
            if f"{gentoo_name}-{version}" in masked:
                del versions[version]
            elif "9999" in version:
                del versions[version]

        # No version left, skip
        if not versions:
            continue

        # TODO: Not sure if the version sorting is correct for gentoo..
        newest_version = sorted(versions, key=functools.cmp_to_key(vercmp))[-1]
        package_name = gentoo_name.split("/", 1)[1]
        info = ExtInfo(gentoo_name, newest_version, versions[newest_version],
                       f"https://packages.gentoo.org/packages/{gentoo_name}", {})
        # Add with the gentoo category and without, so we can find it by package name automatically,
        # but can also reference it unambiguously by gentoo name
        infos[gentoo_name] = info
        infos[package_name] = info
        if gentoo_name.startswith("dev-python/"):
            infos["python-" + package_name] = info

    return infos
