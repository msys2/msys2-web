# type: ignore

import os
import pytest
from fastapi.testclient import TestClient

os.environ["NO_MIDDLEWARE"] = "1"

from app import app


@pytest.fixture(scope="session")
def client():
    os.environ["NO_UPDATE_THREAD"] = "1"
    with TestClient(app) as client:
        yield client
