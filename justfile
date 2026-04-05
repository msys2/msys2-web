# Copyright 2016-2026 Christoph Reiter
# SPDX-License-Identifier: MIT

check:
    uv run ruff check
    uv run ruff format --check
    uv run ty check
    uv run reuse lint
    uv run pytest

fix:
    uv run ruff check --fix
    uv run ruff format

run:
    uv run run.py --cache
