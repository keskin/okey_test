import pytest
import json
import json
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

class GameClient:
    def __init__(self, app, player_id: str):
        self.app = app
        self.player_id = player_id
        self.client = None
        self._ws_cm = None
        self.ws = None

    async def __aenter__(self):
        transport = ASGIWebSocketTransport(app=self.app)
        self.client = AsyncClient(transport=transport, base_url="http://test")
        self._ws_cm = aconnect_ws("/ws", self.client)
        self.ws = await self._ws_cm.__aenter__()

        # İlk mesaj initial_state olmalı
        msg = await self.ws.receive_text()
        data = json.loads(msg)
        assert data["type"] == "initial_state"
        assert data["player_id"] == self.player_id
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._ws_cm:
            await self._ws_cm.__aexit__(exc_type, exc, tb)
        if self.client:
            await self.client.aclose()

    async def send(self, msg: dict):
        if self.ws:
            await self.ws.send_text(json.dumps(msg))

    async def recv(self) -> dict:
        if self.ws:
            return json.loads(await self.ws.receive_text())
        return {}



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
