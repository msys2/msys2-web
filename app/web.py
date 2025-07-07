# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import datetime
from enum import Enum
import urllib.parse
from typing import Any, Optional, NamedTuple
from collections.abc import Callable

import jinja2
import markupsafe

from fastapi import APIRouter, Request, Depends, Response, FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi_etag import Etag
from fastapi.staticfiles import StaticFiles
from fastapi_etag import add_exception_handler as add_etag_exception_handler

from .appstate import state, get_repositories, Package, Source, DepType, SrcInfoPackage, get_base_group_name, Vulnerability, Severity, PackageKey, find_packages
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


class PackageBuildStatus(NamedTuple):
    build_type: str
    status_key: str
    details: str
    urls: dict[str, str]

    @property
    def status_text(self) -> str:
        return get_status_text(self.status_key)

    @property
    def category(self) -> str:
        return get_status_category(self.status_key)

    @property
    def priority(self) -> tuple[int, str]:
        return get_status_priority(self.status_key)


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
        def ctxfunc(context: dict, *args: Any, **kwargs: Any) -> Any:
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


@context_function("vulnerability_color")
def vulnerability_color(request: Request, vuln: Vulnerability) -> str:
    if vuln.severity == Severity.CRITICAL:
        return "danger"
    elif vuln.severity == Severity.HIGH:
        return "warning"
    else:
        return "secondary"


@context_function("package_url")
def package_url(request: Request, package: Package, name: str | None = None) -> str:
    res: str = ""
    if name is None:
        res = str(request.url_for("package", package_name=name or package.name))
        if package.repo_variant:
            res += "?variant=" + package.repo_variant
    else:
        res = str(request.url_for("package", package_name=re.split("[<>=]+", name)[0]))
        if package.repo_variant:
            res += "?variant=" + package.repo_variant
    return res


_spdx_scanner = re.Scanner([  # type: ignore
    (r"[A-Za-z0-9.+-]+", lambda scanner, token: ("LICENSE", token)),
    (r"[^A-Za-z0-9.+-]+", lambda scanner, token: ("TEXT", token)),
])


def _license_to_html(license: str) -> str:

    def create_url(license: str) -> str:
        fn = urllib.parse.quote(license)
        return f"https://spdx.org/licenses/{fn}.html"

    def spdx_to_html(s: str) -> str:
        done = []
        for t, token in _spdx_scanner.scan(s)[0]:
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


def _licenses_to_html(licenses: list[str]) -> str:
    done = []
    for license in licenses:
        needs_quote = (" " in license.strip()) and len(licenses) > 1
        html = _license_to_html(license)
        if needs_quote:
            done.append(f"({html})")
        else:
            done.append(html)

    return " OR ".join(done)


@context_function("licenses_to_html")
def licenses_to_html(request: Request, licenses: list[str]) -> str:
    return _licenses_to_html(licenses)


@template_filter("rdepends_type")
def rdepends_type(types: set[DepType]) -> list[str]:
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
def rdepends_sort(rdepends: dict[Package, set[str]]) -> list[tuple[Package, set[str]]]:
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


@template_filter("group_by_repo")
def group_by_repo(packages: dict[PackageKey, Package]) -> list[tuple[str, list[Package]]]:
    res: dict[str, list[Package]] = {}
    for _, p in sorted(packages.items()):
        res.setdefault(p.repo, []).append(p)
    sorted_res = []
    for repo in get_repositories():
        name = repo.name
        if name in res:
            sorted_res.append((name, res[name]))
    return sorted_res


@router.get('/robots.txt')
async def robots() -> Response:
    data = """\
User-agent: *
Disallow: /search?*
    """
    return Response(content=data, media_type='text/plain')


@router.get('/repos', dependencies=[Depends(Etag(get_etag))])
async def repos(request: Request, response: Response) -> Response:
    return templates.TemplateResponse(request, "repos.html", {"repos": get_repositories()}, headers=dict(response.headers))


@router.get('/stats', dependencies=[Depends(Etag(get_etag))])
async def stats(request: Request, response: Response) -> Response:
    return templates.TemplateResponse(request, "stats.html", {}, headers=dict(response.headers))


