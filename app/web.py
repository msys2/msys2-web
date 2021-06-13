# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import datetime
from enum import Enum
from typing import Callable, Any, List, Union, Dict, Optional, Tuple, Set, NamedTuple

import jinja2

from fastapi import APIRouter, Request, Depends, Response, FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi_etag import Etag
from fastapi.staticfiles import StaticFiles
from fastapi_etag import add_exception_handler as add_etag_exception_handler

from .appstate import state, get_repositories, Package, is_skipped, Source, DepType, SrcInfoPackage
from .utils import extract_upstream_version, version_is_newer_than

router = APIRouter(default_response_class=HTMLResponse)
DIR = os.path.dirname(os.path.realpath(__file__))
templates = Jinja2Templates(directory=os.path.join(DIR, "templates"))
templates.env.undefined = jinja2.StrictUndefined


class PackageStatus(Enum):
    FINISHED = 'finished'
    FINISHED_BUT_BLOCKED = 'finished-but-blocked'
    FINISHED_BUT_INCOMPLETE = 'finished-but-incomplete'
    FAILED_TO_BUILD = 'failed-to-build'
    WAITING_FOR_BUILD = 'waiting-for-build'
    WAITING_FOR_DEPENDENCIES = 'waiting-for-dependencies'
    MANUAL_BUILD_REQUIRED = 'manual-build-required'
    UNKNOWN = 'unknown'


PackageBuildStatus = NamedTuple('PackageBuildStatus', [
    ('type', str),
    ('status', str),
    ('details', str),
    ('urls', Dict[str, str]),
    ('category', str),
])


async def get_etag(request: Request) -> str:
    return state.etag


def template_filter(name: str) -> Callable:
    def wrap(f: Callable) -> Callable:
        templates.env.filters[name] = f
        return f
    return wrap


def context_function(name: str) -> Callable:
    def wrap(f: Callable) -> Callable:
        @jinja2.contextfunction
        def ctxfunc(context: Dict, *args: Any, **kwargs: Any) -> Any:
            return f(context["request"], *args, **kwargs)
        templates.env.globals[name] = ctxfunc
        return f
    return wrap


@context_function("is_endpoint")
def is_endpoint(request: Request, endpoint: str) -> bool:
    path: str = request.scope["path"]
    return path == "/" + endpoint or path.startswith("/" + endpoint + "/")


@context_function("update_timestamp")
def update_timestamp(request: Request) -> float:
    return state.last_update


@context_function("package_url")
def package_url(request: Request, package: Package, name: str = None) -> str:
    res: str = ""
    if name is None:
        res = request.url_for("package", package_name=name or package.name)
        res += "?repo=" + package.repo
        if package.repo_variant:
            res += "&variant=" + package.repo_variant
    else:
        res = request.url_for("package", package_name=re.split("[<>=]+", name)[0])
        if package.repo_variant:
            res += "?repo=" + package.repo
            res += "&variant=" + package.repo_variant
    return res


@context_function("package_name")
def package_name(request: Request, package: Package, name: str = None) -> str:
    name = name or package.name
    name = re.split("[<>=]+", name, 1)[0]
    return (name or package.name)


@template_filter("rdepends_type")
def rdepends_type(types: Set[DepType]) -> List[str]:
    if list(types) == [DepType.NORMAL]:
        return []
    names = []
    for t in types:
        if t == DepType.NORMAL:
            names.append("normal")
        elif t == DepType.CHECK:
            names.append("check")
        elif t == DepType.OPTIONAL:
            names.append("optional")
        elif t == DepType.MAKE:
            names.append("make")
    return names


@template_filter("rdepends_sort")
def rdepends_sort(rdepends: Dict[Package, Set[str]]) -> List[Tuple[Package, Set[str]]]:
    return sorted(rdepends.items(), key=lambda x: (x[0].name.lower(), x[0].key))


