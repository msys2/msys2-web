# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
import base64
import uuid
import time
from datetime import datetime, timezone
from enum import Enum
from functools import cmp_to_key
from urllib.parse import quote_plus, quote
from typing import NamedTuple, Any
from collections.abc import Sequence
from pydantic import BaseModel

from .appconfig import REPOSITORIES
from .utils import vercmp, version_is_newer_than, extract_upstream_version, split_depends, \
    split_optdepends, strip_vcs
from .pgp import parse_signature
from .pkgextra import PkgExtra, PkgExtraEntry


PackageKey = tuple[str, str, str, str, str]


class ExtId(NamedTuple):
    id: str
    name: str
    fallback: bool


class ExtInfo(NamedTuple):
    name: str
    version: str
    date: int
    url: str
    other_urls: dict[str, str]


class PackagerInfo(NamedTuple):
    name: str
    email: str | None


def parse_packager(text: str, _re: Any = re.compile("(.*?)<(.*?)>")) -> PackagerInfo:
    match = _re.fullmatch(text)
    if match is None:
        return PackagerInfo(text.strip(), None)
    else:
        name, email = match.groups()
        return PackagerInfo(name.strip(), email.strip())


class DepType(Enum):
    NORMAL = 0
    MAKE = 1
    OPTIONAL = 2
    CHECK = 3


def get_repositories() -> list[Repository]:
    l = []
    for data in REPOSITORIES:
        l.append(Repository(*data))
    return l


def get_realname_variants(s: Source) -> list[str]:
    """Returns a list of potential names used by external systems, highest priority first"""

    main = [s.realname, s.realname.lower()]

    package_variants = [p.realname for p in s.packages.values()]

    # fallback to the provide names
    provides_variants: list[str] = []
    for p in s.packages.values():
        provides_variants.extend(p.realprovides.keys())

    return main + sorted(package_variants) + sorted(provides_variants)


def cleanup_files(files: list[str]) -> list[str]:
    """Remove redundant directory paths and root them"""

    last = None
    result = []
    for path in sorted(files, reverse=True):
        if last is not None:
            if path.endswith("/") and last.startswith(path):
                continue
        result.append("/" + path)
        last = path
    return result[::-1]


def get_base_group_name(p: Package, group_name: str) -> str:
    """Given a package and a group it is part of, return the base group name the groups is part of"""

    if group_name.startswith(p.package_prefix):
        return p.base_prefix + group_name[len(p.package_prefix):]
    return group_name


class Repository:

    def __init__(self, name: str, variant: str, package_prefix: str, base_prefix: str, url: str, download_url: str, src_url: str):
        self.name = name
        self.variant = variant
        self.package_prefix = package_prefix
        self.base_prefix = base_prefix
        self.url = url
        self.download_url = download_url
        self.src_url = src_url

    @property
    def db_url(self) -> str:
        return self.url.rstrip("/") + "/" + self.name + ".db"

    @property
    def files_url(self) -> str:
        return self.url.rstrip("/") + "/" + self.name + ".files"

    @property
    def packages(self) -> list[Package]:
        global state

        repo_packages = []
        for s in state.sources.values():
            for k, p in sorted(s.packages.items()):
                if p.repo == self.name and p.repo_variant == self.variant:
                    repo_packages.append(p)
        return repo_packages

    @property
    def csize(self) -> int:
        return sum(int(p.csize) for p in self.packages)

    @property
    def isize(self) -> int:
        return sum(int(p.isize) for p in self.packages)


class BuildStatusBuild(BaseModel):
    desc: str | None
    status: str
    urls: dict[str, str]


class BuildStatusPackage(BaseModel):
    name: str
    version: str
    builds: dict[str, BuildStatusBuild]


class BuildStatus(BaseModel):
    packages: list[BuildStatusPackage] = []
    cycles: list[tuple[str, str]] = []


