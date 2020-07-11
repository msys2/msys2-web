# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
import base64
import uuid
import time
from functools import cmp_to_key
from urllib.parse import quote_plus, quote
from typing import List, Set, Dict, Tuple, Optional, Type, Sequence, NamedTuple

from .appconfig import REPOSITORIES
from .utils import vercmp, version_is_newer_than, extract_upstream_version, split_depends, \
    split_optdepends
from .pgp import parse_signature


CygwinVersions = Dict[str, Tuple[str, str, str]]

PackageKey = Tuple[str, str, str, str, str]

ExtInfo = NamedTuple('ExtInfo', [
    ('name', str),
    ('version', str),
    ('date', int),
    ('url', str),
    ('other_urls', List[str]),
])


def get_repositories() -> List[Repository]:
    l = []
    for data in REPOSITORIES:
        l.append(Repository(*data))
    return l


def is_skipped(name: str) -> bool:
    skipped = state.arch_mapping.skipped
    for pattern in skipped:
        if re.fullmatch(pattern, name, flags=re.IGNORECASE) is not None:
            return True
    return False


def get_arch_names(name: str) -> List[str]:
    mapping = state.arch_mapping.mapping
    names: List[str] = []

    def add(n: str) -> None:
        if n not in names:
            names.append(n)

    name = name.lower()

    if is_skipped(name):
        return []

    for pattern, repl in mapping.items():
        new = re.sub("^" + pattern + "$", repl, name, flags=re.IGNORECASE)
        if new != name:
            add(new)
            break

    add(name)

    return names


def get_arch_info_for_base(s: Source) -> Optional[Tuple[str, str, int]]:
    """tuple or None"""

    global state

    variants = sorted([s.realname] + [p.realname for p in s.packages.values()])

    # fallback to the provide names
    provides_variants: List[str] = []
    for p in s.packages.values():
        provides_variants.extend(p.realprovides.keys())
    variants += provides_variants

    for realname in variants:
        for arch_name in get_arch_names(realname):
            if arch_name in state.arch_versions:
                return state.arch_versions[arch_name]
    return None


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


class Repository:

    def __init__(self, name: str, variant: str, url: str, src_url: str):
        self.name = name
        self.variant = variant
        self.url = url
        self.src_url = src_url

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


class ArchMapping:

    mapping: Dict[str, str]
    skipped: Set[str]

    def __init__(self, json_object: Optional[Dict] = None) -> None:
        if json_object is None:
            json_object = {}
        self.mapping = json_object.get("mapping", {})
        self.skipped = set(json_object.get("skipped", []))


class AppState:

    def __init__(self) -> None:
        self._update_etag()

        self._etag = ""
        self._last_update = 0.0
        self._sources: Dict[str, Source] = {}
        self._sourceinfos: Dict[str, SrcInfoPackage] = {}
        self._arch_versions: Dict[str, Tuple[str, str, int]] = {}
        self._arch_mapping: ArchMapping = ArchMapping()
        self._cygwin_versions: CygwinVersions = {}
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
    def arch_versions(self) -> Dict[str, Tuple[str, str, int]]:
        return self._arch_versions

    @arch_versions.setter
    def arch_versions(self, versions: Dict[str, Tuple[str, str, int]]) -> None:
        self._arch_versions = versions
        self._update_etag()

    @property
    def arch_mapping(self) -> ArchMapping:
        return self._arch_mapping

    @arch_mapping.setter
    def arch_mapping(self, arch_mapping: ArchMapping) -> None:
        self._arch_mapping = arch_mapping
        self._update_etag()

    @property
    def cygwin_versions(self) -> CygwinVersions:
        return self._cygwin_versions

    @cygwin_versions.setter
    def cygwin_versions(self, cygwin_versions: CygwinVersions) -> None:
        self._cygwin_versions = cygwin_versions
        self._update_etag()


