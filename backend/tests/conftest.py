import os
import tempfile
from pathlib import Path
import pytest

# Configure an isolated database before importing any application modules.
_test_root = tempfile.TemporaryDirectory(prefix="ed-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_test_root.name) / "tests.db")
os.environ["UPLOAD_DIR"] = str(Path(_test_root.name) / "uploads")
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTH_PASSWORD"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db.session import Base, engine, SessionLocal  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
