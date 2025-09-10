# tests/conftest.py
import pytest
from app import main
from app.main import app as fastapi_app

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="function")
def app():
    # Her testten önce state'i sıfırla
    main.connected_players.clear()
    main.player_ids.clear()
    main.turn_index = 0
    main.game_started = False
    return fastapi_app
