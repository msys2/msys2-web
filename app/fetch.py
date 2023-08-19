# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os
import sys
import io
import json
import asyncio
import traceback
import hashlib
import functools
import gzip
import datetime
from asyncio import Event
from urllib.parse import urlparse, quote_plus
from typing import Any, Dict, Tuple, List, Set, Optional
from email.utils import parsedate_to_datetime

import httpx
from aiolimiter import AsyncLimiter
import zstandard

from .appstate import state, Source, get_repositories, SrcInfoPackage, Package, DepType, Repository, BuildStatus, \
    ExtInfo, ExtId
from .pkgmeta import PkgMeta, parse_yaml
from .appconfig import CYGWIN_METADATA_URL, REQUEST_TIMEOUT, AUR_METADATA_URL, ARCH_REPO_CONFIG, PKGMETA_URLS, \
    SRCINFO_URLS, UPDATE_INTERVAL, BUILD_STATUS_URLS, UPDATE_MIN_RATE, UPDATE_MIN_INTERVAL, PYPI_URLS
from .utils import version_is_newer_than, arch_version_to_msys, extract_upstream_version, logger
from . import appconfig
from .exttarfile import ExtTarFile


def get_mtime_for_response(response: httpx.Response) -> Optional[datetime.datetime]:
    last_modified = response.headers.get("last-modified")
    if last_modified is not None:
        dt: datetime.datetime = parsedate_to_datetime(last_modified)
        return dt.astimezone(datetime.timezone.utc)
    return None


async def get_content_cached_mtime(url: str, *args: Any, **kwargs: Any) -> Tuple[bytes, Optional[datetime.datetime]]:
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
    file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fn), datetime.timezone.utc)
    return (data, file_mtime)


async def get_content_cached(url: str, *args: Any, **kwargs: Any) -> bytes:
    return (await get_content_cached_mtime(url, *args, **kwargs))[0]


def parse_cygwin_versions(base_url: str, data: bytes) -> Tuple[Dict[str, ExtInfo], Dict[str, ExtInfo]]:
    # This is kinda hacky: extract the source name from the src tarball and take
    # last version line before it
    version = None
    source_package = None
    versions: Dict[str, ExtInfo] = {}
    versions_mingw64: Dict[str, ExtInfo] = {}
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
                    "https://cygwin.com/packages/summary/%s-src.html" % source_package,
                    {src_url: src_url_name})
            else:
                info_name = source_package
                if info_name in versions:
                    existing_version = versions[info_name][0]
                    if not version_is_newer_than(version, existing_version):
                        continue
                versions[info_name] = ExtInfo(
                    info_name, version, 0,
                    "https://cygwin.com/packages/summary/%s-src.html" % source_package,
                    {src_url: src_url_name})
    return versions, versions_mingw64


async def update_cygwin_versions() -> None:
    url = CYGWIN_METADATA_URL
    if not await check_needs_update([url]):
        return
    logger.info("update cygwin info")
    logger.info("Loading %r" % url)
    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
    data = zstandard.ZstdDecompressor().decompress(data)
    cygwin_versions, cygwin_versions_mingw64 = parse_cygwin_versions(url, data)
    state.set_ext_infos(ExtId("cygwin", "Cygwin", True), cygwin_versions)
    state.set_ext_infos(ExtId("cygwin-mingw64", "Cygwin-mingw64", False), cygwin_versions_mingw64)


async def update_build_status() -> None:
    urls = BUILD_STATUS_URLS
    if not await check_needs_update(urls):
        return

    logger.info("update build status")
    responses = []
    for url in urls:
        logger.info("Loading %r" % url)
        data, mtime = await get_content_cached_mtime(url, timeout=REQUEST_TIMEOUT)
        logger.info("Done: %r, %r" % (url, str(mtime)))
        responses.append((mtime, url, data))

    # use the newest of all status summaries
    newest = sorted(responses)[-1]
    logger.info("Selected: %r" % (newest[1],))
    state.build_status = BuildStatus.parse_raw(newest[2])


def parse_desc(t: str) -> Dict[str, List[str]]:
    d: Dict[str, List[str]] = {}
    cat = None
    values: List[str] = []
    for l in t.splitlines():
        l = l.strip()
        if cat is None:
            cat = l
        elif not l:
            d[cat] = values
            cat = None
            values = []
        else:
            values.append(l)
    if cat is not None:
        d[cat] = values
    return d


