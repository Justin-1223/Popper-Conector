"""Logging setup and Phase 5 file log helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@dataclass(frozen=True)
class LogPaths:
    service_log: Path
    roast_log: Path


@dataclass
class RoastFileLogger:
    log_dir: Path
    session_id: str
    retention_count: int = 5

    def __post_init__(self) -> None:
        if self.retention_count <= 0:
            raise ValueError("retention_count must be greater than zero")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.paths.service_log.touch(exist_ok=True)
        self.paths.roast_log.touch(exist_ok=True)
        self.enforce_retention()

    @property
    def paths(self) -> LogPaths:
        return LogPaths(
            service_log=self.log_dir / f"service-{self.session_id}.jsonl",
            roast_log=self.log_dir / f"roast-{self.session_id}.jsonl",
        )

    def service_event(self, now_seconds: float, event: str, **fields: Any) -> None:
        self._write(self.paths.service_log, now_seconds, event, fields)

    def roast_event(self, now_seconds: float, event: str, **fields: Any) -> None:
        self._write(self.paths.roast_log, now_seconds, event, fields)

    def summary(self, now_seconds: float, **fields: Any) -> None:
        self.roast_event(now_seconds, "summary", **fields)

    def enforce_retention(self) -> None:
        self._prune("service-*.jsonl")
        self._prune("roast-*.jsonl")

    def _write(
        self,
        path: Path,
        now_seconds: float,
        event: str,
        fields: dict[str, Any],
    ) -> None:
        record = {"t": now_seconds, "event": event, **fields}
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, sort_keys=True) + "\n")

    def _prune(self, pattern: str) -> None:
        files = sorted(
            self.log_dir.glob(pattern),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        for path in files[: max(0, len(files) - self.retention_count)]:
            path.unlink()
