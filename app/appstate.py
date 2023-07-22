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
from typing import List, Set, Dict, Tuple, Optional, Type, Sequence, NamedTuple, Any
from pydantic import BaseModel

from .appconfig import REPOSITORIES
from .utils import vercmp, version_is_newer_than, extract_upstream_version, split_depends, \
    split_optdepends, strip_vcs
from .pgp import parse_signature
from .pkgmeta import PkgMeta, PkgMetaEntry


PackageKey = Tuple[str, str, str, str, str]

ExtId = NamedTuple('ExtId', [
    ('id', str),
    ('name', str),
    # If the versions should be considered only as a fallback
    ('fallback', bool),
])

ExtInfo = NamedTuple('ExtInfo', [
    ('name', str),
    ('version', str),
    ('date', int),
    ('url', str),
    ('other_urls', Dict[str, str]),
])

PackagerInfo = NamedTuple('PackagerInfo', [
    ('name', str),
    ('email', Optional[str]),
])


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


def get_repositories() -> List[Repository]:
    l = []
    for data in REPOSITORIES:
        l.append(Repository(*data))
    return l


def get_realname_variants(s: Source) -> List[str]:
    """Returns a list of potential names used by external systems, highest priority first"""

    main = [s.realname, s.realname.lower()]

    package_variants = [p.realname for p in s.packages.values()]

    # fallback to the provide names
    provides_variants: List[str] = []
    for p in s.packages.values():
        provides_variants.extend(p.realprovides.keys())

    return main + sorted(package_variants) + sorted(provides_variants)


def cleanup_files(files: List[str]) -> List[str]:
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
    def packages(self) -> "List[Package]":
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
    desc: Optional[str]
    status: str
    urls: Dict[str, str]


class BuildStatusPackage(BaseModel):
    name: str
    version: str
    builds: Dict[str, BuildStatusBuild]


class BuildStatus(BaseModel):
    packages: List[BuildStatusPackage] = []
    cycles: List[Tuple[str, str]] = []


