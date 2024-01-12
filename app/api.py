from fastapi import FastAPI, APIRouter, Request, Response, Depends
from fastapi.responses import JSONResponse
from fastapi_etag import Etag
from pydantic import BaseModel

from collections.abc import Iterable
from .appstate import state, SrcInfoPackage
from .utils import extract_upstream_version, version_is_newer_than
from .fetch.update import queue_update


class QueueBuild(BaseModel):
    packages: list[str]
    depends: dict[str, list[str]]
    new: bool


class QueueEntry(BaseModel):
    name: str
    version: str
    version_repo: str | None
    repo_url: str
    repo_path: str
    source: bool
    builds: dict[str, QueueBuild]


async def get_etag(request: Request) -> str:
    return state.etag


router = APIRouter()


def get_srcinfos_to_build() -> tuple[list[SrcInfoPackage], set[str]]:
    srcinfos = []

    # packages that should be updated
    for s in state.sources.values():
        for k, p in sorted(s.packages.items()):
            if p.name in state.sourceinfos:
                srcinfo = state.sourceinfos[p.name]
                if not version_is_newer_than(srcinfo.build_version, p.version):
                    continue
                srcinfos.append(srcinfo)

    # packages that are new
    not_in_repo: dict[str, list[SrcInfoPackage]] = {}
    replaces_not_in_repo: set[str] = set()
    for srcinfo in state.sourceinfos.values():
        not_in_repo.setdefault(srcinfo.pkgname, []).append(srcinfo)
        replaces_not_in_repo.update(srcinfo.replaces)
    for s in state.sources.values():
        for p in s.packages.values():
            not_in_repo.pop(p.name, None)
            replaces_not_in_repo.discard(p.name)
    marked_new: set[str] = set()
    for sis in not_in_repo.values():
        srcinfos.extend(sis)
        # packages that are considered new, that don't exist in the repo, or
        # don't replace packages already in the repo. We mark them as "new" so
        # we can be more lax with them when they fail to build, since there is
        # no regression.
        for si in sis:
            all_replaces_new = all(p in replaces_not_in_repo for p in si.replaces)
            if all_replaces_new:
                marked_new.add(si.pkgname)

    return srcinfos, marked_new


@router.get('/buildqueue2', response_model=list[QueueEntry])
async def buildqueue2(request: Request, response: Response) -> list[QueueEntry]:
    srcinfos, marked_new = get_srcinfos_to_build()

    srcinfo_provides = {}
    srcinfo_replaces = {}
    for srcinfo in state.sourceinfos.values():
        for prov in srcinfo.provides.keys():
            srcinfo_provides[prov] = srcinfo.pkgname
        for repl in srcinfo.replaces:
            srcinfo_replaces[repl] = srcinfo.pkgname

    def resolve_package(pkgname: str) -> str:
        # if another package provides and replaces it, prefer that one
        if pkgname in srcinfo_replaces and pkgname in srcinfo_provides \
                and srcinfo_provides[pkgname] == srcinfo_replaces[pkgname]:
            return srcinfo_provides[pkgname]
        # otherwise prefer the real one
        if pkgname in state.sourceinfos:
            return pkgname
        # if there is no real one, try to find a provider
        return srcinfo_provides.get(pkgname, pkgname)

    def get_transitive_depends_and_resolve(packages: Iterable[str]) -> set[str]:
        todo = set(packages)
        done = set()
        while todo:
            name = resolve_package(todo.pop())
            if name in done:
                continue
            done.add(name)
            if name in state.sourceinfos:
                si = state.sourceinfos[name]
                todo.update(si.depends.keys())
        return done

    def get_transitive_makedepends(packages: Iterable[str]) -> set[str]:
        todo: set[str] = set()
        for name in packages:
            # don't resolve here, we want the real deps of the packages to build
            # even if it gets replaced
            si = state.sourceinfos[name]
            todo.update(si.depends.keys())
            todo.update(si.makedepends.keys())
        return get_transitive_depends_and_resolve(todo)

    def srcinfo_get_repo_version(si: SrcInfoPackage) -> str | None:
        if si.pkgbase in state.sources:
            return state.sources[si.pkgbase].version
        return None

    def srcinfo_has_src(si: SrcInfoPackage) -> bool:
        """If there already is a package with the same base/version in the repo
        we can assume that there exists a source package already
        """

        version = srcinfo_get_repo_version(si)
        return version is not None and version == si.build_version

    def srcinfo_is_new(si: SrcInfoPackage) -> bool:
        return si.pkgname in marked_new

    def build_key(srcinfo: SrcInfoPackage) -> tuple[str, str]:
        return (srcinfo.repo_url, srcinfo.repo_path)

    to_build: dict[tuple, list[SrcInfoPackage]] = {}
    for srcinfo in srcinfos:
        key = build_key(srcinfo)
        to_build.setdefault(key, []).append(srcinfo)

    entries = []
    repo_mapping = {}
    all_packages: set[str] = set()
    for srcinfos in to_build.values():
        packages = set()
        needs_src = False
        new_all: dict[str, list[bool]] = {}
        version_repo = None
        for si in srcinfos:
            if not srcinfo_has_src(si):
                needs_src = True
            version_repo = version_repo or srcinfo_get_repo_version(si)
            new_all.setdefault(si.repo, []).append(srcinfo_is_new(si))
            packages.add(si.pkgname)
            repo_mapping[si.pkgname] = si.repo
        # if all packages to build are new, we consider the build as new
        new = [k for k, v in new_all.items() if all(v)]

        all_packages.update(packages)
        entries.append({
            "repo_url": srcinfos[0].repo_url,
            "repo_path": srcinfos[0].repo_path,
            "version": srcinfos[0].build_version,
            "version_repo": version_repo,
            "name": srcinfos[0].pkgbase,
            "source": needs_src,
            "packages": packages,
            "new": new,
            "makedepends": get_transitive_makedepends(packages) | get_transitive_depends_and_resolve(['base-devel', 'base']),
        })

    # limit the deps to all packages in the queue overall, minus itself
    for e in entries:
        assert isinstance(e["makedepends"], set)
        assert isinstance(e["packages"], set)
        e["makedepends"] &= all_packages
        e["makedepends"] -= e["packages"]

    def group_by_repo(sequence: Iterable[str]) -> dict[str, list]:
        grouped: dict[str, list] = {}
        for name in sequence:
            grouped.setdefault(repo_mapping[name], []).append(name)
        for key, values in grouped.items():
            grouped[key] = sorted(set(values))
        return grouped

    results = []

    for e in entries:
        assert isinstance(e["makedepends"], set)
        assert isinstance(e["packages"], set)
        assert isinstance(e["new"], list)
        assert isinstance(e["name"], str)
        assert isinstance(e["version"], str)
        assert e["version_repo"] is None or isinstance(e["version_repo"], str)
        assert isinstance(e["repo_url"], str)
        assert isinstance(e["repo_path"], str)
        assert isinstance(e["source"], bool)

        makedepends = e["makedepends"]

        builds: dict[str, QueueBuild] = {}
        deps_grouped = group_by_repo(makedepends)

        for repo, build_packages in group_by_repo(e["packages"]).items():
            build_depends = {}
            for deprepo, depends in deps_grouped.items():
                if deprepo == repo or deprepo == "msys":
                    build_depends[deprepo] = depends

            builds[repo] = QueueBuild(
                packages=build_packages,
                depends=build_depends,
                new=(repo in e["new"])
            )

        results.append(QueueEntry(
            name=e["name"],
            version=e["version"],
            version_repo=e["version_repo"],
            repo_url=e["repo_url"],
            repo_path=e["repo_path"],
            source=e["source"],
            builds=builds,
        ))

    return results


