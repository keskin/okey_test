# app/main.py
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any

app = FastAPI()

class GameState:
    def __init__(self):
        self.players: Dict[str, WebSocket] = {}
        self.player_order: List[str] = []
        self.turn: str | None = None
        self.game_started: bool = False

    def add_player(self, player_id: str, websocket: WebSocket):
        self.players[player_id] = websocket
        self.player_order.append(player_id)

    def remove_player(self, player_id: str):
        # If the disconnected player had the turn, nullify it so a new player can take over.
        if self.turn == player_id:
            self.turn = None # The turn is now vacant.

        if player_id in self.players:
            del self.players[player_id]
        if player_id in self.player_order:
            self.player_order.remove(player_id)

    def get_player_id_by_websocket(self, websocket: WebSocket) -> str | None:
        for pid, ws in self.players.items():
            if ws == websocket:
                return pid
        return None

    def start_game(self):
        self.game_started = True
        self.turn = self.player_order[0]

    def next_turn(self):
        if not self.turn or not self.player_order:
            self.turn = None
            return
        try:
            current_index = self.player_order.index(self.turn)
            next_index = (current_index + 1) % len(self.player_order)
            self.turn = self.player_order[next_index]
        except ValueError:
            self.turn = self.player_order[0] if self.player_order else None

    def to_dict(self):
        return {
            "players": self.player_order,
            "turn": self.turn,
            "game_started": self.game_started,
        }

class ConnectionManager:
    def __init__(self):
        self.game_state = GameState()
        self.player_counter = 0

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.player_counter += 1
        player_id = f"P{self.player_counter}"

        await self.broadcast(json.dumps({
            "type": "player_connected",
            "player_id": player_id
        }))

        self.game_state.add_player(player_id, websocket)
        await websocket.send_json({
            "type": "initial_state",
            "player_id": player_id,
            "game_state": self.game_state.to_dict()
        })

        # If 4 players connect for the first time, start the game.
        if len(self.game_state.players) == 4 and not self.game_state.game_started:
            self.game_state.start_game()
            await self.broadcast(json.dumps({
                "type": "game_started",
                "turn": self.game_state.turn
            }))
        # If a new player joins a started game and the turn is vacant, give them the turn.
        elif self.game_state.game_started and self.game_state.turn is None:
            self.game_state.turn = player_id
            await self.broadcast(json.dumps({
                "type": "turn_update",
                "turn": self.game_state.turn
            }))


    async def disconnect(self, websocket: WebSocket):
        player_id = self.game_state.get_player_id_by_websocket(websocket)
        if player_id:
            print(f"Player {player_id} disconnecting.")
            self.game_state.remove_player(player_id)
            await self.broadcast(json.dumps({
                "type": "player_disconnected",
                "player_id": player_id
            }))

    async def broadcast(self, message: str):
        websockets = list(self.game_state.players.values())
        if not websockets:
            return
        await asyncio.gather(*(ws.send_text(message) for ws in websockets))

    async def handle_message(self, websocket: WebSocket, data: Dict[str, Any]):
        msg_type = data.get("type")
        player_id = self.game_state.get_player_id_by_websocket(websocket)

        if not player_id:
            return

        if msg_type == "move" and self.game_state.turn == player_id:
            self.game_state.next_turn()
            await self.broadcast(json.dumps({
                "type": "game_update",
                "move": data.get("move"),
                "player_id": player_id,
                "turn": self.game_state.turn
            }))

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await manager.handle_message(websocket, data)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        print(f"Error in websocket endpoint: {e}")
        await manager.disconnect(websocket)
