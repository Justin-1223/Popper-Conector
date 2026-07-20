"""Run the Joe WebSocket server with real Raspberry Pi hardware."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import os
from pathlib import Path
import sys

from tool_bootstrap import add_project_src_to_path

add_project_src_to_path()

from roastpi.config import load_default_config
from roastpi.service import create_real_service
from roastpi.websocket_server import RoastWebSocketServer


async def run_server(
    *,
    host: str,
    port: int,
    path: str,
    log_dir: Path,
    session_id: str,
    pid_file: Path | None,
    tick_seconds: float,
) -> None:
    config = load_default_config()
    service = create_real_service(config, log_dir=log_dir, session_id=session_id)
    service.start()
    server = RoastWebSocketServer(
        config=config,
        service=service,
        host=host,
        port=port,
        path=path,
        background_tick_seconds=tick_seconds,
    )
    await server.start()
    if pid_file is not None:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    print(f"READY ws://{host}:{server.bound_port}{path}", flush=True)
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        raise
    finally:
        await server.stop()
        if pid_file is not None:
            pid_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real-hardware Joe WebSocket server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--path", default="/WebSocket")
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument(
        "--session-id",
        default=f"service-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )
    parser.add_argument("--pid-file", type=Path)
    parser.add_argument("--tick-seconds", type=float, default=0.1)
    args = parser.parse_args(argv)

    try:
        asyncio.run(
            run_server(
                host=args.host,
                port=args.port,
                path=args.path,
                log_dir=args.log_dir,
                session_id=args.session_id,
                pid_file=args.pid_file,
                tick_seconds=args.tick_seconds,
            )
        )
    except KeyboardInterrupt:
        print("STOPPED", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
