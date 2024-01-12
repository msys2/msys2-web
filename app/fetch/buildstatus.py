# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from ..appconfig import BUILD_STATUS_URLS, REQUEST_TIMEOUT
from ..appstate import BuildStatus, state
from ..utils import logger
from .utils import check_needs_update, get_content_cached_mtime


async def update_build_status() -> None:
    urls = BUILD_STATUS_URLS
    if not await check_needs_update(urls):
        return

    logger.info("update build status")
    responses = []
    for url in urls:
        logger.info("Loading %r" % url)
        data, mtime = await get_content_cached_mtime(url, timeout=REQUEST_TIMEOUT)
        logger.info(f"Done: {url!r}, {str(mtime)!r}")
        responses.append((mtime, url, data))

    # use the newest of all status summaries
    newest = sorted(responses)[-1]
    logger.info(f"Selected: {newest[1]!r}")
    state.build_status = BuildStatus.parse_raw(newest[2])
