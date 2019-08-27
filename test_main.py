# type: ignore

import pytest
from main import app


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
