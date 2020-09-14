from functools import cmp_to_key

from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.responses import JSONResponse

from typing import Tuple, Dict, List, Set, Any, Iterable
from .appstate import state, SrcInfoPackage
from .utils import version_is_newer_than, package_name_is_vcs

router = APIRouter()


def cmp_(a: Any, b: Any) -> int:
    return int((a > b) - (a < b))


def cmp_func(e1: Dict, e2: Dict) -> int:
    # package with fewest deps first
    e1_k = (len(e1["makedepends"]), sorted(e1["provides"]))
    e2_k = (len(e2["makedepends"]), sorted(e2["provides"]))
    e1_p, e1_m = e1["provides"], e1["makedepends"]
    e2_p, e2_m = e2["provides"], e2["makedepends"]

    e2e1 = e2_m & e1_p
    e1e2 = e1_m & e2_p

    if e1e2 and e2e1:
        # cyclic dependency!
        return cmp_(e1_k, e2_k)
    elif e2e1:
        return -1
    elif e1e2:
        return 1
    else:
        return cmp_(e1_k, e2_k)


@router.get('/buildqueue')
async def index(request: Request, response: Response, include_new: bool = True, include_update: bool = True, include_vcs: bool = False) -> Response:
    srcinfos = []

    # packages that should be updated
    if include_update:
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                if p.name in state.sourceinfos:
                    srcinfo = state.sourceinfos[p.name]
                    if package_name_is_vcs(s.name) and not include_vcs:
                        continue
                    if not version_is_newer_than(srcinfo.build_version, p.version):
                        continue
                    srcinfos.append(srcinfo)

    # packages that are new
    if include_new:
        available: Dict[str, List[SrcInfoPackage]] = {}
        for srcinfo in state.sourceinfos.values():
            if package_name_is_vcs(srcinfo.pkgbase) and not include_vcs:
                continue
            available.setdefault(srcinfo.pkgname, []).append(srcinfo)
        for s in state.sources.values():
            for p in s.packages.values():
                available.pop(p.name, None)
        for sis in available.values():
            srcinfos.extend(sis)

    def build_key(srcinfo: SrcInfoPackage) -> Tuple[str, str]:
        return (srcinfo.repo_url, srcinfo.repo_path)

    to_build: Dict[Tuple, List[SrcInfoPackage]] = {}
    for srcinfo in srcinfos:
        key = build_key(srcinfo)
        to_build.setdefault(key, []).append(srcinfo)

    db_makedepends: Dict[str, Set[str]] = {}
    db_depends: Dict[str, Set[str]] = {}
    for s in state.sources.values():
        for p in s.packages.values():
            db_makedepends.setdefault(p.name, set()).update(p.makedepends.keys())
            db_depends.setdefault(p.name, set()).update(p.depends.keys())

    def get_transitive_depends(packages: Iterable[str]) -> Set[str]:
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
            elif name in db_makedepends:
                todo.update(db_depends[name])
        return done

    def get_transitive_makedepends(packages: Iterable[str]) -> Set[str]:
        todo: Set[str] = set()
        for name in packages:
            # prefer depends from the GIT packages over the DB
            if name in state.sourceinfos:
                si = state.sourceinfos[name]
                todo.update(si.depends.keys())
                todo.update(si.makedepends.keys())
            elif name in db_makedepends:
                todo.update(db_depends[name])
                todo.update(db_makedepends[name])

        return get_transitive_depends(todo)

    entries = []
    all_provides = {}
    for srcinfos in to_build.values():
        packages = set()
        provides: Set[str] = set()
        for si in srcinfos:
            packages.add(si.pkgname)
            for prov in si.provides:
                provides.add(prov)
                all_provides[prov] = si.pkgname

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

    all_packages: Set[str] = set()
    for e in entries:
        # Replace dependencies on provided names with their providing packages
        makedepends = set(all_provides.get(d, d) for d in e["makedepends"])
        # Only show deps which are known at that point.. so in case of a cycle
        # this will be wrong, but we can't do much about that.
        e["depends"] = sorted(makedepends & all_packages)
        all_packages |= set(e["packages"])
        e["packages"] = sorted(e["packages"])
        del e["makedepends"]
        del e["provides"]

    return JSONResponse(entries)

api = FastAPI(title="MSYS2 Packages API", docs_url="/")
api.include_router(router)
