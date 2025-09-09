# tests/conftest.py
import pytest

# 'app' nesnesini doğrudan import ediyoruz.
from app.main import app as fastapi_app

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

# Bu fixture, test edilecek olan FastAPI uygulamasını sağlar.
@pytest.fixture(scope="function")
def app():
    return fastapi_app