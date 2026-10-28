import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="pw-test-"))
os.environ["DATA_DIR"] = str(_root)
os.environ["SKIP_MODELS"] = "1"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["MAX_UPLOAD_MB"] = "2"

import pytest
from fastapi.testclient import TestClient

from app.db import wipe
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        wipe(app.state.settings)
        yield test_client