class AppState:

    def __init__(self) -> None:
        self._update_etag()

        self._etag = ""
        self.ready = False
        self._last_update = 0.0
        self._sources: dict[str, Source] = {}
        self._sourceinfos: dict[str, SrcInfoPackage] = {}
        self._pkgextra: PkgExtra = PkgExtra(packages={})
        self._ext_infos: dict[ExtId, dict[str, ExtInfo]] = {}
        self._build_status: BuildStatus = BuildStatus()
        self._update_etag()

    def _update_etag(self) -> None:
        self._etag = str(uuid.uuid4())
        self._last_update = time.time()

    @property
    def last_update(self) -> float:
        return self._last_update

    @property
    def etag(self) -> str:
        return self._etag

    @property
    def sources(self) -> dict[str, Source]:
        return self._sources

    @sources.setter
    def sources(self, sources: dict[str, Source]) -> None:
        self._sources = sources
        self._update_etag()

    @property
    def sourceinfos(self) -> dict[str, SrcInfoPackage]:
        return self._sourceinfos

    @sourceinfos.setter
    def sourceinfos(self, sourceinfos: dict[str, SrcInfoPackage]) -> None:
        self._sourceinfos = sourceinfos
        self._update_etag()

    @property
    def pkgextra(self) -> PkgExtra:
        return self._pkgextra

    @pkgextra.setter
    def pkgextra(self, pkgextra: PkgExtra) -> None:
        self._pkgextra = pkgextra
        self._update_etag()

    @property
    def ext_info_ids(self) -> list[ExtId]:
        return list(self._ext_infos.keys())

    def get_ext_infos(self, id: ExtId) -> dict[str, ExtInfo]:
        return self._ext_infos.get(id, {})

    def set_ext_infos(self, id: ExtId, info: dict[str, ExtInfo]) -> None:
        self._ext_infos[id] = info
        self._update_etag()

    @property
    def build_status(self) -> BuildStatus:
        return self._build_status

    @build_status.setter
    def build_status(self, build_status: BuildStatus) -> None:
        self._build_status = build_status
        self._update_etag()


