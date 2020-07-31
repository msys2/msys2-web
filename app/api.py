from functools import cmp_to_key

from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.responses import JSONResponse

from typing import Tuple, Dict, List, Set, Any, Iterable
from .appstate import state, SrcInfoPackage
from .utils import package_name_is_vcs, version_is_newer_than

router = APIRouter()


def cmp_(a: Any, b: Any) -> int:
    return int((a > b) - (a < b))


def cmp_func(e1: Dict, e2: Dict) -> int:
    # package with fewest deps first
    e1_k = (len(e1["makedepends"]), sorted(e1["provides"]))
    e2_k = (len(e2["makedepends"]), sorted(e2["provides"]))
    e1_p, e1_m = e1["provides"], e1["makedepends"]
    e2_p, e2_m = e2["provides"], e2["makedepends"]

    if e1_p & e2_m and e2_p & e1_m:
        # cyclic dependency!
        return cmp_(e1_k, e2_k)
    elif e1_p & e2_m:
        return -1
    elif e2_p & e1_m:
        return 1
    else:
        return cmp_(e1_k, e2_k)


@router.get('/buildqueue')
async def index(request: Request, response: Response, include_new: bool = True, include_update: bool = True) -> Response:
    srcinfos = []

    # packages that should be updated
    if include_update:
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                if p.name in state.sourceinfos:
                    srcinfo = state.sourceinfos[p.name]
                    if package_name_is_vcs(s.name):
                        continue
                    if not version_is_newer_than(srcinfo.build_version, p.version):
                        continue
                    srcinfos.append(srcinfo)

    # packages that are new
    if include_new:
        available: Dict[str, List[SrcInfoPackage]] = {}
        for srcinfo in state.sourceinfos.values():
            if package_name_is_vcs(srcinfo.pkgbase):
                continue
            available.setdefault(srcinfo.pkgbase, []).append(srcinfo)
        for s in state.sources.values():
            available.pop(s.name, None)
        for sis in available.values():
            srcinfos.extend(sis)

    def build_key(srcinfo: SrcInfoPackage) -> Tuple[str, str]:
        return (srcinfo.repo_url, srcinfo.repo_path)

    to_build: Dict[Tuple, List[SrcInfoPackage]] = {}
    for srcinfo in srcinfos:
        key = build_key(srcinfo)
        to_build.setdefault(key, []).append(srcinfo)

    db_makedepends: Dict[str, Set[str]] = {}
    for s in state.sources.values():
        for p in s.packages.values():
            md = list(p.depends.keys()) + list(p.makedepends.keys())
            db_makedepends.setdefault(p.name, set()).update(md)

    def get_transitive_makedepends(packages: Iterable[str]) -> Set[str]:
        todo = set(packages)
        done = set()
        while todo:
            name = todo.pop()
            if name in done:
                continue
            done.add(name)
            # prefer depends from the GIT packages over the DB
            if name in state.sourceinfos:
                si = state.sourceinfos[name]
                todo.update(si.depends.keys())
                todo.update(si.makedepends.keys())
            elif name in db_makedepends:
                todo.update(db_makedepends[name])
        return done

    entries = []
    for srcinfos in to_build.values():
        packages = set()
        provides: Set[str] = set()
        for si in srcinfos:
            packages.add(si.pkgname)

        entries.append({
            "repo_url": srcinfos[0].repo_url,
            "repo_path": srcinfos[0].repo_path,
            "version": srcinfos[0].build_version,
            "name": srcinfos[0].pkgbase,
            "packages": packages,
            "provides": provides | packages,
            "makedepends": get_transitive_makedepends(packages),
        })

    entries.sort(key=cmp_to_key(cmp_func))

    for e in entries:
        e["packages"] = sorted(e["packages"])
        del e["makedepends"]
        del e["provides"]

    return JSONResponse(entries)

api = FastAPI(title="MSYS2 Packages API", docs_url="/")
api.include_router(router)