@router.get('/mirrors', dependencies=[Depends(Etag(get_etag))])
async def mirrors(request: Request, response: Response) -> Response:
    return templates.TemplateResponse(request, "mirrors.html", {}, headers=dict(response.headers))


@router.get('/', dependencies=[Depends(Etag(get_etag))])
async def index(request: Request, response: Response) -> Response:
    return RedirectResponse(request.url_for('queue'), headers=dict(response.headers))


@router.get('/base', dependencies=[Depends(Etag(get_etag))])
async def baseindex(request: Request, response: Response, repo: str | None = None) -> Response:
    repo_filter = repo or None
    repos = get_repositories()

    filtered: list[Source] = []
    if repo_filter is None:
        filtered = list(state.sources.values())
    else:
        for s in state.sources.values():
            for p in s.packages.values():
                if p.repo == repo_filter:
                    filtered.append(s)
                    break

    return templates.TemplateResponse(request, "baseindex.html", {
        "sources": filtered,
        "repos": repos,
        "repo_filter": repo_filter,
    }, headers=dict(response.headers))


@router.get('/base/{base_name}', dependencies=[Depends(Etag(get_etag))])
async def base(request: Request, response: Response, base_name: str) -> Response:
    if base_name in state.sources:
        res = [state.sources[base_name]]
    else:
        res = []
    return templates.TemplateResponse(request, "base.html", {
        "sources": res,
    }, status_code=200 if res else 404, headers=dict(response.headers))


@router.get('/security', dependencies=[Depends(Etag(get_etag))])
async def security(request: Request, response: Response) -> Response:
    def sort_key(s: Source) -> tuple:
        v: Vulnerability | None = s.worst_active_vulnerability
        assert v is not None
        return v.sort_key

    return templates.TemplateResponse(request, "security.html", {
        "vulnerable": sorted([s for s in state.sources.values() if s.worst_active_vulnerability is not None],
                             key=sort_key,
                             reverse=True),
        "sources": state.sources.values(),
        "known": [s for s in state.sources.values() if s.can_have_vulnerabilities],
        "unknown": [s for s in state.sources.values() if not s.can_have_vulnerabilities],
    }, headers=dict(response.headers))


