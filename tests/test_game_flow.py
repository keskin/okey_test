# tests/test_game_flow.py (Updated with custom sync using Lock and Event instead of Barrier)

import pytest
import anyio
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
import json

# Helper to receive and assert message type and content
async def receive_and_assert(ws, expected_type, expected_content=None):
    """
    Receives a JSON message, asserts type, and optionally specific content.
    """
    data = await ws.receive_json()
    assert data["type"] == expected_type
    if expected_content:
        for key, value in expected_content.items():
            assert data.get(key) == value
    return data

# Helper to send message
async def send_message(ws, message_type, content=None):
    msg = {"type": message_type}
    if content:
        msg.update(content)
    await ws.send_json(msg)

# Modular task for a player: connect, receive initial, handle notifications, etc.
async def player_task(app, player_id, events, lock=None, event=None, counter=None):
    """
    Simulates a player's behavior based on events list.
    events: list of actions like ('receive', type, content), ('send', type, content), ('wait'), ('sync')
    For 'sync': increment counter under lock, set event if count ==4, then await event.wait()
    """
    transport = ASGIWebSocketTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("/ws", client) as ws:
            # Initial state
            await receive_and_assert(ws, "initial_state", {"player_id": player_id})

            for action in events:
                if action[0] == 'receive':
                    await receive_and_assert(ws, action[1], action[2] if len(action) > 2 else None)
                elif action[0] == 'send':
                    await send_message(ws, action[1], action[2] if len(action) > 2 else None)
                elif action[0] == 'wait':
                    await anyio.sleep(0.1)  # Small delay to allow other tasks to progress
                elif action[0] == 'sync' and lock and event and counter:
                    async with lock:
                        counter[0] += 1
                        if counter[0] == 4:
                            event.set()
                    await event.wait()

# Main test for the full game scenario
@pytest.mark.anyio
async def test_full_game_scenario(app):
    # Create sync primitives for game start synchronization
    lock = anyio.Lock()
    event = anyio.Event()
    counter = [0]  # Mutable counter

    async with anyio.create_task_group() as tg:
        # P1 connects
        tg.start_soon(player_task, app, 1, [
            ('receive', 'player_connected', {'player_id': 2}),
            ('receive', 'player_connected', {'player_id': 3}),
            ('receive', 'player_connected', {'player_id': 4}),
            ('receive', 'game_started'),
            ('sync',),  # Sync after game_started
            ('send', 'make_move'),  # P1 makes move after sync
            ('receive', 'game_update', {'move_by': 1, 'next_turn': 2}),
        ], lock, event, counter)

        # P2 connects after P1
        await anyio.sleep(0.05)  # Ensure order
        tg.start_soon(player_task, app, 2, [
            ('receive', 'player_connected', {'player_id': 3}),
            ('receive', 'player_connected', {'player_id': 4}),
            ('receive', 'game_started'),
            ('sync',),  # Sync after game_started
            ('receive', 'game_update', {'move_by': 1, 'next_turn': 2}),
        ], lock, event, counter)

        # P3
        await anyio.sleep(0.05)
        tg.start_soon(player_task, app, 3, [
            ('receive', 'player_connected', {'player_id': 4}),
            ('receive', 'game_started'),
            ('sync',),  # Sync after game_started
            ('receive', 'game_update', {'move_by': 1, 'next_turn': 2}),
        ], lock, event, counter)

        # P4
        await anyio.sleep(0.05)
        tg.start_soon(player_task, app, 4, [
            ('receive', 'game_started'),
            ('sync',),  # Sync after game_started
            ('receive', 'game_update', {'move_by': 1, 'next_turn': 2}),
        ], lock, event, counter)