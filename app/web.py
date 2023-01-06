# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import datetime
from enum import Enum
import urllib.parse
from typing import Callable, Any, List, Union, Dict, Optional, Tuple, Set, NamedTuple

import jinja2
import markupsafe

from fastapi import APIRouter, Request, Depends, Response, FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi_etag import Etag
from fastapi.staticfiles import StaticFiles
from fastapi_etag import add_exception_handler as add_etag_exception_handler

from .appstate import state, get_repositories, Package, Source, DepType, SrcInfoPackage, get_base_group_name
from .appconfig import DEFAULT_REPO
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
        @jinja2.pass_context
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
def package_url(request: Request, package: Package, name: Optional[str] = None) -> str:
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


def _license_to_html(license: str) -> str:

    def create_url(license: str) -> str:
        fn = urllib.parse.quote(license)
        return f"https://spdx.org/licenses/{fn}.html"

    def spdx_to_html(s: str) -> str:
        scanner = re.Scanner([  # type: ignore
            (r"[A-Za-z0-9.+-]+", lambda scanner, token: ("LICENSE", token)),
            (r"[^A-Za-z0-9.+-]+", lambda scanner, token: ("TEXT", token)),
        ])

        done = []
        for t, token in scanner.scan(s)[0]:
            if t == "LICENSE":
                if token.upper() in ["AND", "OR", "WITH"]:
                    done.append(str(markupsafe.escape(token)))
                elif token.upper().startswith("LICENSEREF-"):
                    done.append(str(markupsafe.escape(token.split("-", 1)[-1])))
                else:
                    url = create_url(token)
                    done.append(f"<a href=\"{url}\">{markupsafe.escape(token)}</a>")
            else:
                done.append(str(markupsafe.escape(token)))

        return "".join(done)

    def needs_quote(s: str) -> bool:
        return " " in s

    if license.lower().startswith("spdx:"):
        return spdx_to_html(license.split(":", 1)[-1])
    return str(markupsafe.escape(license))


@context_function("licenses_to_html")
def licenses_to_html(request: Request, licenses: List[str]) -> str:
    done = []
    licenses = sorted(set(licenses))
    for license in licenses:
        needs_quote = (" " in license.strip()) and len(licenses) > 1
        html = _license_to_html(license)
        if needs_quote:
            done.append(f"({html})")
        else:
            done.append(html)

    return " OR ".join(done)


@context_function("package_name")
def package_name(request: Request, package: Package, name: Optional[str] = None) -> str:
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


@router.get('/mirrors', dependencies=[Depends(Etag(get_etag))])
async def mirrors(request: Request, response: Response) -> Response:
    return templates.TemplateResponse("mirrors.html", {"request": request}, headers=dict(response.headers))


@router.get('/', dependencies=[Depends(Etag(get_etag))])
async def index(request: Request, response: Response) -> Response:
    return RedirectResponse(request.url_for('queue'), headers=dict(response.headers))


@router.get('/base', dependencies=[Depends(Etag(get_etag))])
@router.get('/base/{base_name}', dependencies=[Depends(Etag(get_etag))])
async def base(request: Request, response: Response, base_name: Optional[str] = None) -> Response:
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
    params = {}
    if group_name is not None:
        params['group_name'] = group_name
    return RedirectResponse(request.url_for('groups', **params), headers=dict(response.headers))