async def parse_repo(repo: Repository, include_files: bool = True) -> Dict[str, Source]:
    sources: Dict[str, Source] = {}

    def add_desc(d: Any) -> None:
        source = Source.from_desc(d, repo)
        if source.name not in sources:
            sources[source.name] = source
        else:
            source = sources[source.name]

        source.add_desc(d, repo)

    repo_url = repo.files_url if include_files else repo.db_url
    logger.info("Loading %r" % repo_url)
    data = await get_content_cached(repo_url, timeout=REQUEST_TIMEOUT)

    with io.BytesIO(data) as f:
        with ExtTarFile.open(fileobj=f, mode="r") as tar:
            packages: Dict[str, list] = {}
            for info in tar:
                package_name = info.name.split("/", 1)[0]
                infofile = tar.extractfile(info)
                if infofile is None:
                    continue
                with infofile:
                    packages.setdefault(package_name, []).append(
                        (info.name, infofile.read()))

    for package_name, infos in sorted(packages.items()):
        t = ""
        for name, data in sorted(infos):
            if name.endswith("/desc"):
                t += data.decode("utf-8")
            elif name.endswith("/depends"):
                t += data.decode("utf-8")
            elif name.endswith("/files"):
                t += data.decode("utf-8")
        desc = parse_desc(t)
        add_desc(desc)

    return sources


async def update_arch_versions() -> None:
    urls = [i[0] for i in ARCH_REPO_CONFIG]
    if not await check_needs_update(urls):
        return

    logger.info("update versions")
    arch_versions: Dict[str, ExtInfo] = {}
    awaitables = []
    for (url, repo) in ARCH_REPO_CONFIG:
        download_url = url.rsplit("/", 1)[0]
        awaitables.append(
            parse_repo(
                Repository(repo, "", "", "", download_url, download_url, ""),
                False
            )
        )

    # priority: real packages > real provides > aur packages > aur provides

    for sources in (await asyncio.gather(*awaitables)):
        for source in sources.values():
            version = extract_upstream_version(arch_version_to_msys(source.version))
            for p in source.packages.values():
                url = "https://archlinux.org/packages/%s/%s/%s/" % (
                    p.repo, p.arch, p.name)

                if p.name in arch_versions:
                    old_ver = arch_versions[p.name][0]
                    if version_is_newer_than(version, old_ver):
                        arch_versions[p.name] = ExtInfo(p.name, version, p.builddate, url, {})
                else:
                    arch_versions[p.name] = ExtInfo(p.name, version, p.builddate, url, {})

            url = "https://archlinux.org/packages/%s/%s/%s/" % (
                source.repos[0], source.arches[0], source.name)
            if source.name in arch_versions:
                old_ver = arch_versions[source.name][0]
                if version_is_newer_than(version, old_ver):
                    arch_versions[source.name] = ExtInfo(source.name, version, source.date, url, {})
            else:
                arch_versions[source.name] = ExtInfo(source.name, version, source.date, url, {})

            # use provides as fallback
            for p in source.packages.values():
                url = "https://archlinux.org/packages/%s/%s/%s/" % (
                    p.repo, p.arch, p.name)

                for provides in sorted(p.provides.keys()):
                    if provides not in arch_versions:
                        arch_versions[provides] = ExtInfo(provides, version, p.builddate, url, {})

    logger.info("done")
    state.set_ext_infos(ExtId("archlinux", "Arch Linux", False), arch_versions)

    logger.info("update versions from AUR")
    aur_versions: Dict[str, ExtInfo] = {}
    r = await get_content_cached(AUR_METADATA_URL,
                                 timeout=REQUEST_TIMEOUT)
    items = json.loads(r)
    for item in items:
        name = item["Name"]
        if name in aur_versions:
            continue
        version = item["Version"]
        msys_ver = extract_upstream_version(arch_version_to_msys(version))
        last_modified = item["LastModified"]
        url = "https://aur.archlinux.org/packages/%s" % name
        aur_versions[name] = ExtInfo(name, msys_ver, last_modified, url, {})

    for item in items:
        name = item["Name"]
        for provides in sorted(item.get("Provides", [])):
            if provides in aur_versions:
                continue
            version = item["Version"]
            msys_ver = extract_upstream_version(arch_version_to_msys(version))
            last_modified = item["LastModified"]
            url = "https://aur.archlinux.org/packages/%s" % name
            aur_versions[provides] = ExtInfo(provides, msys_ver, last_modified, url, {})

    logger.info("done")
    state.set_ext_infos(ExtId("aur", "AUR", True), aur_versions)


CacheHeaders = Dict[str, Optional[str]]


async def check_needs_update(urls: List[str], _cache: Dict[str, CacheHeaders] = {}) -> bool:
    """Raises RequestException"""

    if appconfig.CACHE_DIR:
        return True

    async def get_cache_headers(client: httpx.AsyncClient, url: str, timeout: float) -> Tuple[str, CacheHeaders]:
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

    logger.info("check needs update: %r -> %r" % (urls, needs_update))

    return needs_update


async def update_source() -> None:
    """Raises RequestException"""

    urls = [repo.files_url for repo in get_repositories()]
    if not await check_needs_update(urls):
        return

    logger.info("update source")

    final: Dict[str, Source] = {}
    awaitables = []
    for repo in get_repositories():
        awaitables.append(parse_repo(repo))
    for sources in await asyncio.gather(*awaitables):
        for name, source in sources.items():
            if name in final:
                final[name].packages.update(source.packages)
            else:
                final[name] = source

    fill_rdepends(final)
    fill_provided_by(final)
    state.sources = final


