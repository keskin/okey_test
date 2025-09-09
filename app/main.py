# app/main.py (Updated)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json

app = FastAPI()

# Global state for simplicity in this minimal simulation
connected_clients = {}  # websocket: player_id
player_counter = 0

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    global player_counter
    player_counter += 1
    player_id = player_counter
    connected_clients[websocket] = player_id

    # Send initial_state to the new player
    await websocket.send_json({"type": "initial_state", "player_id": player_id})

    # Notify existing players about the new connection
    for client, pid in list(connected_clients.items()):
        if client != websocket:
            await client.send_json({"type": "player_connected", "player_id": player_id})

    # If 4 players connected, send game_started to all
    if len(connected_clients) == 4:
        for client in list(connected_clients.keys()):
            await client.send_json({"type": "game_started"})

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "make_move":
                # Simulate move: assume it's P1's turn first, but for simplicity, just broadcast update
                # In a real game, you'd check turns, but here we simulate the scenario where P1 makes a move
                # and next turn is P2
                move_by = player_id
                next_turn = (player_id % 4) + 1  # Cycle to next player, but for scenario, assume after P1 -> P2
                update_msg = {
                    "type": "game_update",
                    "move_by": move_by,
                    "next_turn": next_turn
                }
                # Broadcast to all
                for client in list(connected_clients.keys()):
                    await client.send_json(update_msg)

    except WebSocketDisconnect:
        del connected_clients[websocket]
        print(f"Player {player_id} disconnected")
    except Exception as e:
        print(f"Error: {e}")
        if websocket in connected_clients:
            del connected_clients[websocket]