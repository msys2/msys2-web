# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os
import sys
import argparse

import uvicorn
from app import app
from app import appconfig
from app import logger


def main(argv: list[str]) -> int | str | None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--cache", action="store_true",
                        help="use local repo cache")
    parser.add_argument("-p", "--port", type=int, default=8160,
                        help="port number")
    args = parser.parse_args()

    if args.cache:
        base = os.path.dirname(os.path.realpath(__file__))
        cache_dir = os.path.join(base, ".app.cache")
        logger.info(f"Using cache: {repr(cache_dir)}")
        appconfig.CACHE_DIR = cache_dir

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=None)

    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv))
