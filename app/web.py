# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import datetime
import hmac
import hashlib
from typing import Callable, Any, List, Union, Dict, Optional, Tuple

import httpx
import jinja2

from fastapi import APIRouter, Request, HTTPException, Depends, Response, FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi_etag import Etag
from fastapi.staticfiles import StaticFiles
from fastapi_etag import add_exception_handler as add_etag_exception_handler

from .appstate import state, get_repositories, Package, is_skipped, Source
from .utils import package_name_is_vcs, extract_upstream_version, version_is_newer_than
from .appconfig import REQUEST_TIMEOUT

router = APIRouter(default_response_class=HTMLResponse)
DIR = os.path.dirname(os.path.realpath(__file__))
templates = Jinja2Templates(directory=os.path.join(DIR, "templates"))


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


@context_function("package_restriction")
def package_restriction(request: Request, package: Package, name: str = None) -> str:
    name = name or package.name
    return name[len(re.split("[<>=]+", name)[0]):].strip()


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


@router.get('/', dependencies=[Depends(Etag(get_etag))])
async def index(request: Request, response: Response) -> Response:
    return RedirectResponse(request.url_for('updates'), headers=dict(response.headers))


@router.get('/base', dependencies=[Depends(Etag(get_etag))])
@router.get('/base/{base_name}', dependencies=[Depends(Etag(get_etag))])
async def base(request: Request, response: Response, base_name: str = None) -> Response:
    global state

    if base_name is not None:
        res = [s for s in state.sources if s.name == base_name]
        return templates.TemplateResponse("base.html", {
            "request": request,
            "sources": res,
        }, headers=dict(response.headers))
    else:
        return templates.TemplateResponse("baseindex.html", {
            "request": request,
            "sources": state.sources,
        }, headers=dict(response.headers))


@router.get('/group/', dependencies=[Depends(Etag(get_etag))])
@router.get('/group/{group_name}', dependencies=[Depends(Etag(get_etag))])
async def group(request: Request, response: Response, group_name: Optional[str] = None) -> Response:
    global state

    if group_name is not None:
        res = []
        for s in state.sources:
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
        for s in state.sources:
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
    for s in state.sources:
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
async def updates(request: Request, response: Response) -> Response:
    packages: List[Package] = []
    for s in state.sources:
        packages.extend(s.packages.values())
    packages.sort(key=lambda p: p.builddate, reverse=True)

    return templates.TemplateResponse("updates.html", {
        "request": request,
        "packages": packages[:150],
    }, headers=dict(response.headers))


@router.get('/outofdate', dependencies=[Depends(Etag(get_etag))])
async def outofdate(request: Request, response: Response) -> Response:
    missing = []
    skipped = []
    to_update = []
    all_sources = []
    for s in state.sources:
        if package_name_is_vcs(s.name):
            continue

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


@router.get('/queue', dependencies=[Depends(Etag(get_etag))])
async def queue(request: Request, response: Response) -> Response:
    # Create entries for all packages where the version doesn't match
    updates = []
    for s in state.sources:
        for k, p in sorted(s.packages.items()):
            if p.name in state.sourceinfos:
                srcinfo = state.sourceinfos[p.name]
                if package_name_is_vcs(s.name):
                    continue
                if version_is_newer_than(srcinfo.build_version, p.version):
                    updates.append((srcinfo, s, p))
                    break

    updates.sort(
        key=lambda i: (i[0].date, i[0].pkgbase, i[0].pkgname),
        reverse=True)

    return templates.TemplateResponse("queue.html", {
        "request": request,
        "updates": updates,
    }, headers=dict(response.headers))


@router.get('/new', dependencies=[Depends(Etag(get_etag))])
async def new(request: Request, response: Response) -> Response:
    # Create dummy entries for all GIT only packages
    available = {}
    for srcinfo in state.sourceinfos.values():
        if package_name_is_vcs(srcinfo.pkgbase):
            continue
        available[srcinfo.pkgbase] = srcinfo
    for s in state.sources:
        available.pop(s.name, None)
    new = list(available.values())

    new.sort(
        key=lambda i: (i.date, i.pkgbase, i.pkgname),
        reverse=True)

    return templates.TemplateResponse("new.html", {
        "request": request,
        "new": new,
    }, headers=dict(response.headers))


@router.get('/removals', dependencies=[Depends(Etag(get_etag))])
async def removals(request: Request, response: Response) -> Response:
    # get all packages in the pacman repo which are no in GIT
    missing = []
    for s in state.sources:
        for k, p in s.packages.items():
            if p.name not in state.sourceinfos:
                missing.append((s, p))
    missing.sort(key=lambda i: (i[1].builddate, i[1].name), reverse=True)

    return templates.TemplateResponse("removals.html", {
        "request": request,
        "missing": missing,
    }, headers=dict(response.headers))


