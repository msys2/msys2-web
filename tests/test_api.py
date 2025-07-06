# type: ignore

def test_api(client):
    client.get('/api/buildqueue2').raise_for_status()
