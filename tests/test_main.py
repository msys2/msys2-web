# type: ignore

import os

os.environ["NO_UPDATE_THREAD"] = "1"

import pytest
from app.main import app, parse_cygwin_versions


@pytest.fixture
def client():
    client = app.test_client()
    yield client


def test_main_endpoints(client):
    endpoints = [
        '', 'repos', 'base', 'group', 'updates', 'outofdate', 'queue', 'new',
        'removals', 'search', 'base/foo', 'group/foo', 'package/foo']

    for name in endpoints:
        r = client.get('/' + name, follow_redirects=True)
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