@router.get('/group/', dependencies=[Depends(Etag(get_etag))])
@router.get('/group/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def group(request: Request, response: Response, group_name: str | None = None) -> Response:
    params = {}
    if group_name is not None:
        params['group_name'] = group_name
    return RedirectResponse(request.url_for('groups', **params), headers=dict(response.headers))


@router.get('/groups/', dependencies=[Depends(Etag(get_etag))])
@router.get('/groups/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def groups(request: Request, response: Response, group_name: str | None = None) -> Response:
    if group_name is not None:
        res = []
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                if group_name in p.groups:
                    res.append(p)

        return templates.TemplateResponse(request, "group.html", {
            "name": group_name,
            "packages": res,
        }, status_code=200 if res else 404, headers=dict(response.headers))
    else:
        groups: dict[str, int] = {}
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    groups[name] = groups.get(name, 0) + 1
        return templates.TemplateResponse(request, 'groups.html', {
            "groups": groups,
        }, headers=dict(response.headers))


@router.get('/basegroups/', dependencies=[Depends(Etag(get_etag))])
@router.get('/basegroups/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def basegroups(request: Request, response: Response, group_name: str | None = None) -> Response:
    if group_name is not None:
        groups: dict[str, int] = {}
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    base_name = get_base_group_name(p, name)
                    if base_name == group_name:
                        groups[name] = groups.get(name, 0) + 1

        return templates.TemplateResponse(request, "basegroup.html", {
            "name": group_name,
            "groups": groups,
        }, status_code=200 if groups else 404, headers=dict(response.headers))
    else:
        base_groups: dict[str, set[str]] = {}
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    base_name = get_base_group_name(p, name)
                    base_groups.setdefault(base_name, set()).add(name)

        return templates.TemplateResponse(request, 'basegroups.html', {
            "base_groups": base_groups,
        }, headers=dict(response.headers))


@router.get('/package/', dependencies=[Depends(Etag(get_etag))])
async def packages_redir(request: Request, response: Response) -> Response:
    return RedirectResponse(
        request.url_for('packages').include_query_params(**request.query_params),
        headers=dict(response.headers))


@router.get('/packages/', dependencies=[Depends(Etag(get_etag))])
async def packages(request: Request, response: Response, repo: str | None = None, variant: str | None = None) -> Response:
    repo = repo or get_repositories()[0].name

    packages = []
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if p.repo == repo:
                if not variant or p.repo_variant == variant:
                    packages.append((s, p))

    repos = get_repositories()
    return templates.TemplateResponse(request, "packages.html", {
        "packages": packages,
        "repos": repos,
        "repo_filter": repo,
    }, headers=dict(response.headers))


@router.get('/package/{package_name}', dependencies=[Depends(Etag(get_etag))])
async def package_redir(request: Request, response: Response, package_name: str) -> Response:
    return RedirectResponse(
        request.url_for('package', package_name=package_name).include_query_params(**request.query_params),
        headers=dict(response.headers))


@router.get('/packages/{package_name}', dependencies=[Depends(Etag(get_etag))])
async def package(request: Request, response: Response, package_name: str, repo: str | None = None, variant: str | None = None) -> Response:
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

    if not packages and provides:
        return templates.TemplateResponse(request, "packagevirtual.html", {
            "name": package_name,
            "packages": provides,
        }, headers=dict(response.headers))
    else:
        return templates.TemplateResponse(request, "package.html", {
            "packages": packages,
        }, status_code=200 if packages else 404, headers=dict(response.headers))


@router.get('/updates', dependencies=[Depends(Etag(get_etag))])
async def updates(request: Request, response: Response, repo: str = "") -> Response:

    repo_filter = repo or None
    repos = get_repositories()

    packages: list[Package] = []
    for s in state.sources.values():
        for p in s.packages.values():
            if repo_filter is not None and p.repo != repo_filter:
                continue
            packages.append(p)
    packages.sort(key=lambda p: p.builddate, reverse=True)

    return templates.TemplateResponse(request, "updates.html", {
        "packages": packages[:250],
        "repos": repos,
        "repo_filter": repo_filter,
    }, headers=dict(response.headers))


def get_transitive_depends(related: list[str]) -> set[str]:
    if not related:
        return set()

    db_depends: dict[str, set[str]] = {}
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
async def outofdate(request: Request, response: Response, related: str | None = None, repo: str = "") -> Response:

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
        if repo_filter is not None and repo_filter not in s.repos:
            continue

        all_sources.append(s)

        if "internal" in s.pkgextra.references:
            continue

        if related_depends:
            for p in s.packages.values():
                if p.name in related_depends:
                    break
            else:
                continue

        msys_version = extract_upstream_version(s.version)
        git_version = extract_upstream_version(s.git_version)
        if not version_is_newer_than(git_version, msys_version):
            git_version = ""

        info = s.upstream_info
        if info is not None and info.version is not None:
            if version_is_newer_than(info.version, msys_version):
                to_update.append((s, msys_version, git_version, info.version, info.url, info.date))
        else:
            missing.append(s)

    # show packages which have recently been build first.
    # assumes high frequency update packages are more important
    to_update.sort(key=lambda i: (i[-1], i[0].name), reverse=True)

    missing.sort(key=lambda i: i.date, reverse=True)

    return templates.TemplateResponse(request, "outofdate.html", {
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


def get_status_priority(key: str) -> tuple[int, str]:
    """We want to show the most important status as the primary one"""

    try:
        status = PackageStatus(key)
    except ValueError:
        return (-1, key)

    order = [
        PackageStatus.FINISHED,
        PackageStatus.FINISHED_BUT_INCOMPLETE,
        PackageStatus.FINISHED_BUT_BLOCKED,
        PackageStatus.WAITING_FOR_DEPENDENCIES,
        PackageStatus.WAITING_FOR_BUILD,
        PackageStatus.UNKNOWN,
        PackageStatus.MANUAL_BUILD_REQUIRED,
        PackageStatus.FAILED_TO_BUILD,
    ]

    try:
        return (order.index(status), key)
    except ValueError:
        return (-1, key)


def repo_to_build_type(repo: str) -> list[str]:
    if repo == "msys":
        return [repo, "msys-src"]
    else:
        return [repo, "mingw-src"]


def get_build_types() -> list[str]:
    build_types: list[str] = []
    for r in get_repositories():
        for build_type in repo_to_build_type(r.name):
            if build_type in build_types:
                build_types.remove(build_type)
            build_types.append(build_type)
    return build_types


def get_build_status(srcinfo: SrcInfoPackage, build_types: set[str] = set()) -> list[PackageBuildStatus]:
    build_status = state.build_status

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
                    build_type, status_key,
                    status.desc or "", status.urls)
            )

    if not results:
        for build in build_types:
            results.append(
                PackageBuildStatus(build, PackageStatus.UNKNOWN.value, "", {}))

    return results


@router.get('/queue', dependencies=[Depends(Etag(get_etag))])
async def queue(request: Request, response: Response, build_type: str = "") -> Response:
    # Create entries for all packages where the version doesn't match

    UpdateEntry = tuple[SrcInfoPackage, Optional[Source], Optional[Package], list[PackageBuildStatus]]

    build_filter = build_type or None
    srcinfo_repos: dict[str, set[str]] = {}

    grouped: dict[str, UpdateEntry] = {}
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if p.name in state.sourceinfos:
                srcinfo = state.sourceinfos[p.name]
                if build_filter is not None and build_filter not in repo_to_build_type(srcinfo.repo):
                    continue
                if version_is_newer_than(srcinfo.build_version, p.version):
                    srcinfo_repos.setdefault(srcinfo.pkgbase, set()).update(repo_to_build_type(srcinfo.repo))
                    repo_list = srcinfo_repos[srcinfo.pkgbase] if not build_filter else {build_filter}
                    new_src = state.sources.get(srcinfo.pkgbase)
                    grouped[srcinfo.pkgbase] = (srcinfo, new_src, p, get_build_status(srcinfo, repo_list))

    # new packages
    available: dict[str, list[SrcInfoPackage]] = {}
    for srcinfo in state.sourceinfos.values():
        if build_filter is not None and build_filter not in repo_to_build_type(srcinfo.repo):
            continue
        available.setdefault(srcinfo.pkgname, []).append(srcinfo)
    for s in state.sources.values():
        for p in s.packages.values():
            available.pop(p.name, None)

    # only one per pkgbase
    for srcinfos in available.values():
        for srcinfo in srcinfos:
            srcinfo_repos.setdefault(srcinfo.pkgbase, set()).update(repo_to_build_type(srcinfo.repo))
            repo_list = srcinfo_repos[srcinfo.pkgbase] if not build_filter else {build_filter}
            src, pkg = None, None
            if srcinfo.pkgbase in grouped:
                src, pkg = grouped[srcinfo.pkgbase][1:3]
            elif srcinfo.pkgbase in state.sources:
                src = state.sources[srcinfo.pkgbase]
            grouped[srcinfo.pkgbase] = (srcinfo, src, pkg, get_build_status(srcinfo, repo_list))

    updates: list[UpdateEntry] = []
    updates = list(grouped.values())
    updates.sort(
        key=lambda i: (i[3][0].priority, i[0].date, i[0].pkgbase, i[0].pkgname),
        reverse=True)

    # get all packages in the pacman repo which are no in GIT
    removals = []
    for s in state.sources.values():
        for k, p in s.packages.items():
            if build_filter is not None and build_filter not in repo_to_build_type(p.repo):
                continue
            if p.name not in state.sourceinfos:
                # FIXME: can also break things if it's the only provides and removed,
                # and also is ok to remove if there is a replacement
                removals.append((p, p.rdepends))

    return templates.TemplateResponse(request, "queue.html", {
        "updates": updates,
        "removals": removals,
        "build_types": get_build_types(),
        "build_filter": build_filter,
        "cycles": state.build_status.cycles,
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

    results = find_packages(query, qtype)

    return templates.TemplateResponse(request, "search.html", {
        "results": results,
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
