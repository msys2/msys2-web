# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import asyncio
import datetime
import hashlib
import os
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from .. import appconfig
from ..appconfig import REQUEST_TIMEOUT
from ..utils import logger


def get_mtime_for_response(response: httpx.Response) -> datetime.datetime | None:
    last_modified = response.headers.get("last-modified")
    if last_modified is not None:
        dt: datetime.datetime = parsedate_to_datetime(last_modified)
        return dt.astimezone(datetime.UTC)
    return None


async def get_content_cached_mtime(url: str, *args: Any, **kwargs: Any) -> tuple[bytes, datetime.datetime | None]:
    """Returns the content of the URL response, and a datetime object for when the content was last modified"""

    # cache the file locally, and store the "last-modified" date as the file mtime
    cache_dir = appconfig.CACHE_DIR
    if cache_dir is None:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url, *args, **kwargs)
            r.raise_for_status()
            return (r.content, get_mtime_for_response(r))

    os.makedirs(cache_dir, exist_ok=True)

    cache_fn = quote_plus(
        (urlparse(url).hostname or "") +
        "." + hashlib.sha256(url.encode()).hexdigest()[:16] +
        ".cache")

    fn = os.path.join(cache_dir, cache_fn)
    if not os.path.exists(fn):
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url, *args, **kwargs)
            r.raise_for_status()
            with open(fn, "wb") as h:
                h.write(r.content)
            mtime = get_mtime_for_response(r)
            if mtime is not None:
                os.utime(fn, (mtime.timestamp(), mtime.timestamp()))

    with open(fn, "rb") as h:
        data = h.read()
    file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fn), datetime.UTC)
    return (data, file_mtime)


async def get_content_cached(url: str, *args: Any, **kwargs: Any) -> bytes:
    return (await get_content_cached_mtime(url, *args, **kwargs))[0]


CacheHeaders = dict[str, str | None]


async def check_needs_update(urls: list[str], _cache: dict[str, CacheHeaders] = {}) -> bool:
    """Raises RequestException"""

    if appconfig.CACHE_DIR:
        return True

    async def get_cache_headers(client: httpx.AsyncClient, url: str, timeout: float) -> tuple[str, CacheHeaders]:
        """This tries to return the cache response headers for a given URL as cheap as possible"""

        old_headers = _cache.get(url, {})
        last_modified = old_headers.get("last-modified")
        etag = old_headers.get("etag")
        fetch_headers = {}
        if last_modified is not None:
            fetch_headers["if-modified-since"] = last_modified
        if etag is not None:
            fetch_headers["if-none-match"] = etag
        r = await client.head(url, timeout=timeout, headers=fetch_headers)
        if r.status_code == 304:
            return (url, dict(old_headers))
        r.raise_for_status()
        new_headers = {}
        new_headers["last-modified"] = r.headers.get("last-modified")
        new_headers["etag"] = r.headers.get("etag")
        return (url, new_headers)

    needs_update = False
    async with httpx.AsyncClient(follow_redirects=True) as client:
        awaitables = []
        for url in urls:
            awaitables.append(get_cache_headers(client, url, timeout=REQUEST_TIMEOUT))

        for url, new_cache_headers in (await asyncio.gather(*awaitables)):
            old_cache_headers = _cache.get(url, {})
            if old_cache_headers != new_cache_headers:
                needs_update = True
            _cache[url] = new_cache_headers

    logger.info(f"check needs update: {urls!r} -> {needs_update!r}")

    return needs_update
