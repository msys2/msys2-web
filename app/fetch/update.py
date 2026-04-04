# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import asyncio
import functools
import sys
import traceback

from aiolimiter import AsyncLimiter

from .. import appconfig
from ..appconfig import UPDATE_INTERVAL, UPDATE_MIN_INTERVAL, UPDATE_MIN_RATE
from ..appstate import state
from ..utils import logger
from .arch import update_arch_versions
from .buildstatus import update_build_status
from .cygwin import update_cygwin_versions
from .gentoo import update_gentoo_versions
from .source import update_source
from .sourceinfos import update_sourceinfos
from .cdx import update_cdx


_rate_limit = AsyncLimiter(UPDATE_MIN_RATE, UPDATE_MIN_INTERVAL)


@functools.cache
def _get_update_queue() -> asyncio.Queue[None]:
    return asyncio.Queue(maxsize=1)


async def wait_for_update() -> None:
    update_queue = _get_update_queue()
    await update_queue.get()


def queue_update() -> None:
    update_queue = _get_update_queue()
    try:
        update_queue.put_nowait(None)
    except asyncio.QueueFull:
        pass


async def trigger_loop() -> None:
    while True:
        logger.info(f"Sleeping for {UPDATE_INTERVAL}")
        await asyncio.sleep(UPDATE_INTERVAL)
        queue_update()


_background_tasks = set()


async def update_loop() -> None:
    task = asyncio.create_task(trigger_loop())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    while True:
        async with _rate_limit:
            logger.info("check for updates")
            try:
                awaitables = []
                if not appconfig.NO_EXTERN:
                    awaitables.extend(
                        [
                            update_cygwin_versions(),
                            update_gentoo_versions(),
                            update_arch_versions(),
                        ]
                    )
                awaitables.extend(
                    [
                        update_source(),
                        update_sourceinfos(),
                        update_build_status(),
                        update_cdx(),
                    ]
                )
                await asyncio.gather(*awaitables)
                state.ready = True
                logger.info("done")
            except Exception:
                traceback.print_exc(file=sys.stdout)
        logger.info("Waiting for next update")
        await wait_for_update()
        # XXX: it seems some updates don't propagate right away, so wait a bit
        await asyncio.sleep(5)
