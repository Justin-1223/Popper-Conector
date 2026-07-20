"""Service entrypoint and lifecycle container."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from roastpi.config import AppConfig, load_default_config
from roastpi.logging_setup import configure_logging
from roastpi.service import HardwareBundle, ServiceCore, create_fake_service, create_real_service
from roastpi.state import RuntimeState


@dataclass
class RoastPiApp:
    """Lifecycle container for the current service boundary."""

    config: AppConfig
    hardware: HardwareBundle
    state: RuntimeState
    service: ServiceCore
    running: bool = False

    def start(self) -> None:
        self.service.start()
        self.state.mark_started()
        self.running = True

    def stop(self) -> None:
        self.service.stop()
        self.state.mark_stopped()
        self.running = False


def create_app(*, fake: bool = True, config: AppConfig | None = None) -> RoastPiApp:
    """Create the service shell."""
    resolved_config = config or load_default_config()
    service = create_fake_service(resolved_config) if fake else create_real_service(resolved_config)
    return RoastPiApp(
        config=resolved_config,
        hardware=service.hardware,
        state=RuntimeState(mode="fake" if fake else "real"),
        service=service,
    )


def create_app_with_logs(
    *,
    fake: bool = True,
    config: AppConfig | None = None,
    log_dir: Path,
    session_id: str = "fake-session",
) -> RoastPiApp:
    resolved_config = config or load_default_config()
    if fake:
        service = create_fake_service(
            resolved_config,
            log_dir=log_dir,
            session_id=session_id,
        )
    else:
        service = create_real_service(
            resolved_config,
            log_dir=log_dir,
            session_id=session_id,
        )
    return RoastPiApp(
        config=resolved_config,
        hardware=service.hardware,
        state=RuntimeState(mode="fake" if fake else "real"),
        service=service,
    )


def run_fake_smoke() -> None:
    app = create_app(fake=True)
    app.start()
    app.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the RoastPi service shell.")
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Run with fake hardware.",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run with real Raspberry Pi hardware.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Start and stop immediately for smoke testing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)

    if args.fake and args.real:
        raise SystemExit("Choose only one hardware mode: --fake or --real.")
    if not args.fake and not args.real:
        raise SystemExit("Choose a hardware mode: --fake or --real.")

    app = create_app(fake=args.fake)
    app.start()

    if args.smoke:
        app.stop()

    return 0
