# type: ignore

import os

import respx
import pytest
from app import app
from app.fetch import parse_cygwin_versions
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    os.environ["NO_UPDATE_THREAD"] = "1"
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("endpoint", [
    '', 'repos', 'base', 'group', 'updates', 'outofdate', 'queue', 'new',
    'removals', 'search', 'base/foo', 'group/foo', 'package/foo', 'python2',
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


def test_webhook_ping(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "foobar")

    r = client.post("/webhook", headers={
        "X-Hub-Signature": "sha1=241ebb961521e58a8b2d5d1436863df772ffd531",
        "X-GitHub-Event": "ping",
    })
    r.raise_for_status()
    assert r.json() == {"msg": "pong"}


def test_webhook_push(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "foobar")
    monkeypatch.setenv("APPVEYOR_ACCOUNT", "account")
    monkeypatch.setenv("APPVEYOR_PROJECT", "project")
    monkeypatch.setenv("APPVEYOR_TOKEN", "token")

    with respx.mock:
        request = respx.post(
            "https://ci.appveyor.com/api/builds",
            status_code=201,
            content={
                "buildId": 1234
            })

        r = client.post("/webhook", headers={
            "X-Hub-Signature": "sha1=241ebb961521e58a8b2d5d1436863df772ffd531",
            "X-GitHub-Event": "push",
        })
        assert request.called
        r.raise_for_status()
        assert "msg" in r.json()
        assert "1234" in r.json()["msg"]
