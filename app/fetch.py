# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os
import sys
import io
import tarfile
import json
import asyncio
import traceback
import hashlib
from urllib.parse import urlparse, quote_plus
from itertools import zip_longest
from typing import Any, Dict, Tuple, List, Set, Iterable

import httpx

from .appstate import state, Source, CygwinVersions, ArchMapping, get_repositories, get_arch_names, SrcInfoPackage, Package, DepType
from .appconfig import CYGWIN_VERSION_CONFIG, REQUEST_TIMEOUT, VERSION_CONFIG, ARCH_MAPPING_CONFIG, SRCINFO_CONFIG, UPDATE_INTERVAL, BUILD_STATUS_CONFIG
from .utils import version_is_newer_than, arch_version_to_msys
from . import appconfig


def get_update_urls() -> List[str]:
    urls = []
    for config in VERSION_CONFIG + SRCINFO_CONFIG + ARCH_MAPPING_CONFIG + CYGWIN_VERSION_CONFIG + BUILD_STATUS_CONFIG:
        urls.append(config[0])
    for repo in get_repositories():
        urls.append(repo.files_url)
    return sorted(urls)


async def get_content_cached(url: str, *args: Any, **kwargs: Any) -> bytes:
    cache_dir = appconfig.CACHE_DIR
    if cache_dir is None:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, *args, **kwargs)
            return r.content

    os.makedirs(cache_dir, exist_ok=True)

    cache_fn = quote_plus(
        (urlparse(url).hostname or "") +
        "." + hashlib.sha256(url.encode()).hexdigest()[:16] +
        ".cache")

    fn = os.path.join(cache_dir, cache_fn)
    if not os.path.exists(fn):
        async with httpx.AsyncClient() as client:
            r = await client.get(url, *args, **kwargs)
            with open(fn, "wb") as h:
                h.write(r.content)
    with open(fn, "rb") as h:
        data = h.read()
    return data


def parse_cygwin_versions(base_url: str, data: bytes) -> CygwinVersions:
    # This is kinda hacky: extract the source name from the src tarball and take
    # last version line before it
    version = None
    source_package = None
    versions: CygwinVersions = {}
    base_url = base_url.rsplit("/", 2)[0]
    for line in data.decode("utf-8").splitlines():
        if line.startswith("version:"):
            version = line.split(":", 1)[-1].strip().split("-", 1)[0].split("+", 1)[0]
        elif line.startswith("source:"):
            source = line.split(":", 1)[-1].strip()
            fn = source.rsplit(None, 2)[0]
            source_package = fn.rsplit("/")[-1].rsplit("-", 3)[0]
            src_url = base_url + "/" + fn
            assert version is not None
            if source_package not in versions:
                versions[source_package] = (version, "https://cygwin.com/packages/summary/%s-src.html" % source_package, src_url)
    return versions


async def update_cygwin_versions() -> None:
    print("update cygwin info")
    url = CYGWIN_VERSION_CONFIG[0][0]
    print("Loading %r" % url)
    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
    cygwin_versions = parse_cygwin_versions(url, data)
    state.cygwin_versions = cygwin_versions


async def update_build_status() -> None:
    print("update build status")
    url = BUILD_STATUS_CONFIG[0][0]
    print("Loading %r" % url)
    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
    state.build_status = json.loads(data)


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


async def parse_repo(repo: str, repo_variant: str, url: str) -> Dict[str, Source]:
    base_url = url.rsplit("/", 1)[0]
    sources: Dict[str, Source] = {}
    print("Loading %r" % url)

    def add_desc(d: Any, base_url: str) -> None:
        source = Source.from_desc(d, repo)
        if source.name not in sources:
            sources[source.name] = source
        else:
            source = sources[source.name]

        source.add_desc(d, base_url, repo, repo_variant)

    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)

    with io.BytesIO(data) as f:
        with tarfile.open(fileobj=f, mode="r:gz") as tar:
            packages: Dict[str, list] = {}
            for info in tar.getmembers():
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
        add_desc(desc, base_url)

    return sources


