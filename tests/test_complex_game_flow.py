# tests/test_complex_game_flow.py
import pytest
import anyio
import json
from typing import List, Dict, Any
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

async def player_client(
    app,
    player_id: str,
    all_messages: Dict[str, List[Any]],
    events: Dict[str, anyio.Event],
    moves: Dict[str, str]
):
    """
    Simulates a single WebSocket client (player) connecting to the game,
    receiving messages, and sending moves.
    """
    all_messages[player_id] = []
    transport = ASGIWebSocketTransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws", client) as ws:
                # 1. Initial connection and receiving initial_state
                initial_state_msg = await ws.receive_json()
                all_messages[player_id].append(initial_state_msg)
                assert initial_state_msg["type"] == "initial_state"
                assert initial_state_msg["player_id"] == player_id

                # Signal that this player is connected and has its initial state
                events[f"{player_id}_connected"].set()

                # 2. Wait for the game to start
                await events["game_started"].wait()

                # Process messages until it's this player's turn or game ends
                while True:
                    msg = await ws.receive_json()
                    all_messages[player_id].append(msg)

                    if msg.get("type") == "game_started":
                        # This is the signal we were waiting for, but we loop to collect all messages
                        pass

                    # It's our turn if the game starts and it's our turn, or if the game is updated and it's our turn.
                    is_our_turn = (
                        msg.get("type") == "game_started" and msg.get("turn") == player_id
                    ) or (
                        msg.get("type") == "game_update" and msg.get("turn") == player_id
                    )

                    if is_our_turn:
                        # It's our turn to make a move
                        await anyio.sleep(0.01) # small delay to allow other clients to process
                        await ws.send_json({
                            "type": "move",
                            "player_id": player_id,
                            "move": moves[player_id]
                        })

                    # A way to end the test gracefully
                    if msg.get("type") == "game_update" and msg.get("player_id") == "P4":
                         break # P4's move is the last one in the test scenario
    except Exception as e:
        print(f"Error in {player_id}: {e}")
        # In case of error, still record it to avoid deadlocks in asserts
        all_messages[player_id].append({"type": "error", "detail": str(e)})


@pytest.mark.anyio
async def test_4_player_game_flow(app, monkeypatch):
    """
    Tests the entire 4-player game scenario from connection to a full round of moves.
    """
    # Reset global state to ensure test isolation
    from app.main import manager
    monkeypatch.setattr(manager, "game_state", type(manager.game_state)())
    monkeypatch.setattr(manager, "player_counter", 0)
    all_messages = {}
    events = {
        "P1_connected": anyio.Event(),
        "P2_connected": anyio.Event(),
        "P3_connected": anyio.Event(),
        "P4_connected": anyio.Event(),
        "game_started": anyio.Event(),
    }
    moves = {
        "P1": "e4",
        "P2": "e5",
        "P3": "Nf3",
        "P4": "Nc6",
    }

    async with anyio.create_task_group() as tg:
        # Start all player clients concurrently
        for i in range(1, 5):
            player_id = f"P{i}"
            tg.start_soon(player_client, app, player_id, all_messages, events, moves)
            # Ensure players connect sequentially for predictable state updates
            await events[f"{player_id}_connected"].wait()

        # Wait for P4 to connect, which should trigger the game_started event from the server
        p4_initial_state = all_messages["P4"][0]
        p4_game_state = p4_initial_state['game_state']
        if len(p4_game_state['players']) == 4:
             # The game_started message is sent right after P4 connects.
             # We can use an event to signal this, but for simplicity, we'll check messages.
             # Let's find the game_started message in P4's received messages.
             # The server will send it, so we just need to wait for it.
             # The player_client task will set the event.

             # A small wait to ensure server has time to broadcast 'game_started'
             await anyio.sleep(0.1)

             # The player clients themselves handle the game_started event.
             # We will set our main test event here to unblock the players.
             events["game_started"].set()

    # --- ASSERTIONS ---
    # Now that the simulation is complete, we can inspect the messages each player received.

    # Expected sequence of events after all connections
    p1_expected_types = ["initial_state", "player_connected", "player_connected", "player_connected", "game_started", "game_update", "game_update", "game_update", "game_update"]
    p2_expected_types = ["initial_state", "player_connected", "player_connected", "game_started", "game_update", "game_update", "game_update", "game_update"]
    p3_expected_types = ["initial_state", "player_connected", "game_started", "game_update", "game_update", "game_update", "game_update"]
    p4_expected_types = ["initial_state", "game_started", "game_update", "game_update", "game_update", "game_update"]

    # Check message counts
    assert len(all_messages["P1"]) == len(p1_expected_types)
    assert len(all_messages["P2"]) == len(p2_expected_types)
    assert len(all_messages["P3"]) == len(p3_expected_types)
    assert len(all_messages["P4"]) == len(p4_expected_types)

    # Check message types
    assert [msg['type'] for msg in all_messages["P1"]] == p1_expected_types
    assert [msg['type'] for msg in all_messages["P2"]] == p2_expected_types
    assert [msg['type'] for msg in all_messages["P3"]] == p3_expected_types
    assert [msg['type'] for msg in all_messages["P4"]] == p4_expected_types

    # Spot check a few critical messages
    # P1 sees P4 connect
    p1_p4_connect_msg = all_messages["P1"][3]
    assert p1_p4_connect_msg['type'] == 'player_connected' and p1_p4_connect_msg['player_id'] == 'P4'

    # Everyone sees the game start with P1's turn
    for i in range(1, 5):
        player_id = f"P{i}"
        game_started_msg = next(m for m in all_messages[player_id] if m['type'] == 'game_started')
        assert game_started_msg['turn'] == 'P1'

    # Everyone sees P1's move and that it's P2's turn next
    for i in range(1, 5):
        player_id = f"P{i}"
        p1_move_update = next(m for m in all_messages[player_id] if m['type'] == 'game_update' and m['player_id'] == 'P1')
        assert p1_move_update['move'] == moves['P1']
        assert p1_move_update['turn'] == 'P2'

    # Everyone sees P4's move and that it's P1's turn next
    for i in range(1, 5):
        player_id = f"P{i}"
        p4_move_update = next(m for m in all_messages[player_id] if m['type'] == 'game_update' and m['player_id'] == 'P4')
        assert p4_move_update['move'] == moves['P4']
        assert p4_move_update['turn'] == 'P1'