class AppState:

    def __init__(self) -> None:
        self._update_etag()

        self._etag = ""
        self.ready = False
        self._last_update = 0.0
        self._sources: Dict[str, Source] = {}
        self._sourceinfos: Dict[str, SrcInfoPackage] = {}
        self._pkgmeta: PkgMeta = PkgMeta(packages={})
        self._ext_infos: Dict[ExtId, Dict[str, ExtInfo]] = {}
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
    def sources(self) -> Dict[str, Source]:
        return self._sources

    @sources.setter
    def sources(self, sources: Dict[str, Source]) -> None:
        self._sources = sources
        self._update_etag()

    @property
    def sourceinfos(self) -> Dict[str, SrcInfoPackage]:
        return self._sourceinfos

    @sourceinfos.setter
    def sourceinfos(self, sourceinfos: Dict[str, SrcInfoPackage]) -> None:
        self._sourceinfos = sourceinfos
        self._update_etag()

    @property
    def pkgmeta(self) -> PkgMeta:
        return self._pkgmeta

    @pkgmeta.setter
    def pkgmeta(self, pkgmeta: PkgMeta) -> None:
        self._pkgmeta = pkgmeta
        self._update_etag()

    @property
    def ext_info_ids(self) -> List[ExtId]:
        return list(self._ext_infos.keys())

    def get_ext_infos(self, id: ExtId) -> Dict[str, ExtInfo]:
        return self._ext_infos.get(id, {})

    def set_ext_infos(self, id: ExtId, info: Dict[str, ExtInfo]) -> None:
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

    def __init__(self, builddate: str, csize: str, depends: List[str], filename: str, files: List[str], isize: str,
                 makedepends: List[str], md5sum: str, name: str, pgpsig: str, sha256sum: str, arch: str,
                 base_url: str, repo: str, repo_variant: str, package_prefix: str, base_prefix: str,
                 provides: List[str], conflicts: List[str], replaces: List[str],
                 version: str, base: str, desc: str, groups: List[str], licenses: List[str], optdepends: List[str],
                 checkdepends: List[str], sig_data: str, url: str, packager: str) -> None:
        self.builddate = int(builddate)
        self.csize = csize
        self.url = url
        self.signature = parse_signature(base64.b64decode(sig_data))
        self.depends = split_depends(depends)
        self.checkdepends = split_depends(checkdepends)
        self.filename = filename
        self._files = "\n".join(cleanup_files(files))
        self.isize = isize
        self.makedepends = split_depends(makedepends)
        self.md5sum = md5sum
        self.name = name
        self.pgpsig = pgpsig
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
        self.rdepends: Dict[Package, Set[DepType]] = {}
        self.optdepends = split_optdepends(optdepends)
        self.packager = parse_packager(packager)
        self.provided_by: Set[Package] = set()

    @property
    def files(self) -> Sequence[str]:
        return self._files.splitlines()

    def __repr__(self) -> str:
        return "Package(%s)" % self.fileurl

    @property
    def realprovides(self) -> Dict[str, Set[str]]:
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
    def from_desc(cls: Type[Package], d: Dict[str, List[str]], base: str, repo: Repository) -> Package:
        return cls(d["%BUILDDATE%"][0], d["%CSIZE%"][0],
                   d.get("%DEPENDS%", []), d["%FILENAME%"][0],
                   d.get("%FILES%", []), d["%ISIZE%"][0],
                   d.get("%MAKEDEPENDS%", []),
                   d["%MD5SUM%"][0], d["%NAME%"][0],
                   d.get("%PGPSIG%", [""])[0], d["%SHA256SUM%"][0],
                   d["%ARCH%"][0], repo.download_url, repo.name, repo.variant,
                   repo.package_prefix, repo.base_prefix,
                   d.get("%PROVIDES%", []), d.get("%CONFLICTS%", []),
                   d.get("%REPLACES%", []), d["%VERSION%"][0], base,
                   d.get("%DESC%", [""])[0], d.get("%GROUPS%", []),
                   d.get("%LICENSE%", []), d.get("%OPTDEPENDS%", []),
                   d.get("%CHECKDEPENDS%", []), d.get("%PGPSIG%", [""])[0],
                   d.get("%URL%", [""])[0], d.get("%PACKAGER%", [""])[0])


class Source:

    def __init__(self, name: str):
        self.name = name
        self.packages: Dict[PackageKey, Package] = {}

    @property
    def desc(self) -> str:
        return self._package.desc

    @property
    def _package(self) -> Package:
        return sorted(self.packages.items())[0][1]

    @property
    def repos(self) -> List[str]:
        return sorted(set([p.repo for p in self.packages.values()]))

    @property
    def url(self) -> str:
        return self._package.url

    @property
    def arches(self) -> List[str]:
        return sorted(set([p.arch for p in self.packages.values()]))

    @property
    def groups(self) -> List[str]:
        groups: Set[str] = set()
        for p in self.packages.values():
            groups.update(p.groups)
        return sorted(groups)

    @property
    def basegroups(self) -> List[str]:
        groups: Set[str] = set()
        for p in self.packages.values():
            groups.update(get_base_group_name(p, g) for g in p.groups)
        return sorted(groups)

    @property
    def version(self) -> str:
        # get the newest version
        versions: Set[str] = set([p.version for p in self.packages.values()])
        return sorted(versions, key=cmp_to_key(vercmp), reverse=True)[0]

    @property
    def git_version(self) -> str:
        # get the newest version
        versions: Set[str] = set([p.git_version for p in self.packages.values()])
        return sorted(versions, key=cmp_to_key(vercmp), reverse=True)[0]

    @property
    def licenses(self) -> List[List[str]]:
        licenses: List[List[str]] = []
        for p in self.packages.values():
            if p.licenses and p.licenses not in licenses:
                licenses.append(p.licenses)
        return sorted(licenses)

    @property
    def upstream_info(self) -> Optional[ExtInfo]:
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
    def pkgmeta(self) -> PkgMetaEntry:
        global state

        return state.pkgmeta.packages.get(self.name, PkgMetaEntry())

    @property
    def external_infos(self) -> Sequence[Tuple[ExtId, ExtInfo]]:
        global state

        # internal package, don't try to link it
        if self.pkgmeta.internal:
            return []

        ext = []
        for ext_id in state.ext_info_ids:
            if ext_id.id in self.pkgmeta.references:
                mapped = self.pkgmeta.references[ext_id.id]
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

        for ext_id, info in self.external_infos:
            if version_is_newer_than(info.version, msys_version):
                return True
        return False

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
    def from_desc(cls, d: Dict[str, List[str]], repo: Repository) -> "Source":

        name = d["%NAME%"][0]
        if "%BASE%" not in d:
            if name.startswith(repo.package_prefix):
                base = name[len(repo.package_prefix):]
            else:
                base = name
        else:
            base = d["%BASE%"][0]

        return cls(base)

    def add_desc(self, d: Dict[str, List[str]], repo: Repository) -> None:
        p = Package.from_desc(d, self.name, repo)
        assert p.key not in self.packages
        self.packages[p.key] = p

    def get_info(self) -> Dict[str, Any]:
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


