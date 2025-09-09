# tests/test_disconnect_reconnect_flow.py
import pytest
import anyio
import json
from typing import List, Dict, Any
from httpx import AsyncClient
from httpx_ws import aconnect_ws, WebSocketDisconnect
from httpx_ws.transport import ASGIWebSocketTransport

# A client that connects, plays, and stays until the end
async def player_lifecycle(app, player_id, messages, events, moves):
    transport = ASGIWebSocketTransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws", client) as ws:
                messages.append(await ws.receive_json()) # initial_state
                events[f"{player_id}_connected"].set()

                while True:
                    async with anyio.move_on_after(5) as scope:
                        msg = await ws.receive_json()
                        messages.append(msg)

                        is_our_turn = (
                            (msg.get("type") in ("game_started", "turn_update")) and msg.get("turn") == player_id
                        ) or (
                            (msg.get("type") == "game_update") and msg.get("turn") == player_id
                        )
                        if is_our_turn:
                            await ws.send_json({"type": "move", "player_id": player_id, "move": moves[player_id]})
                            if player_id == "P1":
                                events["P1_made_move"].set()

                        # Exit condition for the full test
                        if msg.get("type") == "game_update" and msg.get("player_id") == "P5":
                            break
                    if scope.cancelled_caught:
                        break
    except Exception as e:
        messages.append({"type": "error", "detail": str(e)})
    finally:
        if f"{player_id}_finished" in events:
            events[f"{player_id}_finished"].set()

# A client that connects and is told when to disconnect
async def disconnecting_player_lifecycle(app, player_id, messages, events):
    transport = ASGIWebSocketTransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws", client) as ws:
                messages.append(await ws.receive_json()) # initial_state
                events[f"{player_id}_connected"].set()

                await events["P1_made_move"].wait()
                await ws.close()
    except WebSocketDisconnect:
        messages.append({"type": "self_disconnected"})
    except Exception as e:
        messages.append({"type": "error", "detail": str(e)})
    finally:
        if f"{player_id}_finished" in events:
            events[f"{player_id}_finished"].set()

@pytest.mark.anyio
async def test_disconnect_and_reconnect_flow(app, monkeypatch):
    from app.main import manager
    monkeypatch.setattr(manager, "game_state", type(manager.game_state)())
    monkeypatch.setattr(manager, "player_counter", 0)

    all_messages = {f"P{i}": [] for i in range(1, 6)}
    pids = ["P1", "P2", "P3", "P4", "P5"]
    events = {
        **{f"{pid}_connected": anyio.Event() for pid in pids},
        **{f"{pid}_finished": anyio.Event() for pid in pids},
        "P1_made_move": anyio.Event(),
    }
    moves = {"P1": "e4", "P5": "d4"}

    async with anyio.create_task_group() as tg:
        tg.start_soon(player_lifecycle, app, "P1", all_messages["P1"], events, moves)
        tg.start_soon(disconnecting_player_lifecycle, app, "P2", all_messages["P2"], events)
        tg.start_soon(player_lifecycle, app, "P3", all_messages["P3"], events, moves)
        tg.start_soon(player_lifecycle, app, "P4", all_messages["P4"], events, moves)

        for i in range(1, 5): await events[f"P{i}_connected"].wait()

        await events["P1_made_move"].wait()
        await events["P2_finished"].wait()

        tg.start_soon(player_lifecycle, app, "P5", all_messages["P5"], events, moves)
        await events["P5_connected"].wait()

        for p_id in ["P1", "P3", "P4", "P5"]:
            await events[f"{p_id}_finished"].wait()

    # --- ASSERTIONS ---
    for p_id in ["P1", "P3", "P4"]:
        messages = all_messages[p_id]
        assert any(m.get("type") == "player_disconnected" and m.get("player_id") == "P2" for m in messages), f"P{p_id} did not see P2 disconnect"
        assert any(m.get("type") == "player_connected" and m.get("player_id") == "P5" for m in messages), f"P{p_id} did not see P5 connect"
        assert any(m.get("type") == "game_update" and m.get("player_id") == "P5" for m in messages), f"P{p_id} did not see P5's move"

    assert any(m.get("type") == "self_disconnected" for m in all_messages["P2"])

    p5_messages = all_messages["P5"]
    assert any(m.get("type") == "turn_update" and m.get("turn") == "P5" for m in p5_messages)
    assert any(m.get("type") == "game_update" and m.get("player_id") == "P5" for m in p5_messages)

    last_game_update = [m for m in all_messages["P1"] if m.get("type") == "game_update"][-1]
    assert last_game_update["turn"] == "P3"
