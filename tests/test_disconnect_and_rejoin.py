# tests/test_disconnect_and_rejoin.py
import pytest
from app.main import app
from tests.utils.game_client import GameClient


@pytest.mark.anyio
async def test_disconnect_and_rejoin(app):
    # P1,P2,P3,P4 sıralı bağlanma (manuel connect)
    p1 = GameClient(app, "P1")
    init1 = await p1.connect()
    assert init1 == {"type": "initial_state", "player_id": "P1"}

    p2 = GameClient(app, "P2")
    init2 = await p2.connect()
    assert init2 == {"type": "initial_state", "player_id": "P2"}

    # P1'e player_connected P2 gitmeli
    p1data = await p1.recv()
    assert p1data == {"type": "player_connected", "player_id": "P2"}

    p3 = GameClient(app, "P3")
    init3 = await p3.connect()
    assert init3 == {"type": "initial_state", "player_id": "P3"}

    assert await p1.recv() == {"type": "player_connected", "player_id": "P3"}
    assert await p2.recv() == {"type": "player_connected", "player_id": "P3"}

    p4 = GameClient(app, "P4")
    init4 = await p4.connect()
    assert init4 == {"type": "initial_state", "player_id": "P4"}

    # P1,P2,P3'e player_connected P4 gelmeli
    assert await p1.recv() == {"type": "player_connected", "player_id": "P4"}
    assert await p2.recv() == {"type": "player_connected", "player_id": "P4"}
    assert await p3.recv() == {"type": "player_connected", "player_id": "P4"}

    # game_started
    for c in (p1, p2, p3, p4):
        assert await c.recv() == {"type": "game_started"}

    # P1 hamle yapsın
    await p1.send({"type": "move", "player_id": "P1", "move": "X"})
    for c in (p1, p2, p3, p4):
        msg = await c.recv()
        assert msg["type"] == "game_update"
        assert msg["move"] == "P1 -> X"
        assert msg["next"] == "P2"

    # P2 disconnect
    await p2.close()

    # P1,P3,P4 player_disconnected P2 almalı
    for c in (p1, p3, p4):
        assert await c.recv() == {"type": "player_disconnected", "player_id": "P2"}

    # P5 bağlanır
    p5 = GameClient(app, "P5")
    init5 = await p5.connect()
    assert init5 == {"type": "initial_state", "player_id": "P5"}

    # diğerleri player_connected P5 almalı
    for c in (p1, p3, p4):
        assert await c.recv() == {"type": "player_connected", "player_id": "P5"}

    # P5 hamlesi
    await p5.send({"type": "move", "player_id": "P5", "move": "Y"})
    for c in (p1, p3, p4, p5):
        msg = await c.recv()
        assert msg["type"] == "game_update"
        assert msg["move"] == "P5 -> Y"

    # cleanup
    await p1.close()
    await p3.close()
    await p4.close()
    await p5.close()