class Package:

    def __init__(self, builddate: str, csize: str, depends: List[str], filename: str, files: List[str], isize: str,
                 makedepends: List[str], md5sum: str, name: str, pgpsig: str, sha256sum: str, arch: str,
                 base_url: str, repo: str, repo_variant: str, provides: List[str], conflicts: List[str], replaces: List[str],
                 version: str, base: str, desc: str, groups: List[str], licenses: List[str], optdepends: List[str],
                 checkdepends: List[str], sig_data: str, url: str) -> None:
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
        self.provides = split_depends(provides)
        self.conflicts = split_depends(conflicts)
        self.replaces = split_depends(replaces)
        self.version = version
        self.base = base
        self.desc = desc
        self.groups = groups
        self.licenses = licenses
        self.rdepends: Dict[Package, Set[str]] = {}
        self.optdepends = split_optdepends(optdepends)

    @property
    def files(self) -> Sequence[str]:
        return self._files.splitlines()

    def __repr__(self) -> str:
        return "Package(%s)" % self.fileurl

    @property
    def realprovides(self) -> Dict[str, Set[str]]:
        prov = {}
        for key, infos in self.provides.items():
            if key.startswith("mingw"):
                key = key.split("-", 3)[-1]
            prov[key] = infos
        return prov

    @property
    def realname(self) -> str:
        if self.repo.startswith("mingw"):
            return self.name.split("-", 3)[-1]
        return self.name

    @property
    def git_version(self) -> str:
        if self.name in state.sourceinfos:
            return state.sourceinfos[self.name].build_version
        return ""

    @property
    def key(self) -> PackageKey:
        return (self.repo, self.repo_variant,
                self.name, self.arch, self.fileurl)

    @classmethod
    def from_desc(cls: Type[Package], d: Dict[str, List[str]], base: str, base_url: str, repo: str, repo_variant: str) -> Package:
        return cls(d["%BUILDDATE%"][0], d["%CSIZE%"][0],
                   d.get("%DEPENDS%", []), d["%FILENAME%"][0],
                   d.get("%FILES%", []), d["%ISIZE%"][0],
                   d.get("%MAKEDEPENDS%", []),
                   d["%MD5SUM%"][0], d["%NAME%"][0],
                   d.get("%PGPSIG%", [""])[0], d["%SHA256SUM%"][0],
                   d["%ARCH%"][0], base_url, repo, repo_variant,
                   d.get("%PROVIDES%", []), d.get("%CONFLICTS%", []),
                   d.get("%REPLACES%", []), d["%VERSION%"][0], base,
                   d.get("%DESC%", [""])[0], d.get("%GROUPS%", []),
                   d.get("%LICENSE%", []), d.get("%OPTDEPENDS%", []),
                   d.get("%CHECKDEPENDS%", []), d.get("%PGPSIG%", [""])[0],
                   d.get("%URL%", [""])[0])