async def update_arch_versions() -> None:
    print("update versions")
    arch_versions: Dict[str, Tuple[str, str, int]] = {}
    awaitables = []
    for (url, repo, variant) in VERSION_CONFIG:
        awaitables.append(parse_repo(repo, variant, url))

    for sources in (await asyncio.gather(*awaitables)):
        for source in sources.values():
            msys_ver = arch_version_to_msys(source.version)
            for p in source.packages.values():
                url = "https://www.archlinux.org/packages/%s/%s/%s/" % (
                    p.repo, p.arch, p.name)

                if p.name in arch_versions:
                    old_ver = arch_versions[p.name][0]
                    if version_is_newer_than(msys_ver, old_ver):
                        arch_versions[p.name] = (msys_ver, url, p.builddate)
                else:
                    arch_versions[p.name] = (msys_ver, url, p.builddate)

            url = "https://www.archlinux.org/packages/%s/%s/%s/" % (
                source.repos[0], source.arches[0], source.name)
            if source.name in arch_versions:
                old_ver = arch_versions[source.name][0]
                if version_is_newer_than(msys_ver, old_ver):
                    arch_versions[source.name] = (msys_ver, url, source.date)
            else:
                arch_versions[source.name] = (msys_ver, url, source.date)

    print("done")

    print("update versions from AUR")
    # a bit hacky, try to get the remaining versions from AUR
    possible_names = set()
    for s in state.sources.values():
        for p in s.packages.values():
            possible_names.update(get_arch_names(p.realname))
        possible_names.update(get_arch_names(s.realname))

    r = await get_content_cached("https://aur.archlinux.org/packages.gz",
                                 timeout=REQUEST_TIMEOUT)
    aur_packages = set()
    for name in r.decode().splitlines():
        if name.startswith("#"):
            continue
        if name in arch_versions:
            continue
        if name not in possible_names:
            continue
        aur_packages.add(name)

    def chunks(iterable: Iterable[str], n: int) -> List[List[str]]:
        return [list(filter(None, x)) for x in zip_longest(*([iter(iterable)] * n))]

    # too long URLs lead to errors, so split things up
    for chunk in chunks(sorted(aur_packages), 250):
        aur_url = (
            "https://aur.archlinux.org/rpc/?v=5&type=info&" +
            "&".join(["arg[]=%s" % n for n in chunk]))
        data = await get_content_cached(aur_url, timeout=REQUEST_TIMEOUT)
        json_obj = json.loads(data.decode("utf-8"))
        for result in json_obj["results"]:
            name = result["Name"]
            if name not in chunk or name in arch_versions:
                continue
            last_modified = result["LastModified"]
            url = "https://aur.archlinux.org/packages/%s" % name
            arch_versions[name] = (result["Version"], url, last_modified)

    print("done")
    state.arch_versions = arch_versions


async def check_needs_update(_cache_key: List[str] = [""]) -> bool:
    """Raises RequestException"""

    if appconfig.CACHE_DIR:
        return True

    async def get_headers(client: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Headers:
        r = await client.head(*args, **kwargs)
        r.raise_for_status()
        return r.headers

    combined = ""
    async with httpx.AsyncClient() as client:
        awaitables = []
        for url in get_update_urls():
            awaitables.append(get_headers(client, url, timeout=REQUEST_TIMEOUT))

        for headers in (await asyncio.gather(*awaitables)):
            key = headers.get("last-modified", "")
            key += headers.get("etag", "")
            combined += key

    if combined != _cache_key[0]:
        _cache_key[0] = combined
        return True
    else:
        return False


async def update_source() -> None:
    """Raises RequestException"""

    print("update source")

    final: Dict[str, Source] = {}
    awaitables = []
    for repo in get_repositories():
        awaitables.append(parse_repo(repo.name, repo.variant, repo.files_url))
    for sources in await asyncio.gather(*awaitables):
        for name, source in sources.items():
            if name in final:
                final[name].packages.update(source.packages)
            else:
                final[name] = source

    fill_rdepends(final)
    state.sources = final


async def update_sourceinfos() -> None:
    print("update sourceinfos")

    result: Dict[str, SrcInfoPackage] = {}

    for cfg in SRCINFO_CONFIG:
        url = cfg[0]
        print("Loading %r" % url)
        data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
        json_obj = json.loads(data.decode("utf-8"))
        for hash_, m in json_obj.items():
            for repo, srcinfo in m["srcinfo"].items():
                for pkg in SrcInfoPackage.for_srcinfo(srcinfo, repo, m["repo"], m["path"], m["date"]):
                    if pkg.pkgname in result:
                        print(f"WARN: duplicate: {pkg.pkgname} provided by "
                              f"{pkg.pkgbase} and {result[pkg.pkgname].pkgbase}")
                    result[pkg.pkgname] = pkg

    state.sourceinfos = result


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


async def update_arch_mapping() -> None:
    print("update arch mapping")

    url = ARCH_MAPPING_CONFIG[0][0]
    print("Loading %r" % url)

    data = await get_content_cached(url, timeout=REQUEST_TIMEOUT)
    state.arch_mapping = ArchMapping(json.loads(data))


async def update_loop() -> None:
    while True:
        try:
            print("check for update")
            if await check_needs_update():
                print("update needed")
                rounds = []
                rounds.append([
                    update_arch_mapping(),
                    update_cygwin_versions(),
                    update_source(),
                    update_sourceinfos(),
                    update_build_status(),
                ])
                # update_arch_versions() depends on update_source()
                rounds.append([
                    update_arch_versions()
                ])
                for r in rounds:
                    await asyncio.gather(*r)
                state.ready = True
            else:
                print("no update needed")
        except Exception:
            traceback.print_exc(file=sys.stdout)
        print("Sleeping for %d" % UPDATE_INTERVAL)
        await asyncio.sleep(UPDATE_INTERVAL)
