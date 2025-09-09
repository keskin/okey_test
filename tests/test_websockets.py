import pytest
import anyio
from httpx_ws import aconnect_ws

# Testin `pytest-anyio` tarafından yönetileceğini belirtiyoruz.
@pytest.mark.anyio
async def test_websocket_echo_single_client(leaky_client):
    """
    Minimal websocket uygulamasını tek bir istemciyle test eder.
    """
    async with aconnect_ws("/ws", leaky_client) as ws:
        await ws.send_text("hello")
        response = await ws.receive_text()
        assert response == "Echo: hello"


@pytest.mark.anyio
async def test_websocket_echo_multiple_clients(leaky_client):
    """
    Birden fazla istemciyi, anyio'nun görev grubu (TaskGroup) mekanizmasını
    kullanarak eş zamanlı ve kontrollü bir şekilde test eder.
    Bu yöntem, test sonundaki temizlik (teardown) sürecinde yaşanan
    yarış durumunu (race condition) engeller.
    """

    async def run_client(message: str):
        """Tek bir istemci bağlantısını ve testini yöneten yardımcı fonksiyon."""
        async with aconnect_ws("/ws", leaky_client) as ws:
            await ws.send_text(message)
            response = await ws.receive_text()
            assert response == f"Echo: {message}"
        
        # Olay döngüsüne, bu websocket'in kapanış işlemlerini işlemesi için
        # bir şans vererek yarış durumunu engelliyoruz.
        await anyio.sleep(0)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_client, "client 1")
        tg.start_soon(run_client, "client 2")
        tg.start_soon(run_client, "client 3")
        tg.start_soon(run_client, "client 4")