class Package:

    def __init__(self, builddate: str, csize: str, depends: list[str], filename: str, files: list[str], isize: str,
                 makedepends: list[str], md5sum: str, name: str, pgpsig: str | None, sha256sum: str, arch: str,
                 base_url: str, repo: str, repo_variant: str, package_prefix: str, base_prefix: str,
                 provides: list[str], conflicts: list[str], replaces: list[str],
                 version: str, base: str, desc: str, groups: list[str], licenses: list[str], optdepends: list[str],
                 checkdepends: list[str], url: str, packager: str) -> None:
        self.builddate = int(builddate)
        self.csize = csize
        self.url = url
        self.signature = parse_signature(base64.b64decode(pgpsig)) if pgpsig is not None else None
        self.depends = split_depends(depends)
        self.checkdepends = split_depends(checkdepends)
        self.filename = filename
        self._files = "\n".join(cleanup_files(files))
        self.isize = isize
        self.makedepends = split_depends(makedepends)
        self.md5sum = md5sum
        self.name = name
        self.sha256sum = sha256sum
        self.arch = arch
        self.fileurl = base_url + "/" + quote(self.filename)
        self.repo = repo
        self.repo_variant = repo_variant
        self.package_prefix = package_prefix
        self.base_prefix = base_prefix
        self.provides = split_depends(provides)
        self.conflicts = split_depends(conflicts)
        self.replaces = split_depends(replaces)
        self.version = version
        self.base = base
        self.desc = desc
        self.groups = groups
        self.licenses = licenses
        self.rdepends: dict[Package, set[DepType]] = {}
        self.optdepends = split_optdepends(optdepends)
        self.packager = parse_packager(packager)
        self.provided_by: set[Package] = set()

    @property
    def files(self) -> Sequence[str]:
        return self._files.splitlines()

    def __repr__(self) -> str:
        return "Package(%s)" % self.fileurl

    @property
    def pkgextra(self) -> PkgExtraEntry:
        global state

        return state.pkgextra.packages.get(self.base, PkgExtraEntry())

    @property
    def urls(self) -> list[tuple[str, str]]:
        """Returns a list of (name, url) tuples for the various URLs of the package"""

        extra = self.pkgextra
        urls = []
        # homepage from the PKGBUILD, everything else from the extra metadata
        urls.append(("Homepage", self.url))
        if extra.changelog_url is not None:
            urls.append(("Changelog", extra.changelog_url))
        if extra.repository_url is not None:
            urls.append(("Repository", extra.repository_url))
        if extra.issue_tracker_url is not None:
            urls.append(("Issue tracker", extra.issue_tracker_url))
        if extra.documentation_url is not None:
            urls.append(("Documentation", extra.documentation_url))
        if extra.pgp_keys_url is not None:
            urls.append(("PGP keys", extra.pgp_keys_url))
        return urls

    @property
    def realprovides(self) -> dict[str, set[str]]:
        prov = {}
        for key, infos in self.provides.items():
            if key.startswith(self.package_prefix):
                key = key[len(self.package_prefix):]
            prov[key] = infos
        return prov

    @property
    def realname(self) -> str:
        if self.name.startswith(self.package_prefix):
            return strip_vcs(self.name[len(self.package_prefix):])
        return strip_vcs(self.name)

    @property
    def git_version(self) -> str:
        if self.name in state.sourceinfos:
            return state.sourceinfos[self.name].build_version
        return ""

    @property
    def repo_url(self) -> str:
        if self.name in state.sourceinfos:
            return state.sourceinfos[self.name].repo_url
        for repo in get_repositories():
            if repo.name == self.repo:
                return repo.src_url
        return ""

    @property
    def repo_path(self) -> str:
        if self.name in state.sourceinfos:
            return state.sourceinfos[self.name].repo_path
        return self.base

    @property
    def history_url(self) -> str:
        return self.repo_url + ("/commits/master/" + quote(self.repo_path))

    @property
    def source_url(self) -> str:
        return self.repo_url + ("/tree/master/" + quote(self.repo_path))

    @property
    def key(self) -> PackageKey:
        return (self.repo, self.repo_variant,
                self.name, self.arch, self.fileurl)

    @classmethod
    def from_desc(cls: type[Package], d: dict[str, list[str]], base: str, repo: Repository) -> Package:
        return cls(d["%BUILDDATE%"][0], d["%CSIZE%"][0],
                   d.get("%DEPENDS%", []), d["%FILENAME%"][0],
                   d.get("%FILES%", []), d["%ISIZE%"][0],
                   d.get("%MAKEDEPENDS%", []),
                   d["%MD5SUM%"][0], d["%NAME%"][0],
                   d.get("%PGPSIG%", [None])[0], d["%SHA256SUM%"][0],
                   d["%ARCH%"][0], repo.download_url, repo.name, repo.variant,
                   repo.package_prefix, repo.base_prefix,
                   d.get("%PROVIDES%", []), d.get("%CONFLICTS%", []),
                   d.get("%REPLACES%", []), d["%VERSION%"][0], base,
                   d.get("%DESC%", [""])[0], d.get("%GROUPS%", []),
                   d.get("%LICENSE%", []), d.get("%OPTDEPENDS%", []),
                   d.get("%CHECKDEPENDS%", []),
                   d.get("%URL%", [""])[0], d.get("%PACKAGER%", [""])[0])


