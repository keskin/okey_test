#app/main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:    
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")

    except WebSocketDisconnect:
        print("Client disconnected")