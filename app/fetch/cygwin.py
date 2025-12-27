# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import sys
import asyncio

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

from ..appconfig import CYGWIN_METADATA_URL, REQUEST_TIMEOUT
from ..appstate import ExtId, ExtInfo, state
from ..utils import logger, version_is_newer_than
from .utils import check_needs_update, get_content_cached


def parse_cygwin_versions(base_url: str, data: bytes) -> tuple[dict[str, ExtInfo], dict[str, ExtInfo]]:
    # This is kinda hacky: extract the source name from the src tarball and take
    # last version line before it
    version = None
    source_package = None
    versions: dict[str, ExtInfo] = {}
    versions_mingw64: dict[str, ExtInfo] = {}
    base_url = base_url.rsplit("/", 2)[0]
    in_main = True
    for line in data.decode("utf-8").splitlines():
        if line.startswith("@"):
            in_main = True
        if line.startswith("version:"):
            version = line.split(":")[-1].strip().split("-", 1)[0].split("+", 1)[0]
        elif in_main and line.startswith("source:"):
            in_main = False
            source = line.split(":", 1)[-1].strip()
            fn = source.rsplit(None, 2)[0]
            source_package = fn.rsplit("/")[-1].rsplit("-", 3)[0]
            src_url = base_url + "/" + fn
            assert version is not None
            src_url_name = src_url.rsplit("/")[-1]
            if source_package.startswith("mingw64-x86_64-"):
                info_name = source_package.split("-", 2)[-1]
                if info_name in versions_mingw64:
                    existing_version = versions_mingw64[info_name][0]
                    if not version_is_newer_than(version, existing_version):
                        continue
                versions_mingw64[info_name] = ExtInfo(
                    info_name, version, 0,
                    f"https://cygwin.com/packages/summary/{source_package}-src.html",
                    {src_url: src_url_name})
            else:
                info_name = source_package
                if info_name in versions:
                    existing_version = versions[info_name][0]
                    if not version_is_newer_than(version, existing_version):
                        continue
                versions[info_name] = ExtInfo(
                    info_name, version, 0,
                    f"https://cygwin.com/packages/summary/{source_package}-src.html",
                    {src_url: src_url_name})
    return versions, versions_mingw64


async def update_cygwin_versions() -> None:
    url = CYGWIN_METADATA_URL
    if not await check_needs_update([url]):
        return
    logger.info("update cygwin info")
    logger.info(f"Loading {url!r}")
    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
    data = zstd.decompress(data)
    cygwin_versions, cygwin_versions_mingw64 = await asyncio.to_thread(parse_cygwin_versions, url, data)
    state.set_ext_infos(ExtId("cygwin", "Cygwin", True, True), cygwin_versions)
    state.set_ext_infos(ExtId("cygwin-mingw64", "Cygwin-mingw64", False, True), cygwin_versions_mingw64)