class Source:

    def __init__(self, name: str):
        self.name = name
        self.packages: dict[PackageKey, Package] = {}

    @property
    def desc(self) -> str:
        pkg = self._package
        desc = None
        # the pacman DB has no information on the "base" package,
        # so we need to use the sourceinfo for that
        if pkg.name in state.sourceinfos:
            desc = state.sourceinfos[pkg.name].pkgbasedesc
        if desc is None:
            desc = pkg.desc
        return desc

    @property
    def _package(self) -> Package:
        return sorted(self.packages.items())[0][1]

    @property
    def repos(self) -> list[str]:
        return sorted({p.repo for p in self.packages.values()})

    @property
    def url(self) -> str:
        return self._package.url

    @property
    def arches(self) -> list[str]:
        return sorted({p.arch for p in self.packages.values()})

    @property
    def groups(self) -> list[str]:
        groups: set[str] = set()
        for p in self.packages.values():
            groups.update(p.groups)
        return sorted(groups)

    @property
    def basegroups(self) -> list[str]:
        groups: set[str] = set()
        for p in self.packages.values():
            groups.update(get_base_group_name(p, g) for g in p.groups)
        return sorted(groups)

    @property
    def version(self) -> str:
        # get the newest version
        versions: set[str] = {p.version for p in self.packages.values()}
        return sorted(versions, key=cmp_to_key(vercmp), reverse=True)[0]

    @property
    def git_version(self) -> str:
        # get the newest version
        versions: set[str] = {p.git_version for p in self.packages.values()}
        return sorted(versions, key=cmp_to_key(vercmp), reverse=True)[0]

    @property
    def licenses(self) -> list[list[str]]:
        licenses: list[list[str]] = []
        for p in self.packages.values():
            if p.licenses and p.licenses not in licenses:
                licenses.append(p.licenses)
        return sorted(licenses)

    @property
    def upstream_info(self) -> ExtInfo | None:
        # Take the newest version of the external versions
        newest = None
        fallback = None
        for ext_id, info in self.external_infos:
            if ext_id.fallback:
                if fallback is None or version_is_newer_than(info.version, fallback.version):
                    fallback = info
            else:
                if newest is None or version_is_newer_than(info.version, newest.version):
                    newest = info
        return newest or fallback or None

    @property
    def upstream_version(self) -> str:
        upstream_info = self.upstream_info
        return upstream_info.version if upstream_info is not None else ""

    @property
    def pkgextra(self) -> PkgExtraEntry:
        global state

        return state.pkgextra.packages.get(self.name, PkgExtraEntry())

    @property
    def urls(self) -> list[tuple[str, str]]:
        return self._package.urls

    @property
    def external_infos(self) -> Sequence[tuple[ExtId, ExtInfo]]:
        global state

        # internal package, don't try to link it
        if self.pkgextra.internal:
            return []

        ext = []
        for ext_id in state.ext_info_ids:
            if ext_id.id in self.pkgextra.references:
                mapped = self.pkgextra.references[ext_id.id]
                if mapped is None:
                    continue
                variants = [mapped]
            else:
                variants = get_realname_variants(self)

            infos = state.get_ext_infos(ext_id)
            for realname in variants:
                if realname in infos:
                    ext.append((ext_id, infos[realname]))
                    break

        return sorted(ext)

    @property
    def is_outdated(self) -> bool:
        msys_version = extract_upstream_version(self.version)
        return version_is_newer_than(self.upstream_version, msys_version)

    @property
    def realname(self) -> str:
        if self.name.startswith(self._package.base_prefix):
            return strip_vcs(self.name[len(self._package.base_prefix):])
        return strip_vcs(self.name)

    @property
    def date(self) -> int:
        """The build date of the newest package"""

        return sorted([p.builddate for p in self.packages.values()])[-1]

    @property
    def repo_url(self) -> str:
        return self._package.repo_url

    @property
    def repo_path(self) -> str:
        return self._package.repo_path

    @property
    def source_url(self) -> str:
        return self._package.source_url

    @property
    def history_url(self) -> str:
        return self._package.history_url

    @property
    def filebug_url(self) -> str:
        return self.repo_url + (
            "/issues/new?template=bug_report.yml&title=" + quote_plus("[%s] " % self.realname))

    @property
    def searchbug_url(self) -> str:
        return self.repo_url + (
            "/issues?q=" + quote_plus("is:issue is:open %s" % self.realname))

    @classmethod
    def from_desc(cls, d: dict[str, list[str]], repo: Repository) -> Source:

        name = d["%NAME%"][0]
        if "%BASE%" not in d:
            if name.startswith(repo.package_prefix):
                base = name[len(repo.package_prefix):]
            else:
                base = name
        else:
            base = d["%BASE%"][0]

        return cls(base)

    def add_desc(self, d: dict[str, list[str]], repo: Repository) -> None:
        p = Package.from_desc(d, self.name, repo)
        assert p.key not in self.packages
        self.packages[p.key] = p

    def get_info(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'realname': self.realname,
            'url': self.url,
            'version': self.version,
            'descriptions': self.desc,
            'arches': self.arches,
            'repos': self.repos,
            'source_url': self.source_url,
            'build_date': self.date,
            'licenses': self.licenses,
            'groups': self.groups,
        }


