# type: ignore

import json


def _get_sse_data(response):
    for line in response.text.split('\n'):
        if line.startswith('data:'):
            return json.loads(line[5:].strip())


def test_msys2_vercmp(client):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "msys2_vercmp",
            "arguments": {
                "versionA": "1.0.0",
                "versionB": "1.0.1"
            }
        }
    }

    headers = {
        "Accept": "application/json, text/event-stream"
    }

    response = client.post('/mcp/mcp', json=payload, headers=headers)
    response.raise_for_status()
    data = _get_sse_data(response)
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "result" in data
    assert data["result"]["content"][0]["text"] == "-1"
