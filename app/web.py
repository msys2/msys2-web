# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import datetime
import hmac
import hashlib
from functools import wraps
from typing import Callable, Any, List, Union, Dict, Optional, Tuple

import httpx
from flask import render_template, request, url_for, redirect, \
    make_response, Blueprint, abort, jsonify, Request

from .appstate import state, get_repositories, Package, is_skipped, Source
from .utils import package_name_is_vcs, extract_upstream_version, version_is_newer_than
from .appconfig import REQUEST_TIMEOUT


packages = Blueprint('packages', __name__, template_folder='templates')


@packages.app_template_filter('timestamp')
def _jinja2_filter_timestamp(d: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(
            int(d)).strftime('%Y-%m-%d %H:%M:%S')
    except OSError:
        return "-"


@packages.app_template_filter('filesize')
def _jinja2_filter_filesize(d: int) -> str:
    d = int(d)
    if d > 1024 ** 3:
        return "%.2f GB" % (d / (1024 ** 3))
    else:
        return "%.2f MB" % (d / (1024 ** 2))


@packages.context_processor
def funcs() -> Dict[str, Callable]:

    def is_endpoint(value: str) -> bool:
        if value.startswith(".") and request.blueprint is not None:
            value = request.blueprint + value
        return value == request.endpoint

    def package_url(package: Package, name: str = None) -> str:
        res: str = ""
        if name is None:
            res = url_for(".package", name=name or package.name)
            res += "?repo=" + package.repo
            if package.repo_variant:
                res += "&variant=" + package.repo_variant
        else:
            res = url_for(".package", name=re.split("[<>=]+", name)[0])
            if package.repo_variant:
                res += "?repo=" + package.repo
                res += "&variant=" + package.repo_variant
        return res

    def package_name(package: Package, name: str = None) -> str:
        name = name or package.name
        name = re.split("[<>=]+", name, 1)[0]
        return (name or package.name)

    def package_restriction(package: Package, name: str = None) -> str:
        name = name or package.name
        return name[len(re.split("[<>=]+", name)[0]):].strip()

    def update_timestamp() -> float:
        global state

        return state.last_update

    return dict(package_url=package_url, package_name=package_name,
                package_restriction=package_restriction,
                update_timestamp=update_timestamp, is_endpoint=is_endpoint)


def cache_route(f: Callable) -> Callable:

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        global state

        response = make_response()
        response.set_etag(state.etag)
        response.make_conditional(request)
        if response.status_code == 304:
            return response

        result = f(*args, **kwargs)
        if isinstance(result, str):
            response.set_data(result)
            return response
        else:
            return result

    return wrapper


RouteResponse = Any


@packages.route('/repos')
@cache_route
def repos() -> RouteResponse:
    return render_template('repos.html', repos=get_repositories())


@packages.route('/')
def index() -> RouteResponse:
    return redirect(url_for('.updates'))


@packages.route('/base')
@packages.route('/base/<name>')
@cache_route
def base(name: str = None) -> RouteResponse:
    global state

    if name is not None:
        res = [s for s in state.sources if s.name == name]
        return render_template('base.html', sources=res)
    else:
        return render_template('baseindex.html', sources=state.sources)


@packages.route('/group/')
@packages.route('/group/<name>')
@cache_route
def group(name: Optional[str] = None) -> RouteResponse:
    global state

    if name is not None:
        res = []
        for s in state.sources:
            for k, p in sorted(s.packages.items()):
                if name in p.groups:
                    res.append(p)

        return render_template('group.html', name=name, packages=res)
    else:
        groups: Dict[str, int] = {}
        for s in state.sources:
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    groups[name] = groups.get(name, 0) + 1
        return render_template('groups.html', groups=groups)


@packages.route('/package/<name>')
@cache_route
def package(name: str) -> RouteResponse:
    global state

    repo = request.args.get('repo')
    variant = request.args.get('variant')

    packages = []
    for s in state.sources:
        for k, p in sorted(s.packages.items()):
            if p.name == name or name in p.provides:
                if not repo or p.repo == repo:
                    if not variant or p.repo_variant == variant:
                        packages.append((s, p))
    return render_template('package.html', packages=packages)


@packages.route('/updates')
@cache_route
def updates() -> RouteResponse:
    global state

    packages: List[Package] = []
    for s in state.sources:
        packages.extend(s.packages.values())
    packages.sort(key=lambda p: p.builddate, reverse=True)
    return render_template('updates.html', packages=packages[:150])


@packages.route('/outofdate')
@cache_route
def outofdate() -> RouteResponse:
    global state

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

    return render_template(
        'outofdate.html',
        all_sources=all_sources, to_update=to_update, missing=missing,
        skipped=skipped)


@packages.route('/queue')
@cache_route
def queue() -> RouteResponse:
    global state

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

    return render_template('queue.html', updates=updates)


@packages.route('/new')
@cache_route
def new() -> RouteResponse:
    global state

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

    return render_template('new.html', new=new)


@packages.route('/removals')
@cache_route
def removals() -> RouteResponse:
    global state

    # get all packages in the pacman repo which are no in GIT
    missing = []
    for s in state.sources:
        for k, p in s.packages.items():
            if p.name not in state.sourceinfos:
                missing.append((s, p))
    missing.sort(key=lambda i: (i[1].builddate, i[1].name), reverse=True)

    return render_template('removals.html', missing=missing)


@packages.route('/python2')
@cache_route
def python2() -> RouteResponse:

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

    return render_template(
        'python2.html', results=results)


@packages.route('/search')
@cache_route
def search() -> str:
    global state

    query = request.args.get('q', '')
    qtype = request.args.get('t', '')

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

    return render_template(
        'search.html', results=res_pkg, query=query, qtype=qtype)


def trigger_appveyor_build(account: str, project: str, token: str) -> str:
    """Returns an URL for the build or raises RequestException"""

    r = httpx.post(
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


def check_github_signature(request: Request, secret: str) -> bool:
    signature = request.headers.get('X-Hub-Signature', '')
    mac = hmac.new(secret.encode("utf-8"), request.get_data(), hashlib.sha1)
    return hmac.compare_digest("sha1=" + mac.hexdigest(), signature)


@packages.route("/webhook", methods=['POST'])
def github_payload() -> RouteResponse:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        abort(500, 'webhook secret config incomplete')

    if not check_github_signature(request, secret):
        abort(400, 'Invalid signature')

    event = request.headers.get('X-GitHub-Event', '')
    if event == 'ping':
        return jsonify({'msg': 'pong'})
    if event == 'push':
        account = os.environ.get("APPVEYOR_ACCOUNT")
        project = os.environ.get("APPVEYOR_PROJECT")
        token = os.environ.get("APPVEYOR_TOKEN")
        if not account or not project or not token:
            abort(500, 'appveyor config incomplete')
        build_url = trigger_appveyor_build(account, project, token)
        return jsonify({'msg': 'triggered a build: %s' % build_url})
    else:
        abort(400, 'Unsupported event type: ' + event)