@router.get('/groups/', dependencies=[Depends(Etag(get_etag))])
@router.get('/groups/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def groups(request: Request, response: Response, group_name: Optional[str] = None) -> Response:
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


@router.get('/basegroups/', dependencies=[Depends(Etag(get_etag))])
@router.get('/basegroups/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def basegroups(request: Request, response: Response, group_name: Optional[str] = None) -> Response:
    global state

    if group_name is not None:
        groups: Dict[str, int] = {}
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    base_name = get_base_group_name(p, name)
                    if base_name == group_name:
                        groups[name] = groups.get(name, 0) + 1

        return templates.TemplateResponse("basegroup.html", {
            "request": request,
            "name": group_name,
            "groups": groups,
        }, headers=dict(response.headers))
    else:
        base_groups: Dict[str, Set[str]] = {}
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    base_name = get_base_group_name(p, name)
                    base_groups.setdefault(base_name, set()).add(name)

        return templates.TemplateResponse('basegroups.html', {
            "request": request,
            "base_groups": base_groups,
        }, headers=dict(response.headers))


@router.get('/package/', dependencies=[Depends(Etag(get_etag))])
async def packages(request: Request, response: Response, repo: Optional[str] = None, variant: Optional[str] = None) -> Response:
    global state

    repo = repo or DEFAULT_REPO

    packages = []
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if p.repo == repo:
                if not variant or p.repo_variant == variant:
                    packages.append((s, p))

    repos = get_repositories()
    return templates.TemplateResponse("packages.html", {
        "request": request,
        "packages": packages,
        "repos": repos,
        "repo_filter": repo,
    }, headers=dict(response.headers))


@router.get('/package/{package_name}', dependencies=[Depends(Etag(get_etag))])
async def package(request: Request, response: Response, package_name: str, repo: Optional[str] = None, variant: Optional[str] = None) -> Response:
    global state

    packages = []
    provides = []
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            is_package_exact = (package_name is None or p.name == package_name)
            if is_package_exact or package_name in p.provides:
                if not repo or p.repo == repo:
                    if not variant or p.repo_variant == variant:
                        if is_package_exact:
                            packages.append((s, p))
                        else:
                            provides.append((s, p))

    if packages:
        return templates.TemplateResponse("package.html", {
            "request": request,
            "packages": packages,
        }, headers=dict(response.headers))
    else:
        return templates.TemplateResponse("packagevirtual.html", {
            "request": request,
            "name": package_name,
            "packages": provides,
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


def get_transitive_depends(related: List[str]) -> Set[str]:
    if not related:
        return set()

    db_depends: Dict[str, Set[str]] = {}
    related_pkgs = set()
    for s in state.sources.values():
        for p in s.packages.values():
            if s.name in related:
                related_pkgs.add(p.name)
            db_depends.setdefault(p.name, set()).update(p.depends.keys())

    todo = set(related_pkgs)
    done = set()
    while todo:
        name = todo.pop()
        if name in done:
            continue
        done.add(name)
        if name in db_depends:
            todo.update(db_depends[name])

    return done


@router.get('/outofdate', dependencies=[Depends(Etag(get_etag))])
async def outofdate(request: Request, response: Response, related: Optional[str] = None, repo: str = "") -> Response:

    repo_filter = repo or None
    repos = get_repositories()

    missing = []
    to_update = []
    all_sources = []

    if related is not None:
        related_list = list(filter(None, [s.strip() for s in related.split(",")]))
    else:
        related_list = []

    related_depends = get_transitive_depends(related_list)

    for s in state.sources.values():
        all_sources.append(s)

        if s.pkgmeta.internal:
            continue

        if related_depends:
            for p in s.packages.values():
                if p.name in related_depends:
                    break
            else:
                continue

        if repo_filter is not None and repo_filter not in s.repos:
            continue

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
            missing.append(s)

    # show packages which have recently been build first.
    # assumes high frequency update packages are more important
    to_update.sort(key=lambda i: (i[-1], i[0].name), reverse=True)

    missing.sort(key=lambda i: i.date, reverse=True)

    return templates.TemplateResponse("outofdate.html", {
        "request": request,
        "all_sources": all_sources,
        "to_update": to_update,
        "missing": missing,
        "related": related or "",
        "repos": repos,
        "repo_filter": repo_filter,
    }, headers=dict(response.headers))


def get_status_text(key: str) -> str:
    try:
        status = PackageStatus(key)
    except ValueError:
        return key
    if status == PackageStatus.UNKNOWN:
        return "Waiting to be processed"
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

    if status in (PackageStatus.FINISHED, PackageStatus.FINISHED_BUT_BLOCKED,
                  PackageStatus.FINISHED_BUT_INCOMPLETE):
        return SUCCESS
    elif status in (PackageStatus.WAITING_FOR_BUILD, PackageStatus.WAITING_FOR_DEPENDENCIES,
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


def repo_to_builds(repo: str) -> List[str]:
    if repo == "msys":
        return [repo, "msys-src"]
    else:
        return [repo, "mingw-src"]


def get_build_status(srcinfo: SrcInfoPackage, repo_list: Set[str] = set()) -> List[PackageBuildStatus]:
    build_status = state.build_status

    build_types = set()
    for repo in repo_list:
        build_types.update(repo_to_builds(repo))

    entry = None
    for package in build_status.packages:
        if package.name == srcinfo.pkgbase and package.version == srcinfo.build_version:
            entry = package
            break

    results = []
    if entry is not None:
        for build_type, status in sorted(entry.builds.items(), key=lambda i: get_status_priority(i[1].status), reverse=True):
            status_key = status.status
            if build_types and build_type not in build_types:
                continue
            results.append(
                PackageBuildStatus(
                    build_type, get_status_text(status_key),
                    status.desc or "", status.urls,
                    get_status_category(status_key))
            )

    if not results:
        build_types = set()
        for repo in repo_list:
            build_types.update(repo_to_builds(repo))
        for build in sorted(build_types):
            key = "unknown"
            results.append(
                PackageBuildStatus(build, get_status_text(key), "", {}, get_status_category(key)))

    return results


@router.get('/queue', dependencies=[Depends(Etag(get_etag))])
async def queue(request: Request, response: Response, repo: str = "") -> Response:
    # Create entries for all packages where the version doesn't match

    UpdateEntry = Tuple[SrcInfoPackage, Optional[Package], List[PackageBuildStatus]]

    repo_filter = repo or None
    repos = get_repositories()

    srcinfo_repos: Dict[str, Set[str]] = {}

    grouped: Dict[str, UpdateEntry] = {}
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if p.name in state.sourceinfos:
                srcinfo = state.sourceinfos[p.name]
                if repo_filter is not None and srcinfo.repo != repo_filter:
                    continue
                if version_is_newer_than(srcinfo.build_version, p.version):
                    srcinfo_repos.setdefault(srcinfo.pkgbase, set()).add(srcinfo.repo)
                    repo_list = srcinfo_repos[srcinfo.pkgbase] if not repo_filter else set([repo_filter])
                    grouped[srcinfo.pkgbase] = (srcinfo, p, get_build_status(srcinfo, repo_list))

    # new packages
    available: Dict[str, List[SrcInfoPackage]] = {}
    for srcinfo in state.sourceinfos.values():
        if repo_filter is not None and srcinfo.repo != repo_filter:
            continue
        available.setdefault(srcinfo.pkgname, []).append(srcinfo)
    for s in state.sources.values():
        for p in s.packages.values():
            available.pop(p.name, None)

    # only one per pkgbase
    for srcinfos in available.values():
        for srcinfo in srcinfos:
            srcinfo_repos.setdefault(srcinfo.pkgbase, set()).add(srcinfo.repo)
            repo_list = srcinfo_repos[srcinfo.pkgbase] if not repo_filter else set([repo_filter])
            pkg = None
            if srcinfo.pkgbase in grouped:
                pkg = grouped[srcinfo.pkgbase][1]
            grouped[srcinfo.pkgbase] = (srcinfo, pkg, get_build_status(srcinfo, repo_list))

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
                # FIXME: can also break things if it's the only provides and removed,
                # and also is ok to remove if there is a replacement
                removals.append((p, ", ".join([d.name for d in p.rdepends])))

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
    parts_lower = [p.lower() for p in parts]
    res_pkg: List[Tuple[float, Union[Package, Source]]] = []

    def get_score(name: str, parts: List[str]) -> float:
        score = 0.0
        for part in parts:
            if part not in name:
                return -1
            score += name.count(part) * len(part) / len(name)
        return score

    if not query:
        pass
    elif qtype == "pkg":
        for s in state.sources.values():
            score = get_score(s.realname.lower(), parts_lower)
            if score >= 0:
                res_pkg.append((score, s))
                continue
            score = get_score(s.name.lower(), parts_lower)
            if score >= 0:
                res_pkg.append((score, s))
        res_pkg.sort(key=lambda e: (-e[0], e[1].name.lower()))
    elif qtype == "binpkg":
        for s in state.sources.values():
            for sub in s.packages.values():
                score = get_score(sub.realname.lower(), parts_lower)
                if score >= 0:
                    res_pkg.append((score, sub))
                    continue
                score = get_score(sub.name.lower(), parts_lower)
                if score >= 0:
                    res_pkg.append((score, sub))
        res_pkg.sort(key=lambda e: (-e[0], e[1].name.lower()))

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
