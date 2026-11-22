# SPDX-FileCopyrightText: The MSYS2 Authors
# SPDX-License-Identifier: MIT

import faulthandler


def post_worker_init(worker):
    # Uvicorn resets SIGABRT during worker initialization. Reinstall the handler
    # here so Gunicorn's timeout signal dumps the worker's stacks to stderr,
    # even if faulthandler was already enabled via PYTHONFAULTHANDLER.
    faulthandler.disable()
    faulthandler.enable()
