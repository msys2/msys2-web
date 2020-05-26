# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os

from fastapi import FastAPI

from .web import webapp
from .fetch import start_update_thread


app = FastAPI(openapi_url=None)
app.mount("/", webapp)


# https://github.com/tiangolo/fastapi/issues/1480
@app.on_event("startup")
async def startup_event() -> None:
    if not os.environ.get("NO_UPDATE_THREAD"):
        start_update_thread()
