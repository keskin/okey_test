# tests/utils/game_client.py
import asyncio
import json
import os
import warnings
from typing import Any, Optional, Dict

# optional uvloop for WSL2 stability (best effort)
try:
    if os.path.exists("/proc/version"):
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
            ver = f.read().lower()
        if "microsoft" in ver:  # WSL detected
            try:
                import uvloop  # type: ignore
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())  # best-effort
            except Exception as e:
                warnings.warn("uvloop import failed (WSL fallback). Continuing without uvloop: " + repr(e))
except Exception:
    # be very defensive: do not fail module import
    pass

import httpx
from httpx_ws import aconnect_ws, AsyncWebSocketSession
from httpx_ws.transport import ASGIWebSocketTransport


class GameClient:
    """
    Background-task based GameClient for tests.

    - connect() -> returns initial_state dict (or raises)
    - send(dict) -> queues a message to be sent by background writer
    - recv(timeout=None) -> awaits next incoming message dict from server
    - close() -> requests background task to stop and waits for graceful shutdown

    This design guarantees:
    - All httpx / httpx-ws context managers are opened/closed inside the same background task.
    - Main test task never calls WebSocket methods directly (avoids cancel-scope issues).
    - Timeouts / shields protect against WSL2-specific blocking behavior.
    """

    def __init__(
        self,
        app: Any,
        player_id: str,
        ws_path: str = "/ws",
        recv_timeout: float = 5.0,
        send_timeout: float = 5.0,
        startup_timeout: float = 5.0,
    ):
        self._app = app
        self.player_id = player_id
        self.ws_path = ws_path.rstrip("/")
        self.recv_timeout = float(recv_timeout)
        self.send_timeout = float(send_timeout)
        self.startup_timeout = float(startup_timeout)

        # background task & runtime objects (owned & used by background task)
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._ws: Optional[AsyncWebSocketSession] = None

        # queues/events for communication between test task and background task
        self._send_q: asyncio.Queue[Dict] = asyncio.Queue()
        self._recv_q: asyncio.Queue[Dict] = asyncio.Queue()
        self._stop_ev: asyncio.Event = asyncio.Event()
        self._initial_fut: Optional[asyncio.Future] = None

        # closed flag
        self._closed: bool = False

    # ---------------------------
    # Public API
    # ---------------------------
    async def connect(self, timeout: Optional[float] = None) -> Dict:
        """
        Start the background task and return the server's initial_state message (dict).
        Raises exception if background task fails to connect.
        """
        if self._task is not None:
            raise RuntimeError("GameClient already connected")

        loop = asyncio.get_running_loop()
        # future that will carry the initial_state or an exception
        self._initial_fut = loop.create_future()

        # spawn background task
        self._task = loop.create_task(self._run())

        # wait for initial_state (or exception) from background task
        wait_t = timeout if timeout is not None else self.startup_timeout
        try:
            result = await asyncio.wait_for(self._initial_fut, timeout=wait_t)
            if isinstance(result, dict):
                return result
            else:
                # defensive: if background provided non-dict, wrap or raise
                return dict(result)  # type: ignore
        except Exception:
            # if the task already finished with error, re-raise that
            if self._task.done():
                exc = self._task.exception()
                if exc is not None:
                    raise exc
            raise

    async def send(self, message: Dict, timeout: Optional[float] = None) -> None:
        """
        Queue a message to be sent by the background writer.
        Will raise if client was closed.
        """
        if self._closed:
            raise RuntimeError("GameClient is closed; cannot send")

        # put into queue (no blocking, but use wait_for if you want)
        if timeout is None:
            await self._send_q.put(message)
        else:
            await asyncio.wait_for(self._send_q.put(message), timeout=timeout)

    async def recv(self, timeout: Optional[float] = None) -> Dict:
        """
        Receive the next message from server (as dict).
        timeout = None means wait forever.
        """
        if timeout is None:
            msg = await self._recv_q.get()
            return msg
        else:
            return await asyncio.wait_for(self._recv_q.get(), timeout=timeout)

    async def close(self, wait_timeout: float = 5.0) -> None:
        """
        Request graceful shutdown of the background task and wait for it.
        Safe to call multiple times.
        """
        if self._task is None:
            # nothing to do
            self._closed = True
            return

        # signal stop to background task
        try:
            self._stop_ev.set()
        except Exception:
            pass

        # wait for background task to finish
        try:
            await asyncio.wait_for(self._task, timeout=wait_timeout)
        except asyncio.TimeoutError:
            # if it blocks, cancel the task as last resort
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except Exception:
                    pass
        finally:
            # cleanup internal state
            self._task = None
            self._client = None
            self._ws = None
            self._closed = True

    # ---------------------------
    # Background task
    # ---------------------------
    async def _run(self) -> None:
        """
        Runs in a background task. Opens AsyncClient and websocket context managers
        and runs reader/writer loops. Ensures that open/close happen in same task.
        """
        try:
            transport = ASGIWebSocketTransport(app=self._app)
            # Use http scheme for httpx streaming calls (ASGI transport handles it)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                async with aconnect_ws(f"{self.ws_path}/{self.player_id}", client) as ws:
                    # store runtime objects (only for diagnostic; main thread never calls ws.*)
                    self._client = client
                    self._ws = ws

                    # spawn reader/writer
                    reader = asyncio.create_task(self._reader_loop())
                    writer = asyncio.create_task(self._writer_loop())

                    # wait for stop event (shielded so external cancellation doesn't interrupt shutdown)
                    try:
                        await asyncio.shield(self._stop_ev.wait())
                    finally:
                        # cancel reader/writer and wait for them to finish
                        for t in (reader, writer):
                            t.cancel()
                        await asyncio.gather(reader, writer, return_exceptions=True)

        except Exception as exc:
            # If initial handshake failed, set exception on initial future so connect() fails fast.
            if self._initial_fut is not None and not self._initial_fut.done():
                try:
                    self._initial_fut.set_exception(exc)
                except Exception:
                    pass
            # also push an error into recv queue for callers
            try:
                await self._recv_q.put({"type": "error", "error": str(exc)})
            except Exception:
                pass
            # re-raise so upstream (close/wait) notices
            raise
        finally:
            # mark as closed
            self._client = None
            self._ws = None
            # ensure initial future set if not yet (some servers may not send initial_state; handle gracefully)
            if self._initial_fut is not None and not self._initial_fut.done():
                try:
                    # no initial_state came; deliver an explicit error
                    self._initial_fut.set_exception(RuntimeError("WebSocket closed before initial_state"))
                except Exception:
                    pass

    async def _reader_loop(self) -> None:
        """
        Reads messages from the websocket and pushes them into _recv_q.
        The first 'initial_state' message resolves the _initial_fut for connect().
        Uses timeouts to avoid getting stuck on receive_text() on WSL2.
        """
        if self._ws is None:
            # defensive: nothing to read
            return

        try:
            while True:
                try:
                    text = await asyncio.wait_for(self._ws.receive_text(), timeout=self.recv_timeout)
                except asyncio.TimeoutError:
                    # no data in interval — check stop flag and continue
                    if self._stop_ev.is_set():
                        return
                    continue
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    # push error to recv queue and set initial future if needed
                    if self._initial_fut is not None and not self._initial_fut.done():
                        try:
                            self._initial_fut.set_exception(exc)
                        except Exception:
                            pass
                    await self._recv_q.put({"type": "error", "error": str(exc)})
                    return

                # parse JSON safely
                try:
                    data = json.loads(text)
                except Exception:
                    data = {"type": "raw", "text": text}

                # if first initial_state arrives, set the future
                if self._initial_fut is not None and not self._initial_fut.done() and data.get("type") == "initial_state":
                    try:
                        self._initial_fut.set_result(data)
                    except Exception:
                        pass
                # push to recv queue for test to consume
                await self._recv_q.put(data)

        finally:
            return

    async def _writer_loop(self) -> None:
        """
        Sends messages from _send_q to the websocket.
        Uses a small timeout on queue.get to periodically check the stop flag.
        """
        if self._ws is None:
            return

        try:
            while True:
                try:
                    item = await asyncio.wait_for(self._send_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    # check stop flag and continue
                    if self._stop_ev.is_set():
                        return
                    continue
                except asyncio.CancelledError:
                    return

                # attempt to send with timeout
                try:
                    await asyncio.wait_for(self._ws.send_text(json.dumps(item)), timeout=self.send_timeout)
                except asyncio.TimeoutError:
                    # sending timed out: push an error into recv queue and stop writer
                    await self._recv_q.put({"type": "error", "error": "send timeout"})
                    return
                except Exception as exc:
                    await self._recv_q.put({"type": "error", "error": str(exc)})
                    return

        finally:
            return

    # small convenience properties
    @property
    def is_connected(self) -> bool:
        return self._task is not None and not self._task.done() and not self._closed
