# type: ignore

import os

os.environ["NO_MIDDLEWARE"] = "1"

import pytest
from app.appstate import SrcInfoPackage, parse_packager
from app.fetch.cygwin import parse_cygwin_versions
from app.fetch.pypi import extract_pypi_project_from_purl
from app.utils import split_optdepends, vercmp
from app.pkgextra import extra_to_pkgextra_entry


@pytest.mark.parametrize("endpoint", [
    '', 'repos', 'base', 'group', 'groups', 'updates', 'outofdate', 'queue', 'new',
    'search', 'base/foo', 'group/foo', 'groups/foo', 'package/foo',
    'package', 'stats', 'mirrors', 'basegroups', 'basegroups/foo',
    'packages', 'packages/foo',
])
def test_main_endpoints(client, endpoint):
    r = client.get('/' + endpoint)
    assert r.status_code == (404 if "/" in endpoint else 200)
    assert "etag" in r.headers
    etag = r.headers["etag"]
    r = client.get('/' + endpoint, headers={"if-none-match": etag})
    assert r.status_code == 304
    r = client.get('/' + endpoint, headers={"if-none-match": "nope"})
    assert r.status_code == (404 if "/" in endpoint else 200)


def test_parse_cygwin_versions():
    data = b"""\
@ python36
category: Python Interpreters
requires: binutils cygwin libbz2_1 libcrypt0 libcrypt2 libexpat1 libffi6
version: 1:3.6.9-1
install: x86_64/release/python36/python36-3.6.9-1.tar.xz 5750152 96dd43cf9
source: x86_64/release/python36/python36-3.6.9-1-src.tar.xz 17223444 ef39d9419"""

    setup_ini_url = "https://mirrors.kernel.org/sourceware/cygwin/x86_64/setup.ini"
    versions = parse_cygwin_versions(setup_ini_url, data)[0]
    assert "python36" in versions
    assert versions["python36"].version == "3.6.9"
    assert versions["python36"].url == "https://cygwin.com/packages/summary/python36-src.html"
    assert versions["python36"].other_urls == {
        "https://mirrors.kernel.org/sourceware/cygwin/x86_64/release/python36/python36-3.6.9-1-src.tar.xz":
        "python36-3.6.9-1-src.tar.xz"
    }


def test_parse_cygwin_multiple():
    data = b"""\
@ gcc-cilkplus
version: 10.2.0-1
install: x86_64/release/gcc/gcc-cilkplus/gcc-cilkplus-10.2.0-1.tar.xz 108 96dd43cf9
source: x86_64/release/gcc/gcc-10.2.0-1-src.tar.xz 75022528 96dd43cf9
build-depends: cygport

@ gcc-core
version: 11.3.0-1
install: x86_64/release/gcc/gcc-core/gcc-core-11.3.0-1.tar.zst 31476642 96dd43cf9
source: x86_64/release/gcc/gcc-11.3.0-1-src.tar.zst 81157789 96dd43cf9
depends2: bash, binutils
obsoletes: gcc-ada, gcc-cilkplus
provides: gcc11
    """

    setup_ini_url = "https://mirrors.kernel.org/sourceware/cygwin/x86_64/setup.ini"
    versions = parse_cygwin_versions(setup_ini_url, data)[0]
    assert versions["gcc"].version == "11.3.0"

    data = b"""\
@ cygwin-debuginfo
sdesc: "Debug info for cygwin"
ldesc: "This package contains files necessary for debugging the
cygwin package with gdb."
category: Debug
version: 3.4.5-1
install: x86_64/release/cygwin/cygwin-debuginfo/cygwin-debuginfo-3.4.5-1.tar.xz 8703304 96dd43cf9
source: x86_64/release/cygwin/cygwin-3.4.5-1-src.tar.xz 8960088 96dd43cf9
[test]
version: 3.5.0-0.138.g6338d2f24a60
install: x86_64/release/cygwin/cygwin-debuginfo/cygwin-debuginfo-3.5.0-0.138.g6338d2f24a60.tar.xz 8672372 96dd43cf9
source: x86_64/release/cygwin/cygwin-3.5.0-0.138.g6338d2f24a60-src.tar.xz 9011204 96dd43cf9
depends2: cygwin-debuginfo
build-depends: autoconf, auto
"""

    setup_ini_url = "https://mirrors.kernel.org/sourceware/cygwin/x86_64/setup.ini"
    versions = parse_cygwin_versions(setup_ini_url, data)[0]
    assert versions["cygwin"].version == "3.4.5"


