# type: ignore

import os
import base64
import datetime

os.environ["NO_MIDDLEWARE"] = "1"

import pytest
from app import app
from app.appstate import SrcInfoPackage, parse_packager
from app.fetch import parse_cygwin_versions
from app.pgp import parse_signature, SigError, Signature
from app.utils import split_optdepends, strip_vcs
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    os.environ["NO_UPDATE_THREAD"] = "1"
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("endpoint", [
    '', 'repos', 'base', 'group', 'updates', 'outofdate', 'queue', 'new',
    'removals', 'search', 'base/foo', 'group/foo', 'package/foo',
    'package',
])
def test_main_endpoints(client, endpoint):
    r = client.get('/' + endpoint)
    assert r.status_code == 200
    assert "etag" in r.headers
    etag = r.headers["etag"]
    r = client.get('/' + endpoint, headers={"if-none-match": etag})
    assert r.status_code == 304
    r = client.get('/' + endpoint, headers={"if-none-match": "nope"})
    assert r.status_code == 200


def test_parse_cygwin_versions():
    data = b"""\
@ python36
category: Python Interpreters
requires: binutils cygwin libbz2_1 libcrypt0 libcrypt2 libexpat1 libffi6
version: 3.6.9-1
install: x86_64/release/python36/python36-3.6.9-1.tar.xz 5750152 96dd43cf9
source: x86_64/release/python36/python36-3.6.9-1-src.tar.xz 17223444 ef39d9419"""

    setup_ini_url = "https://mirrors.kernel.org/sourceware/cygwin/x86_64/setup.ini"
    versions = parse_cygwin_versions(setup_ini_url, data)
    assert "python36" in versions
    assert versions["python36"][0] == "3.6.9"
    assert versions["python36"][1] == "https://cygwin.com/packages/summary/python36-src.html"
    assert versions["python36"][2] == "https://mirrors.kernel.org/sourceware/cygwin/x86_64/release/python36/python36-3.6.9-1-src.tar.xz"


EXAMPLE_SIG = (
    "iHUEABEIAB0WIQStNRxQrghXdetZMztfku/BpH1FoQUCXlOY5wAKCRBfku"
    "/BpH1FodQoAP4nQnPNLnx5MVIJgZgCwW/hplW7Ai9MqkmFBqD8/+EXfAD/"
    "Rgxtz2XH7RZ1JKh7PN5NsVz9UlBM7977PjFg9WptNGU=")


def test_pgp():
    with pytest.raises(SigError):
        parse_signature(b"")

    with pytest.raises(SigError):
        parse_signature(b"foobar")

    data = base64.b64decode(EXAMPLE_SIG)
    sig = parse_signature(data)
    assert isinstance(sig, Signature)
    assert sig.keyid == "5f92efc1a47d45a1"
    assert sig.date == datetime.datetime(2020, 2, 24, 9, 35, 35)
    assert sig.name == "Alexey Pavlov"
    assert sig.url == "http://pool.sks-keyservers.net/pks/lookup?op=vindex&fingerprint=on&search=0x5f92efc1a47d45a1"


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


def test_strip_vcs():
    assert strip_vcs("foo") == "foo"
    assert strip_vcs("foo-git") == "foo"


def test_for_srcinfo():
    info = """
pkgbase = libarchive
\tpkgver = 3.5.1
\tdepends = gcc-libs
pkgname = libarchive
pkgname = libarchive-devel
\tdepends = libxml2-devel
pkgname = something
\tdepends = \n"""

    packages = SrcInfoPackage.for_srcinfo(
        info, "repo", "https://foo.bar", "/", "2021-01-15")
    libarchive = [p for p in packages if p.pkgname == "libarchive"][0]
    assert list(libarchive.depends) == ["gcc-libs"]
    assert libarchive.pkgver == "3.5.1"
    devel = [p for p in packages if p.pkgname == "libarchive-devel"][0]
    assert list(devel.depends) == ["libxml2-devel"]
    assert devel.pkgver == "3.5.1"
    something = [p for p in packages if p.pkgname == "something"][0]
    assert list(something.depends) == []