class Source:

    def __init__(self, name: str, desc: str, packager: str):
        self.name = name
        self.desc = desc
        self.packager = packager
        self.packages: Dict[PackageKey, Package] = {}

    @property
    def _package(self) -> Package:
        return sorted(self.packages.items())[-1][1]

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
    def licenses(self) -> List[str]:
        licenses: Set[str] = set()
        for p in self.packages.values():
            licenses.update(p.licenses)
        return sorted(licenses)

    @property
    def upstream_version(self) -> str:
        # Take the newest version of the external versions
        version = None
        for info in self.external_infos:
            if version is None or version_is_newer_than(info.version, version):
                version = info.version
        return version or ""

    @property
    def external_infos(self) -> Sequence[ExtInfo]:
        global state

        ext = []
        arch_info = get_arch_info_for_base(self)
        if arch_info is not None:
            version = extract_upstream_version(arch_info[0])
            url = arch_info[1]
            ext.append(ExtInfo("Arch Linux", version, arch_info[2], url, []))

        cygwin_versions = state.cygwin_versions
        if self.name in cygwin_versions:
            info = cygwin_versions[self.name]
            ext.append(ExtInfo("Cygwin", info[0], 0, info[1], [info[2]]))

        return sorted(ext)

    @property
    def is_outdated(self) -> bool:
        msys_version = extract_upstream_version(self.version)

        for info in self.external_infos:
            if version_is_newer_than(info.version, msys_version):
                return True
        return False

    @property
    def realname(self) -> str:
        if self._package.repo.startswith("mingw"):
            return self.name.split("-", 2)[-1]
        return self.name

    @property
    def date(self) -> int:
        """The build date of the newest package"""

        return sorted([p.builddate for p in self.packages.values()])[-1]

    @property
    def repo_url(self) -> str:
        for p in self.packages.values():
            if p.name in state.sourceinfos:
                return state.sourceinfos[p.name].repo_url
            for repo in get_repositories():
                if repo.name == p.repo:
                    return repo.src_url
        return ""

    @property
    def repo_path(self) -> str:
        for p in self.packages.values():
            if p.name in state.sourceinfos:
                return state.sourceinfos[p.name].repo_path
        return self.name

    @property
    def source_url(self) -> str:
        return self.repo_url + ("/tree/master/" + quote(self.repo_path))

    @property
    def history_url(self) -> str:
        return self.repo_url + ("/commits/master/" + quote(self.repo_path))

    @property
    def filebug_url(self) -> str:
        return self.repo_url + (
            "/issues/new?title=" + quote_plus("[%s]" % self.realname))

    @property
    def searchbug_url(self) -> str:
        return self.repo_url + (
            "/issues?q=" + quote_plus("is:issue is:open %s" % self.realname))

    @classmethod
    def from_desc(cls, d: Dict[str, List[str]], repo: str) -> "Source":

        name = d["%NAME%"][0]
        if "%BASE%" not in d:
            if repo.startswith("mingw"):
                base = "mingw-w64-" + name.split("-", 3)[-1]
            else:
                base = name
        else:
            base = d["%BASE%"][0]

        return cls(base, d.get("%DESC%", [""])[0], d["%PACKAGER%"][0])

    def add_desc(self, d: Dict[str, List[str]], base_url: str, repo: str, repo_variant: str) -> None:
        p = Package.from_desc(
            d, self.name, base_url, repo, repo_variant)
        assert p.key not in self.packages
        self.packages[p.key] = p


class SrcInfoPackage(object):

    def __init__(self, pkgbase: str, pkgname: str, pkgver: str, pkgrel: str,
                 repo: str, repo_path: str, date: str):
        self.pkgbase = pkgbase
        self.pkgname = pkgname
        self.pkgver = pkgver
        self.pkgrel = pkgrel
        self.repo_url = repo
        self.repo_path = repo_path
        self.date = date
        self.epoch: Optional[str] = None
        self.depends: Dict[str, Set[str]] = {}
        self.makedepends: Dict[str, Set[str]] = {}
        self.provides: Dict[str, Set[str]] = {}
        self.conflicts: Dict[str, Set[str]] = {}
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
    def for_srcinfo(cls, srcinfo: str, repo: str, repo_path: str, date: str) -> "Set[SrcInfoPackage]":
        packages = set()

        for line in srcinfo.splitlines():
            line = line.strip()
            if line.startswith("pkgbase = "):
                pkgver = pkgrel = epoch = ""
                depends = []
                makedepends = []
                sources = []
                pkgbase = line.split(" = ", 1)[-1]
                provides = []
                conflicts = []
            elif line.startswith("depends = "):
                depends.append(line.split(" = ", 1)[-1])
            elif line.startswith("makedepends = "):
                makedepends.append(line.split(" = ", 1)[-1])
            elif line.startswith("source = "):
                sources.append(line.split(" = ", 1)[-1])
            elif line.startswith("pkgver = "):
                pkgver = line.split(" = ", 1)[-1]
            elif line.startswith("pkgrel = "):
                pkgrel = line.split(" = ", 1)[-1]
            elif line.startswith("epoch = "):
                epoch = line.split(" = ", 1)[-1]
            elif line.startswith("provides = "):
                provides.append(line.split(" = ", 1)[-1])
            elif line.startswith("conflicts = "):
                conflicts.append(line.split(" = ", 1)[-1])
            elif line.startswith("pkgname = "):
                pkgname = line.split(" = ", 1)[-1]
                package = cls(pkgbase, pkgname, pkgver, pkgrel, repo, repo_path, date)
                package.epoch = epoch
                package.depends = split_depends(depends)
                package.makedepends = split_depends(makedepends)
                package.sources = sources
                package.conflicts = split_depends(conflicts)
                package.provides = split_depends(provides)
                packages.add(package)

        return packages


state = AppState()