class SrcInfoPackage:

    def __init__(self, pkgbase: str, pkgname: str, pkgver: str, pkgrel: str,
                 repo: str, repo_url: str, repo_path: str, date: str, pkgbasedesc: str | None):
        self.pkgbase = pkgbase
        self.pkgname = pkgname
        self.pkgver = pkgver
        self.pkgrel = pkgrel
        self.repo = repo
        self.repo_url = repo_url
        self.repo_path = repo_path
        # iso 8601 to UTC without a timezone
        self.date = datetime.fromisoformat(date).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.epoch: str | None = None
        self.depends: dict[str, set[str]] = {}
        self.makedepends: dict[str, set[str]] = {}
        self.provides: dict[str, set[str]] = {}
        self.conflicts: dict[str, set[str]] = {}
        self.replaces: set[str] = set()
        self.sources: list[str] = []
        self.pkgbasedesc = pkgbasedesc

    @property
    def history_url(self) -> str:
        return self.repo_url + ("/commits/master/" + quote(self.repo_path))

    @property
    def source_url(self) -> str:
        return self.repo_url + ("/tree/master/" + quote(self.repo_path))

    @property
    def build_version(self) -> str:
        version = f"{self.pkgver}-{self.pkgrel}"
        if self.epoch:
            version = f"{self.epoch}~{version}"
        return version

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.pkgname} {self.build_version}>"

    @classmethod
    def for_srcinfo(cls, srcinfo: str, repo: str, repo_url: str, repo_path: str, date: str) -> set[SrcInfoPackage]:
        # parse pkgbase and then each pkgname
        base: dict[str, list[str]] = {}
        sub: dict[str, dict[str, list[str]]] = {}
        current = None
        for line in srcinfo.splitlines():
            line = line.strip()
            if not line:
                continue

            key, value = line.split(" =", 1)
            value = value.strip()
            values = [value] if value else []

            if current is None and key == "pkgbase":
                current = base
            elif key == "pkgname":
                name = line.split(" = ", 1)[-1]
                sub[name] = {}
                current = sub[name]
            if current is None:
                continue

            current.setdefault(key, []).extend(values)

        # everything not set in the packages, take from the base
        for bkey, bvalue in base.items():
            for items in sub.values():
                if bkey not in items:
                    items[bkey] = bvalue

        # special case: the base description is overwritten by the sub packages
        # but we still want to use it for the "base" package
        pkgbasedesc = base["pkgdesc"][0] if base.get("pkgdesc") else None

        packages = set()
        for name, pkg in sub.items():
            pkgbase = pkg["pkgbase"][0]
            pkgname = pkg["pkgname"][0]
            pkgver = pkg.get("pkgver", [""])[0]
            pkgrel = pkg.get("pkgrel", [""])[0]
            epoch = pkg.get("epoch", [""])[0]
            package = cls(
                pkgbase, pkgname, pkgver, pkgrel, repo,
                repo_url, repo_path, date, pkgbasedesc)
            package.epoch = epoch
            package.depends = split_depends(pkg.get("depends", []))
            package.makedepends = split_depends(pkg.get("makedepends", []))
            package.conflicts = split_depends(pkg.get("conflicts", []))
            package.provides = split_depends(pkg.get("provides", []))
            package.replaces = set(pkg.get("replaces", []))
            package.sources = pkg.get("sources", [])
            package.pkgbasedesc = pkgbasedesc
            packages.add(package)
        return packages


state = AppState()
