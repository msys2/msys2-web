# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request

from .web import webapp, check_is_ready
from .api import api
from .utils import logger
from .fetch.update import update_loop


_background_tasks = set()


# https://github.com/tiangolo/fastapi/issues/1480
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not os.environ.get("NO_UPDATE_THREAD"):
        task = asyncio.create_task(update_loop())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    yield


app = FastAPI(openapi_url=None, lifespan=lifespan)
webapp.mount("/api", api, name="api")
app.mount("/", webapp)


# https://github.com/tiangolo/fastapi/issues/1472
if not os.environ.get("NO_MIDDLEWARE"):
    app.middleware("http")(check_is_ready)


@webapp.exception_handler(Exception)
async def webapp_exception_handler(request: Request, exc: Exception) -> None:
    import traceback
    logger.error(''.join(traceback.format_tb(exc.__traceback__)))
    raise exc


@api.exception_handler(Exception)
async def api_exception_handler(request: Request, exc: Exception) -> None:
    import traceback
    logger.error(''.join(traceback.format_tb(exc.__traceback__)))
    raise exc