def test_parse_cygwin_mingw64():
    data = b"""\
@ mingw64-x86_64-headers
sdesc: "MinGW-w64 runtime headers and libraries"
ldesc: "MinGW-w64 runtime headers for Win32 64bit target"
category: Devel
version: 11.0.1-1
install: noarch/release/mingw64-x86_64-headers/mingw64-x86_64-headers-11.0.1-1.tar.xz 5431516 d9af7b3cb3472832de831f7238b7e21540a58b4b72018e8525efe57e1ca1f5c15cb3c06c88e09c8babaa598a8005cda67cbdacf5f3f27b537271f2f537c0ef74
source: noarch/release/mingw64-x86_64-headers/mingw64-x86_64-headers-11.0.1-1-src.tar.xz 9867916 8763e5e91b16130e2a32a861c176ba0334495937604b994c93fcf4323ffe0a6e7606215c3ddd60c11871f271279fcd96239f0748045179fe91b5f434d6702c23
depends2: mingw64-x86_64-winpthreads
build-depends: cygport
"""

    setup_ini_url = "https://mirrors.kernel.org/sourceware/cygwin/x86_64/setup.ini"
    versions = parse_cygwin_versions(setup_ini_url, data)[1]
    assert versions["headers"].version == "11.0.1"


def test_parse_packager():
    info = parse_packager("foobar")
    assert info.name == "foobar"
    assert info.email is None

    info = parse_packager("foobar <foobar@msys2.org>")
    assert info.name == "foobar"
    assert info.email == "foobar@msys2.org"


def test_split_optdepends():
    assert split_optdepends(["foo: bar"]) == {'foo': {'bar'}}
    assert split_optdepends(["foo: bar", "foo: quux"]) == {'foo': {'bar', 'quux'}}
    assert split_optdepends(["foobar"]) == {'foobar': set()}
    assert split_optdepends(["foobar:"]) == {'foobar': set()}


def test_for_srcinfo():
    info = """
pkgbase = libarchive
\tpkgver = 3.5.1
\tdepends = gcc-libs
pkgname = libarchive
pkgname = libarchive-devel
\tdepends = libxml2-devel
\treplaces = libarchive-devel-git
pkgname = something
\tdepends = \n"""

    packages = SrcInfoPackage.for_srcinfo(
        info, "repo", "https://foo.bar", "/", "2021-01-15")
    libarchive = [p for p in packages if p.pkgname == "libarchive"][0]
    assert list(libarchive.depends) == ["gcc-libs"]
    assert libarchive.pkgver == "3.5.1"
    devel = [p for p in packages if p.pkgname == "libarchive-devel"][0]
    assert list(devel.depends) == ["libxml2-devel"]
    assert list(devel.replaces) == ["libarchive-devel-git"]
    assert devel.pkgver == "3.5.1"
    something = [p for p in packages if p.pkgname == "something"][0]
    assert list(something.depends) == []


def test_for_pkgbasedesc():
    info = """
pkgbase = libarchive
\tpkgdesc = base-desc
pkgname = libarchive-devel
\tpkgdesc = sub-desc
\n"""

    packages = SrcInfoPackage.for_srcinfo(
        info, "repo", "https://foo.bar", "/", "2021-01-15")
    assert list(packages)[0].pkgbasedesc == "base-desc"


def test_vercmp():

    def test_ver(a, b, res):
        assert vercmp(a, b) == res
        assert vercmp(b, a) == (res * -1)

    test_ver("1.0.0", "2.0.0", -1)
    test_ver("1.0.0", "1.0.0.r101", -1)
    test_ver("1.0.0", "1.0.0", 0)
    test_ver("2019.10.06", "2020.12.07", -1)
    test_ver("1.3_20200327", "1.3_20210319", -1)
    test_ver("r2991.1771b556", "0.161.r3039.544c61f", -1)
    test_ver("6.8", "6.8.3", -1)
    test_ver("6.8", "6.8.", -1)
    test_ver("2.5.9.27149.9f6840e90c", "3.0.7.33374", -1)
    test_ver(".", "", 1)
    test_ver("0", "", 1)
    test_ver("0", "00", 0)
    test_ver(".", "..0", -1)
    test_ver(".0", "..0", -1)
    test_ver("1r", "1", -1)
    test_ver("r1", "r", 1)
    test_ver("1.1.0", "1.1.0a", 1)
    test_ver("1.1.0.", "1.1.0a", 1)
    test_ver("a", "1", -1)
    test_ver(".", "1", -1)
    test_ver(".", "a", 1)
    test_ver("a1", "1", -1)

    # FIXME:
    # test_ver(".0", "0", 1)


def test_extra_to_pkgextra_entry():
    assert extra_to_pkgextra_entry(
        {"references": ['foo: quux', 'bar']}
    ).references == {'foo': ['quux'], 'bar': [None]}
    assert extra_to_pkgextra_entry(
        {"changelog_url": "foo"}
    ).changelog_url == "foo"


def test_extract_pypi_project_from_purl():
    assert extract_pypi_project_from_purl("pkg:pypi/foo") == "foo"
    assert extract_pypi_project_from_purl("pkg:pypi/django@1.11.1") == "django"
    assert extract_pypi_project_from_purl("pkg:pypi/django?filename=Django-1.11.1.tar.gz") == "django"
    assert extract_pypi_project_from_purl("pkg:cargo/rand@0.7.2") is None