@template_filter('timestamp')
def filter_timestamp(d: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(
            int(d)).strftime('%Y-%m-%d %H:%M:%S')
    except OSError:
        return "-"


@template_filter('filesize')
def filter_filesize(d: int) -> str:
    d = int(d)
    if d > 1024 ** 3:
        return "%.2f GB" % (d / (1024 ** 3))
    else:
        return "%.2f MB" % (d / (1024 ** 2))


@router.get('/repos', dependencies=[Depends(Etag(get_etag))])
async def repos(request: Request, response: Response) -> Response:
    return templates.TemplateResponse("repos.html", {"request": request, "repos": get_repositories()}, headers=dict(response.headers))


@router.get('/stats', dependencies=[Depends(Etag(get_etag))])
async def stats(request: Request, response: Response) -> Response:
    return templates.TemplateResponse("stats.html", {"request": request}, headers=dict(response.headers))


@router.get('/', dependencies=[Depends(Etag(get_etag))])
async def index(request: Request, response: Response) -> Response:
    return RedirectResponse(request.url_for('queue'), headers=dict(response.headers))


@router.get('/base', dependencies=[Depends(Etag(get_etag))])
@router.get('/base/{base_name}', dependencies=[Depends(Etag(get_etag))])
async def base(request: Request, response: Response, base_name: str = None) -> Response:
    global state

    if base_name is not None:
        if base_name in state.sources:
            res = [state.sources[base_name]]
        else:
            res = []
        return templates.TemplateResponse("base.html", {
            "request": request,
            "sources": res,
        }, headers=dict(response.headers))
    else:
        return templates.TemplateResponse("baseindex.html", {
            "request": request,
            "sources": state.sources.values(),
        }, headers=dict(response.headers))


@router.get('/group/', dependencies=[Depends(Etag(get_etag))])
@router.get('/group/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def group(request: Request, response: Response, group_name: Optional[str] = None) -> Response:
    global state

    if group_name is not None:
        res = []
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                if group_name in p.groups:
                    res.append(p)

        return templates.TemplateResponse("group.html", {
            "request": request,
            "name": group_name,
            "packages": res,
        }, headers=dict(response.headers))
    else:
        groups: Dict[str, int] = {}
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    groups[name] = groups.get(name, 0) + 1
        return templates.TemplateResponse('groups.html', {
            "request": request,
            "groups": groups,
        }, headers=dict(response.headers))


@router.get('/package/', dependencies=[Depends(Etag(get_etag))])
@router.get('/package/{package_name}', dependencies=[Depends(Etag(get_etag))])
async def package(request: Request, response: Response, package_name: Optional[str] = None, repo: Optional[str] = None, variant: Optional[str] = None) -> Response:
    global state

    packages = []
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if package_name is None or p.name == package_name or package_name in p.provides:
                if not repo or p.repo == repo:
                    if not variant or p.repo_variant == variant:
                        packages.append((s, p))

    if package_name is not None:
        return templates.TemplateResponse("package.html", {
            "request": request,
            "packages": packages,
        }, headers=dict(response.headers))
    else:
        return templates.TemplateResponse("packages.html", {
            "request": request,
            "packages": packages,
        }, headers=dict(response.headers))


@router.get('/updates', dependencies=[Depends(Etag(get_etag))])
async def updates(request: Request, response: Response, repo: str = "") -> Response:

    repo_filter = repo or None
    repos = get_repositories()

    packages: List[Package] = []
    for s in state.sources.values():
        for p in s.packages.values():
            if repo_filter is not None and p.repo != repo_filter:
                continue
            packages.append(p)
    packages.sort(key=lambda p: p.builddate, reverse=True)

    return templates.TemplateResponse("updates.html", {
        "request": request,
        "packages": packages[:250],
        "repos": repos,
        "repo_filter": repo_filter,
    }, headers=dict(response.headers))


@router.get('/outofdate', dependencies=[Depends(Etag(get_etag))])
async def outofdate(request: Request, response: Response) -> Response:
    missing = []
    skipped = []
    to_update = []
    all_sources = []
    for s in state.sources.values():
        all_sources.append(s)

        msys_version = extract_upstream_version(s.version)
        git_version = extract_upstream_version(s.git_version)
        if not version_is_newer_than(git_version, msys_version):
            git_version = ""

        external_infos = s.external_infos

        for info in external_infos:
            if version_is_newer_than(info.version, msys_version):
                to_update.append((s, msys_version, git_version, info.version, info.url, info.date))
                break

        if not external_infos:
            if is_skipped(s.name):
                skipped.append(s)
            else:
                missing.append((s, s.realname))

    # show packages which have recently been build first.
    # assumes high frequency update packages are more important
    to_update.sort(key=lambda i: (i[-1], i[0].name), reverse=True)

    missing.sort(key=lambda i: i[0].date, reverse=True)
    skipped.sort(key=lambda i: i.name)

    return templates.TemplateResponse("outofdate.html", {
        "request": request,
        "all_sources": all_sources,
        "to_update": to_update,
        "missing": missing,
        "skipped": skipped,
    }, headers=dict(response.headers))


def get_status_text(key: str) -> str:
    try:
        status = PackageStatus(key)
    except ValueError:
        return key
    if status == PackageStatus.UNKNOWN:
        return "Waiting for being processed"
    elif status == PackageStatus.FAILED_TO_BUILD:
        return "Failed to build"
    elif status == PackageStatus.FINISHED:
        return "Ready for upload"
    elif status == PackageStatus.FINISHED_BUT_BLOCKED:
        return "Ready for upload but waiting for dependencies"
    elif status == PackageStatus.FINISHED_BUT_INCOMPLETE:
        return "Ready for upload but related builds are missing"
    elif status == PackageStatus.MANUAL_BUILD_REQUIRED:
        return "Manual build required"
    elif status == PackageStatus.WAITING_FOR_BUILD:
        return "Waiting to be built"
    elif status == PackageStatus.WAITING_FOR_DEPENDENCIES:
        return "Waiting for dependencies"
    else:
        return key


def get_status_category(key: str) -> str:
    SUCCESS = "success"
    DANGER = "danger"

    try:
        status = PackageStatus(key)
    except ValueError:
        return DANGER

    if status == PackageStatus.FINISHED:
        return SUCCESS
    elif status in (PackageStatus.FINISHED_BUT_BLOCKED, PackageStatus.FINISHED_BUT_INCOMPLETE,
                    PackageStatus.WAITING_FOR_BUILD, PackageStatus.WAITING_FOR_DEPENDENCIES,
                    PackageStatus.UNKNOWN):
        return ""
    else:
        return DANGER


def get_status_priority(key: str) -> Tuple[int, str]:
    """We want to show the most important status as the primary one"""

    try:
        status = PackageStatus(key)
    except ValueError:
        return (-1, key)

    order = [
        PackageStatus.UNKNOWN,
        PackageStatus.FINISHED,
        PackageStatus.MANUAL_BUILD_REQUIRED,
        PackageStatus.FINISHED_BUT_INCOMPLETE,
        PackageStatus.FINISHED_BUT_BLOCKED,
        PackageStatus.WAITING_FOR_BUILD,
        PackageStatus.WAITING_FOR_DEPENDENCIES,
        PackageStatus.FAILED_TO_BUILD,
    ]

    try:
        return (order.index(status), key)
    except ValueError:
        return (-1, key)


def get_build_status(srcinfo: SrcInfoPackage, repo_filter: Optional[str] = None) -> List[PackageBuildStatus]:
    build_status = state.build_status

    all_status = build_status.get(srcinfo.pkgbase, {})
    results = []
    for build_type, status in sorted(all_status.items(), key=lambda i: get_status_priority(i[1]["status"]), reverse=True):
        status_key = status.get("status", "unknown")
        if status.get("version") != srcinfo.build_version:
            continue
        if repo_filter is not None and build_type != repo_filter:
            continue
        results.append(
            PackageBuildStatus(
                build_type, get_status_text(status_key),
                status.get("desc", ""), status.get("urls", {}),
                get_status_category(status_key))
        )

    if not results:
        key = "unknown"
        results.append(
            PackageBuildStatus(key, get_status_text(key), "", {}, get_status_category(key)))

    return results


@router.get('/queue', dependencies=[Depends(Etag(get_etag))])
async def queue(request: Request, response: Response, repo: str = "") -> Response:
    # Create entries for all packages where the version doesn't match

    UpdateEntry = Tuple[SrcInfoPackage, Optional[Source], Optional[Package], List[PackageBuildStatus]]

    repo_filter = repo or None
    repos = get_repositories()

    updates_grouped: Dict[str, UpdateEntry] = {}
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if p.name in state.sourceinfos:
                srcinfo = state.sourceinfos[p.name]
                if repo_filter is not None and srcinfo.repo != repo_filter:
                    continue
                if version_is_newer_than(srcinfo.build_version, p.version):
                    updates_grouped[srcinfo.pkgbase] = (srcinfo, s, p, get_build_status(srcinfo, repo_filter))
                    break

    # new packages
    available = {}
    for srcinfo in state.sourceinfos.values():
        if repo_filter is not None and srcinfo.repo != repo_filter:
            continue
        available[srcinfo.pkgname] = srcinfo
    for s in state.sources.values():
        for p in s.packages.values():
            available.pop(p.name, None)

    # only one per pkgbase
    grouped: Dict[str, UpdateEntry] = {}
    for srcinfo in available.values():
        grouped[srcinfo.pkgbase] = (srcinfo, None, None, get_build_status(srcinfo, repo_filter))
    grouped.update(updates_grouped)

    updates: List[UpdateEntry] = []
    updates = list(grouped.values())
    updates.sort(
        key=lambda i: (i[0].date, i[0].pkgbase, i[0].pkgname),
        reverse=True)

    # get all packages in the pacman repo which are no in GIT
    removals = []
    for s in state.sources.values():
        for k, p in s.packages.items():
            if repo_filter is not None and p.repo != repo_filter:
                continue
            if p.name not in state.sourceinfos:
                removals.append((s, p))
    removals.sort(key=lambda i: (i[1].builddate, i[1].name), reverse=True)

    return templates.TemplateResponse("queue.html", {
        "request": request,
        "updates": updates,
        "removals": removals,
        "repos": repos,
        "repo_filter": repo_filter,
    }, headers=dict(response.headers))


@router.get('/new', dependencies=[Depends(Etag(get_etag))])
@router.get('/removals', dependencies=[Depends(Etag(get_etag))])
async def new(request: Request, response: Response) -> Response:
    return RedirectResponse(request.url_for('queue'), headers=dict(response.headers))


@router.get('/search', dependencies=[Depends(Etag(get_etag))])
async def search(request: Request, response: Response, q: str = "", t: str = "") -> Response:
    query = q
    qtype = t

    if qtype not in ["pkg", "binpkg"]:
        qtype = "pkg"

    parts = query.split()
    res_pkg: List[Union[Package, Source]] = []

    if not query:
        pass
    elif qtype == "pkg":
        for s in state.sources.values():
            if [p for p in parts if p.lower() in s.name.lower()] == parts:
                res_pkg.append(s)
        res_pkg.sort(key=lambda s: s.name.lower())
    elif qtype == "binpkg":
        for s in state.sources.values():
            for sub in s.packages.values():
                if [p for p in parts if p.lower() in sub.name.lower()] == parts:
                    res_pkg.append(sub)
        res_pkg.sort(key=lambda p: p.name.lower())

    return templates.TemplateResponse("search.html", {
        "request": request,
        "results": res_pkg,
        "query": query,
        "qtype": qtype,
    }, headers=dict(response.headers))


async def check_is_ready(request: Request, call_next: Callable) -> Response:
    if not state.ready:
        return Response(content="starting up...", status_code=503)
    response: Response = await call_next(request)
    return response


webapp = FastAPI(openapi_url=None)
webapp.mount("/static", StaticFiles(directory=os.path.join(DIR, "static")), name="static")
webapp.include_router(router)
add_etag_exception_handler(webapp)