async def update_sourceinfos() -> None:
    urls = SRCINFO_URLS
    if not await check_needs_update(urls):
        return

    logger.info("update sourceinfos")
    result: Dict[str, SrcInfoPackage] = {}

    for url in urls:
        logger.info("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        json_obj = json.loads(gzip.decompress(data).decode("utf-8"))
        for hash_, m in json_obj.items():
            for repo, srcinfo in m["srcinfo"].items():
                for pkg in SrcInfoPackage.for_srcinfo(srcinfo, repo, m["repo"], m["path"], m["date"]):
                    if pkg.pkgname in result:
                        logger.info(f"WARN: duplicate: {pkg.pkgname} provided by "
                                    f"{pkg.pkgbase} and {result[pkg.pkgname].pkgbase}")
                    result[pkg.pkgname] = pkg

    state.sourceinfos = result


async def update_pkgmeta() -> None:
    urls = PKGMETA_URLS
    if not await check_needs_update(urls):
        return

    logger.info("update pkgmeta")
    merged = PkgMeta(packages={})
    for url in urls:
        logger.info("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        merged.packages.update(parse_yaml(data).packages)

    state.pkgmeta = merged
    await update_pypi_versions(merged)


async def update_pypi_versions(pkgmeta: PkgMeta) -> None:
    urls = PYPI_URLS
    if not await check_needs_update(urls):
        return

    projects = {}
    for url in urls:
        logger.info("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        json_obj = json.loads(gzip.decompress(data).decode("utf-8"))
        projects.update(json_obj.get("projects", {}))

    pypi_versions = {}
    for entry in pkgmeta.packages.values():
        if "pypi" not in entry.references:
            continue
        pypi_name = entry.references["pypi"]
        assert isinstance(pypi_name, str)
        if pypi_name in projects:
            project = projects[pypi_name]
            info = project["info"]
            project_urls = project.get("urls", [])
            oldest_timestamp = 0
            for url_entry in project_urls:
                dt = datetime.datetime.fromisoformat(
                    url_entry["upload_time_iso_8601"].replace("Z", "+00:00"))
                timestamp = int(dt.timestamp())
                if oldest_timestamp == 0 or timestamp < oldest_timestamp:
                    oldest_timestamp = timestamp
            pypi_versions[pypi_name] = ExtInfo(
                pypi_name, info["version"], oldest_timestamp, info["project_url"], {})

    state.set_ext_infos(ExtId("pypi", "PyPI", True), pypi_versions)


def fill_rdepends(sources: Dict[str, Source]) -> None:
    deps: Dict[str, Dict[Package, Set[DepType]]] = {}
    for s in sources.values():
        for p in s.packages.values():
            for n, r in p.depends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.NORMAL)
            for n, r in p.makedepends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.MAKE)
            for n, r in p.optdepends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.OPTIONAL)
            for n, r in p.checkdepends.items():
                deps.setdefault(n, dict()).setdefault(p, set()).add(DepType.CHECK)

    for s in sources.values():
        for p in s.packages.values():
            rdeps = [deps.get(p.name, dict())]
            for prov in p.provides:
                rdeps.append(deps.get(prov, dict()))

            merged: Dict[Package, Set[DepType]] = {}
            for rd in rdeps:
                for rp, rs in rd.items():
                    merged.setdefault(rp, set()).update(rs)

            p.rdepends = merged


def fill_provided_by(sources: Dict[str, Source]) -> None:

    provided_by: Dict[str, Set[Package]] = {}
    for s in sources.values():
        for p in s.packages.values():
            for provides in p.provides.keys():
                provided_by.setdefault(provides, set()).add(p)
    for s in sources.values():
        for p in s.packages.values():
            if p.name in provided_by:
                p.provided_by = provided_by[p.name]


_rate_limit = AsyncLimiter(UPDATE_MIN_RATE, UPDATE_MIN_INTERVAL)


@functools.lru_cache(maxsize=None)
def _get_update_event() -> Event:
    return Event()


async def wait_for_update() -> None:
    update_event = _get_update_event()
    await update_event.wait()
    update_event.clear()


def queue_update() -> None:
    update_event = _get_update_event()
    update_event.set()


async def trigger_loop() -> None:
    while True:
        logger.info("Sleeping for %d" % UPDATE_INTERVAL)
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
                awaitables = [
                    update_pkgmeta(),
                    update_cygwin_versions(),
                    update_arch_versions(),
                    update_source(),
                    update_sourceinfos(),
                    update_build_status(),
                ]
                await asyncio.gather(*awaitables)
                state.ready = True
                logger.info("done")
            except Exception:
                traceback.print_exc(file=sys.stdout)
        logger.info("Waiting for next update")
        await wait_for_update()
        # XXX: it seems some updates don't propagate right away, so wait a bit
        await asyncio.sleep(5)