@router.get('/removals')
async def removals(request: Request, response: Response) -> Response:
    # get all packages in the pacman repo which are no in GIT
    entries = []
    for s in state.sources.values():
        for k, p in s.packages.items():
            # FIXME: can also break things if it's the only provides and removed,
            # and also is ok to remove if there is a replacement
            if p.name not in state.sourceinfos and not p.rdepends:
                entries.append({
                    "repo": p.repo,
                    "name": p.name,
                })
    return JSONResponse(entries)


@router.get('/search')
async def search(request: Request, response: Response, query: str = "", qtype: str = "") -> Response:

    if qtype not in ["pkg", "binpkg"]:
        qtype = "pkg"

    parts = query.split()
    res_pkg: list[dict[str, str | list[str] | int]] = []
    exact = {}
    if not query:
        pass
    elif qtype == "pkg":
        for s in state.sources.values():
            if s.name.lower() == query or s.realname.lower() == query:
                exact = s.get_info()
                continue
            if [p for p in parts if p.lower() in s.name.lower()] == parts:
                res_pkg.append(s.get_info())
    elif qtype == "binpkg":
        for s in state.sources.values():
            for sub in s.packages.values():
                if sub.name.lower() == query or sub.realname.lower() == query:
                    exact = s.get_info()
                    continue
                if [p for p in parts if p.lower() in sub.name.lower()] == parts:
                    res_pkg.append(s.get_info())
    return JSONResponse(
        {
            'query': query,
            'qtype': qtype,
            'results': {
                'exact': exact,
                'other': res_pkg
            }
        }
    )


@router.post("/trigger_update", response_class=JSONResponse)
async def do_trigger_update(request: Request) -> Response:
    queue_update()
    return JSONResponse({})


class OutOfDateEntry(BaseModel):
    name: str
    repo_url: str
    repo_path: str
    version_git: str
    version_upstream: str


@router.get('/outofdate', response_model=list[OutOfDateEntry], dependencies=[Depends(Etag(get_etag))])
async def outofdate(request: Request, response: Response) -> list[OutOfDateEntry]:
    to_update = []

    for s in state.sources.values():
        if s.pkgextra.internal:
            continue

        git_version = extract_upstream_version(s.git_version)
        info = s.upstream_info
        if info is not None and info.version != "":
            if version_is_newer_than(info.version, git_version):
                to_update.append(OutOfDateEntry(
                    name=s.name,
                    repo_url=s.repo_url,
                    repo_path=s.repo_path,
                    version_git=git_version,
                    version_upstream=info.version))

    return to_update


api = FastAPI(title="MSYS2 Packages API", docs_url="/")
api.include_router(router)
