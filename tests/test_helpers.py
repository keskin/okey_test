# tests/test_helpers.py (Yeni dosya)
import asyncio
import anyio
from httpx import AsyncClient
from httpx_ws import aconnect_ws, AsyncWebSocketSession
from httpx_ws.transport import ASGIWebSocketTransport
from fastapi import FastAPI

class TestPlayer:
    """
    Bir WebSocket oyuncusunu simüle eden ve test senaryolarını yöneten bir yardımcı sınıf.
    """
    def __init__(self, app: FastAPI, player_id: str):
        self.app = app
        self.player_id = player_id
        self.websocket: AsyncWebsocketSession = None
        # Gelen mesajlar için bir "gelen kutusu" (inbox)
        self._inbox = anyio.create_memory_object_stream(max_buffer_size=100)

    async def listen(self):
        """
        Arka planda çalışarak sunucudan gelen mesajları dinler ve inbox'a koyar.
        """
        try:
            async for message in self.websocket:
                await self._inbox.send(message.json())
        except Exception:
            # Bağlantı kapandığında veya hata olduğunda dinleyiciyi sonlandır.
            pass

    async def connect(self, task_group):
        """
        Sunucuya bağlanır ve arka plan dinleyicisini başlatır.
        """
        transport = ASGIWebSocketTransport(app=self.app)
        client = await AsyncClient(transport=transport, base_url="http://test").__aenter__()
        self.websocket = await aconnect_ws(f"/ws/{self.player_id}", client).__aenter__()
        task_group.start_soon(self.listen)
        print(f"Oyuncu {self.player_id} bağlandı.")

    async def send_move(self, move: dict):
        """Sunucuya bir hamle mesajı gönderir."""
        await self.websocket.send_json(move)
        print(f"Oyuncu {self.player_id} hamle gönderdi: {move}")

    async def expect_message(self, timeout: float = 2.0):
        """
        Belirtilen süre içinde bir sonraki mesajı bekler ve döndürür.
        """
        print(f"Oyuncu {self.player_id} mesaj bekliyor...")
        with anyio.fail_after(timeout):
            message = await self._inbox.receive()
            print(f"Oyuncu {self.player_id} mesaj aldı: {message}")
            return message

    async def assert_message(self, expected_type: str, expected_payload: dict = None, timeout: float = 2.0):
        """
        Belirli bir türde ve içerikte mesaj bekler. Başarısız olursa hata verir.
        """
        message = await self.expect_message(timeout)
        assert message.get("type") == expected_type
        if expected_payload:
            # Gelen mesajın, beklenen payload'u içerdiğini kontrol et
            assert all(item in message.items() for item in expected_payload.items())