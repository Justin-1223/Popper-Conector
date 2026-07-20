"""Pi-hosted WebSocket server for Phase 4 fake-runtime tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from roastpi.config import AppConfig
from roastpi.protocol import (
    GetDataRequest,
    ProtocolError,
    build_get_data_response,
    parse_message,
)
from roastpi.service import ServiceCore, create_fake_service


@dataclass
class RoastWebSocketServer:
    config: AppConfig
    service: ServiceCore | None = None
    host: str = "127.0.0.1"
    port: int = 0
    path: str = "/WebSocket"
    background_tick_seconds: float | None = None
    _server: Server | None = field(default=None, init=False)
    _tick_task: asyncio.Task | None = field(default=None, init=False)

    async def start(self) -> None:
        if self.service is None:
            self.service = create_fake_service(self.config)
            self.service.start()
        self._server = await serve(self._handle_client, self.host, self.port)
        if self.background_tick_seconds is not None:
            self._tick_task = asyncio.create_task(self._background_tick())

    async def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.service is not None and self.service.running:
            self.service.stop()

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server is not running")
        return int(self._server.sockets[0].getsockname()[1])

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.bound_port}{self.path}"

    async def _handle_client(self, websocket: ServerConnection) -> None:
        assert self.service is not None
        path = websocket.request.path if websocket.request is not None else ""
        if path != self.path:
            await websocket.close(code=1008, reason="unsupported path")
            return

        self.service.connect_artisan()
        try:
            async for raw_message in websocket:
                response = self.handle_raw_message(raw_message)
                if response is not None:
                    await websocket.send(json.dumps(response))
        except ConnectionClosed:
            pass
        finally:
            self.service.disconnect_artisan()

    def handle_raw_message(self, raw_message: str | bytes) -> dict[str, Any] | None:
        assert self.service is not None
        try:
            message = parse_message(raw_message)
        except ProtocolError as exc:
            self.service.record_protocol_error(str(exc))
            return None

        if isinstance(message, GetDataRequest):
            self.service.sample_sensor()
            self.service.tick()
            return build_get_data_response(message.id, self.service.build_snapshot())

        self.service.handle_command(message)
        return None

    async def _background_tick(self) -> None:
        assert self.service is not None
        assert self.background_tick_seconds is not None
        while True:
            await asyncio.sleep(self.background_tick_seconds)
            self.service.tick()
