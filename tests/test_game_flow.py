import pytest
from tests.utils.game_client import GameClient

@pytest.mark.anyio
async def test_full_game_flow(app):
    async with GameClient(app, "P1") as p1, \
               GameClient(app, "P2") as p2, \
               GameClient(app, "P3") as p3, \
               GameClient(app, "P4") as p4:

        # P2 bağlanınca P1'e player_connected gelir
        assert await p1.recv() == {"type": "player_connected", "player_id": "P2"}

        # P3 bağlanınca P1 ve P2'ye player_connected gelir
        assert await p1.recv() == {"type": "player_connected", "player_id": "P3"}
        assert await p2.recv() == {"type": "player_connected", "player_id": "P3"}

        # P4 bağlanınca diğer üçüne player_connected gelir
        assert await p1.recv() == {"type": "player_connected", "player_id": "P4"}
        assert await p2.recv() == {"type": "player_connected", "player_id": "P4"}
        assert await p3.recv() == {"type": "player_connected", "player_id": "P4"}

        # Tüm oyuncular game_started alır
        for player in [p1, p2, p3, p4]:
            assert await player.recv() == {"type": "game_started"}

        # P1 hamle yapar
        await p1.send({"type": "move", "player_id": "P1", "move": "X"})

        # Herkes game_update alır
        for player in [p1, p2, p3, p4]:
            msg = await player.recv()
            assert msg["type"] == "game_update"
            assert msg["move"] == "P1 -> X"
            assert msg["next"] == "P2"
