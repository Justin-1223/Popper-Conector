"""Runtime lifecycle and pure roast state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from roastpi.protocol import RoastEventCommand, SetFanCommand, SetHeatCommand


@dataclass
class RuntimeState:
    mode: str
    lifecycle: str = "created"
    events: list[str] = field(default_factory=list)

    def mark_started(self) -> None:
        self.lifecycle = "running"
        self.events.append("started")

    def mark_stopped(self) -> None:
        self.lifecycle = "stopped"
        self.events.append("stopped")


class RoastState(str, Enum):
    STANDBY = "standby"
    CONNECTED_IDLE = "connected_idle"
    ROASTING = "roasting"
    LOST_ARTISAN_GRACE = "lost_artisan_grace"
    COOLDOWN_OR_DROP = "cooldown_or_drop"
    ENDED = "ended"


class SensorStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    FAULT = "fault"


class CommandStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


LOST_ARTISAN_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    status: CommandStatus
    command: str
    error: str | None = None


@dataclass
class RoastStateMachine:
    state: RoastState = RoastState.STANDBY
    control_status: str = "standby"
    sensor_status: SensorStatus = SensorStatus.MISSING
    bt_celsius: float | None = None
    requested_heat_percent: float = 0.0
    fan_setting: int = 100
    logging_active: bool = False
    connected: bool = False
    lost_artisan_at_seconds: float | None = None
    last_command: str | None = None
    last_command_status: str | None = None
    last_error: str | None = None
    events: list[str] = field(default_factory=list)

    def connect(self, now_seconds: float) -> None:
        self.connected = True
        self.lost_artisan_at_seconds = None
        if self.state in {RoastState.STANDBY, RoastState.ENDED}:
            self.state = RoastState.CONNECTED_IDLE
            self.control_status = "standby"
        elif self.state == RoastState.LOST_ARTISAN_GRACE:
            self.state = RoastState.ROASTING
            self.control_status = "active"
        self.events.append(f"connect:{now_seconds}")

    def disconnect(self, now_seconds: float) -> None:
        self.connected = False
        if self.state == RoastState.ROASTING:
            self.state = RoastState.LOST_ARTISAN_GRACE
            self.control_status = "holding_last_outputs"
            self.lost_artisan_at_seconds = now_seconds
        self.events.append(f"disconnect:{now_seconds}")

    def tick(self, now_seconds: float) -> None:
        if (
            self.state == RoastState.LOST_ARTISAN_GRACE
            and self.lost_artisan_at_seconds is not None
            and now_seconds - self.lost_artisan_at_seconds >= LOST_ARTISAN_TIMEOUT_SECONDS
        ):
            self.state = RoastState.STANDBY
            self.control_status = "standby"
            self.logging_active = False
            self.lost_artisan_at_seconds = None
            self.requested_heat_percent = 0.0
            self.fan_setting = 100
            self.events.append("lost_artisan_timeout")

    def handle_command(
        self,
        command: SetHeatCommand | SetFanCommand | RoastEventCommand,
        now_seconds: float,
    ) -> CommandResult:
        if isinstance(command, SetHeatCommand):
            return self._handle_set_heat(command)
        if isinstance(command, SetFanCommand):
            return self._handle_set_fan(command)
        return self._handle_roast_event(command, now_seconds)

    def update_sensor(self, status: SensorStatus, bt_celsius: float | None) -> None:
        if not isinstance(status, SensorStatus):
            raise ValueError("sensor status must be a SensorStatus")
        if status == SensorStatus.OK and bt_celsius is None:
            raise ValueError("ok sensor status requires a BT value")
        if status != SensorStatus.OK and bt_celsius is not None:
            raise ValueError("faulted or missing sensor must not carry fake BT")
        self.sensor_status = status
        self.bt_celsius = bt_celsius

    def _handle_set_heat(self, command: SetHeatCommand) -> CommandResult:
        if self.state != RoastState.ROASTING:
            return self._reject("setHeat", "not_roasting")
        self.requested_heat_percent = command.requested_heat_percent
        return self._accept("setHeat")

    def _handle_set_fan(self, command: SetFanCommand) -> CommandResult:
        if self.state != RoastState.ROASTING:
            return self._reject("setFan", "not_roasting")
        self.fan_setting = command.fan_setting
        return self._accept("setFan")

    def _handle_roast_event(
        self,
        command: RoastEventCommand,
        now_seconds: float,
    ) -> CommandResult:
        if command.event == "CHARGE":
            if self.state not in {RoastState.CONNECTED_IDLE, RoastState.STANDBY, RoastState.ENDED}:
                return self._reject("roastEvent", "charge_not_allowed")
            self.state = RoastState.ROASTING
            self.control_status = "active"
            self.logging_active = True
            self.lost_artisan_at_seconds = None
            self.events.append(f"CHARGE:{now_seconds}")
            return self._accept("roastEvent")

        if command.event == "DROP":
            if self.state not in {RoastState.ROASTING, RoastState.LOST_ARTISAN_GRACE}:
                return self._reject("roastEvent", "drop_not_allowed")
            self.state = RoastState.COOLDOWN_OR_DROP
            self.control_status = "standby"
            self.requested_heat_percent = 0.0
            self.fan_setting = 100
            self.lost_artisan_at_seconds = None
            self.events.append(f"DROP:{now_seconds}")
            return self._accept("roastEvent")

        if command.event == "OFF":
            self.state = RoastState.ENDED
            self.control_status = "standby"
            self.logging_active = False
            self.requested_heat_percent = 0.0
            self.fan_setting = 100
            self.lost_artisan_at_seconds = None
            self.events.append(f"OFF:{now_seconds}")
            return self._accept("roastEvent")

        return self._reject("roastEvent", "unknown_event")

    def _accept(self, command: str) -> CommandResult:
        self.last_command = command
        self.last_command_status = CommandStatus.ACCEPTED.value
        self.last_error = None
        return CommandResult(True, CommandStatus.ACCEPTED, command)

    def _reject(self, command: str, error: str) -> CommandResult:
        self.last_command = command
        self.last_command_status = CommandStatus.REJECTED.value
        self.last_error = error
        return CommandResult(False, CommandStatus.REJECTED, command, error)
