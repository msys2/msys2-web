# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os
import asyncio

from fastapi import FastAPI

from .web import webapp
from .fetch import update_loop


app = FastAPI(openapi_url=None)
app.mount("/", webapp)


# https://github.com/tiangolo/fastapi/issues/1480
@app.on_event("startup")
async def startup_event() -> None:
    if not os.environ.get("NO_UPDATE_THREAD"):
        asyncio.create_task(update_loop())