class SrcInfoPackage(object):

    def __init__(self, pkgbase: str, pkgname: str, pkgver: str, pkgrel: str,
                 repo: str, repo_url: str, repo_path: str, date: str):
        self.pkgbase = pkgbase
        self.pkgname = pkgname
        self.pkgver = pkgver
        self.pkgrel = pkgrel
        self.repo = repo
        self.repo_url = repo_url
        self.repo_path = repo_path
        # iso 8601 to UTC without a timezone
        self.date = datetime.fromisoformat(date).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.epoch: Optional[str] = None
        self.depends: Dict[str, Set[str]] = {}
        self.makedepends: Dict[str, Set[str]] = {}
        self.provides: Dict[str, Set[str]] = {}
        self.conflicts: Dict[str, Set[str]] = {}
        self.replaces: Set[str] = set()
        self.sources: List[str] = []

    @property
    def history_url(self) -> str:
        return self.repo_url + ("/commits/master/" + quote(self.repo_path))

    @property
    def source_url(self) -> str:
        return self.repo_url + ("/tree/master/" + quote(self.repo_path))

    @property
    def build_version(self) -> str:
        version = "%s-%s" % (self.pkgver, self.pkgrel)
        if self.epoch:
            version = "%s~%s" % (self.epoch, version)
        return version

    def __repr__(self) -> str:
        return "<%s %s %s>" % (
            type(self).__name__, self.pkgname, self.build_version)

    @classmethod
    def for_srcinfo(cls, srcinfo: str, repo: str, repo_url: str, repo_path: str, date: str) -> "Set[SrcInfoPackage]":
        # parse pkgbase and then each pkgname
        base: Dict[str, List[str]] = {}
        sub: Dict[str, Dict[str, List[str]]] = {}
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

        packages = set()
        for name, pkg in sub.items():
            pkgbase = pkg["pkgbase"][0]
            pkgname = pkg["pkgname"][0]
            pkgver = pkg.get("pkgver", [""])[0]
            pkgrel = pkg.get("pkgrel", [""])[0]
            epoch = pkg.get("epoch", [""])[0]
            package = cls(pkgbase, pkgname, pkgver, pkgrel, repo, repo_url, repo_path, date)
            package.epoch = epoch
            package.depends = split_depends(pkg.get("depends", []))
            package.makedepends = split_depends(pkg.get("makedepends", []))
            package.conflicts = split_depends(pkg.get("conflicts", []))
            package.provides = split_depends(pkg.get("provides", []))
            package.replaces = set(pkg.get("replaces", []))
            package.sources = pkg.get("sources", [])
            packages.add(package)
        return packages


state = AppState()