@router.get('/python2', dependencies=[Depends(Etag(get_etag))])
async def python2(request: Request, response: Response) -> Response:

    def is_split_package(p: Package) -> bool:
        py2 = False
        py3 = False
        for name, type_ in (p.makedepends + p.depends):
            if name.startswith("mingw-w64-x86_64-python3") or name.startswith("python3"):
                py3 = True
            if name.startswith("mingw-w64-x86_64-python2") or name.startswith("python2"):
                py2 = True
            if py2 and py3:
                for s in state.sources:
                    if s.name == p.base:
                        return len(s.packages) >= 4
                return True
        return False

    def get_rdep_count(p: Package) -> int:
        todo = {p.name: p}
        done = set()
        while todo:
            name, p = todo.popitem()
            done.add(name)
            for rdep in [x[0] for x in p.rdepends]:
                if rdep.name not in done:
                    todo[rdep.name] = rdep
        return len(done) - 1

    deps: Dict[str, Tuple[Package, int, bool]] = {}
    for s in state.sources:
        for p in s.packages.values():
            if not (p.repo, p.repo_variant) in [("mingw64", ""), ("msys", "x86_64")]:
                continue
            if p.name in deps:
                continue
            if p.name in ["mingw-w64-x86_64-python2", "python2"]:
                for rdep, type_ in sorted(p.rdepends, key=lambda y: y[0].name):
                    if type_ != "" and is_split_package(rdep):
                        continue
                    deps[rdep.name] = (rdep, get_rdep_count(rdep), is_split_package(rdep))
            for path in p.files:
                if "/lib/python2.7/" in path:
                    deps[p.name] = (p, get_rdep_count(p), is_split_package(p))
                    break

    grouped: Dict[str, Tuple[int, bool]] = {}
    for p, count, split in deps.values():
        base = p.base
        if base in grouped:
            old_count, old_split = grouped[base]
            grouped[base] = (old_count + count, split or old_split)
        else:
            grouped[base] = (count, split)

    results = sorted(grouped.items(), key=lambda i: (i[1][0], i[0]))

    return templates.TemplateResponse("python2.html", {
        "request": request,
        "results": results,
    }, headers=dict(response.headers))


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
        for s in state.sources:
            if [p for p in parts if p.lower() in s.name.lower()] == parts:
                res_pkg.append(s)
        res_pkg.sort(key=lambda s: s.name)
    elif qtype == "binpkg":
        for s in state.sources:
            for sub in s.packages.values():
                if [p for p in parts if p.lower() in sub.name.lower()] == parts:
                    res_pkg.append(sub)
        res_pkg.sort(key=lambda p: p.name)

    return templates.TemplateResponse("search.html", {
        "request": request,
        "results": res_pkg,
        "query": query,
        "qtype": qtype,
    }, headers=dict(response.headers))


async def trigger_appveyor_build(account: str, project: str, token: str) -> str:
    """Returns an URL for the build or raises RequestException"""

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://ci.appveyor.com/api/builds",
            json={
                "accountName": account,
                "projectSlug": project,
                "branch": "master",
            },
            headers={
                "Authorization": "Bearer " + token,
            },
            timeout=REQUEST_TIMEOUT)
        r.raise_for_status()

        try:
            build_id = r.json()['buildId']
        except (ValueError, KeyError):
            build_id = 0

    return "https://ci.appveyor.com/project/%s/%s/builds/%d" % (
        account, project, build_id)


async def check_github_signature(request: Request, secret: str) -> bool:
    signature = request.headers.get('X-Hub-Signature', '')
    mac = hmac.new(secret.encode("utf-8"), await request.body(), hashlib.sha1)
    return hmac.compare_digest("sha1=" + mac.hexdigest(), signature)


@router.post("/webhook", response_class=JSONResponse)
async def github_payload(request: Request) -> Response:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(500, 'webhook secret config incomplete')

    if not await check_github_signature(request, secret):
        raise HTTPException(400, 'Invalid signature')

    event = request.headers.get('X-GitHub-Event', '')
    if event == 'ping':
        return JSONResponse({'msg': 'pong'})
    if event == 'push':
        account = os.environ.get("APPVEYOR_ACCOUNT")
        project = os.environ.get("APPVEYOR_PROJECT")
        token = os.environ.get("APPVEYOR_TOKEN")
        if not account or not project or not token:
            raise HTTPException(500, 'appveyor config incomplete')
        build_url = await trigger_appveyor_build(account, project, token)
        return JSONResponse({'msg': 'triggered a build: %s' % build_url})
    else:
        raise HTTPException(400, 'Unsupported event type: ' + event)


webapp = FastAPI(openapi_url=None)
webapp.mount("/static", StaticFiles(directory=os.path.join(DIR, "static")), name="static")
webapp.include_router(router)
add_etag_exception_handler(webapp)
