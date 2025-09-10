# app/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json
from typing import List

app = FastAPI()

# Basit in-memory state
connected_players: List[WebSocket] = []
player_ids: List[str] = []  # ["P1", "P2", "P3", "P4"]
turn_index: int = 0
game_started: bool = False


@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: str):
    global connected_players, player_ids, turn_index, game_started

    await websocket.accept()

    # Oyuncu kimliği belirle
    connected_players.append(websocket)
    player_ids.append(player_id)

    # Oyuncuya kendi initial_state gönder
    await websocket.send_text(json.dumps({
        "type": "initial_state",
        "player_id": player_id
    }))

    # Diğer oyunculara player_connected bildir
    for other_ws, other_id in zip(connected_players, player_ids):
        if other_id != player_id:
            await other_ws.send_text(json.dumps({
                "type": "player_connected",
                "player_id": player_id
            }))

    # Eğer 4. oyuncu bağlandıysa oyunu başlat
    if len(connected_players) == 4 and not game_started:
        game_started = True
        for ws in connected_players:
            await ws.send_text(json.dumps({
                "type": "game_started"
            }))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "move":
                # Sıra kimdeyse o oyuncudan gelen hamleyi tümüne yayınla
                current_player = player_ids[turn_index]
                if msg.get("player_id") == current_player:
                    turn_index = (turn_index + 1) % len(player_ids)
                    next_player = player_ids[turn_index]

                    for ws in connected_players:
                        await ws.send_text(json.dumps({
                            "type": "game_update",
                            "move": f"{msg['player_id']} -> {msg['move']}",
                            "next": next_player
                        }))
    except WebSocketDisconnect:
        if player_id in player_ids:
            idx = player_ids.index(player_id)
            del connected_players[idx]
            del player_ids[idx]

            # Diğer oyunculara bildir
            for ws in connected_players:
                await ws.send_text(json.dumps({
                    "type": "player_disconnected",
                    "player_id": player_id
                }))
