# tests/test_game_flow.py - v4
import pytest
import anyio
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

# Tek istemcili test, doğru transport ile kendi istemcisini oluşturuyor.
@pytest.mark.anyio
async def test_websocket_echo_single_client(app):
    # KRİTİK DEĞİŞİKLİK: ASGIWebSocketTransport kullanılıyor.
    transport = ASGIWebSocketTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("/ws", client) as ws:
            await ws.send_text("hello")
            response = await ws.receive_text()
            assert response == "Echo: hello"

# Yardımcı fonksiyon, doğru transport ile kendi istemcisini yönetiyor.
async def run_websocket_client(app, message: str, expected_response: str):
    """
    Her istemci için tamamen izole bir ortam oluşturur.
    Kendi AsyncClient'ını doğru WebSocket transportu ile yaratır.
    """
    # KRİTİK DEĞİŞİKLİK: ASGIWebSocketTransport kullanılıyor.
    transport = ASGIWebSocketTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("/ws", client) as ws:
            await ws.send_text(message)
            response = await ws.receive_text()
            assert response == expected_response

# Çok istemcili test, her görev için sadece 'app' nesnesini geçiriyor.
@pytest.mark.anyio
async def test_websocket_echo_multiple_clients_correct(app):
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            run_websocket_client, app, "hello 1", "Echo: hello 1"
        )
        tg.start_soon(
            run_websocket_client, app, "hello 2", "Echo: hello 2"
        )
        tg.start_soon(
            run_websocket_client, app, "hello 3", "Echo: hello 3"
        )
        tg.start_soon(
            run_websocket_client, app, "hello 4", "Echo: hello 4"
        )

