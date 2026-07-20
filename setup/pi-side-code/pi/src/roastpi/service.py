"""Roast service core for fake and real hardware runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import time
from typing import Protocol

from roastpi.config import AppConfig
from roastpi.hardware.fake import FakeHardware
from roastpi.hardware.real import RealHardware
from roastpi.heat import (
    HeatPlan,
    TimedHeatSetting,
    active_heat_setting_for_elapsed,
    actual_accumulated_heat_percent,
    heat_setting_to_output_voltage,
    requested_heat_percent_to_heat_plan,
)
from roastpi.protocol import DataSnapshot, RoastEventCommand, SetFanCommand, SetHeatCommand
from roastpi.logging_setup import RoastFileLogger
from roastpi.state import (
    LOST_ARTISAN_TIMEOUT_SECONDS,
    CommandStatus,
    CommandResult,
    RoastState,
    RoastStateMachine,
)


@dataclass
class FakeClock:
    now_seconds: float = 0.0

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be greater than or equal to zero")
        self.now_seconds += seconds


@dataclass
class MonotonicClock:
    started_at_seconds: float = field(default_factory=time.monotonic)

    @property
    def now_seconds(self) -> float:
        return time.monotonic() - self.started_at_seconds


class ThermocoupleInput(Protocol):
    def read(self):
        """Read one BT sample from the thermocouple path."""


class OutputDriver(Protocol):
    def apply_output(
        self,
        *,
        heat_setting: int,
        heat_voltage: float,
        fan_setting: int,
        reason: str,
    ) -> None:
        """Apply one complete heat/fan output state."""


class HardwareBundle(Protocol):
    thermocouple: ThermocoupleInput
    output: OutputDriver

    def start(self) -> None:
        """Start hardware resources."""

    def stop(self) -> None:
        """Stop hardware resources."""


@dataclass
class ServiceCore:
    config: AppConfig
    hardware: HardwareBundle
    mode: str = "fake"
    clock: FakeClock | MonotonicClock = field(default_factory=FakeClock)
    state_machine: RoastStateMachine = field(default_factory=RoastStateMachine)
    running: bool = False
    log_entries: list[str] = field(default_factory=list)
    current_heat_plan: HeatPlan | None = None
    heat_window_started_at_seconds: float = 0.0
    actual_accumulated_heat_percent: float = 0.0
    low_heat_setting: int = 1
    high_heat_setting: int = 1
    file_logger: RoastFileLogger | None = None
    summary_logged_for_current_window: bool = False
    last_output_heat_setting: int = 1
    last_output_changed_at_seconds: float = 0.0
    heat_since_last_snapshot: list[TimedHeatSetting] = field(default_factory=list)

    def start(self) -> None:
        self.hardware.start()
        self.running = True
        self._log_service(f"startup {self.mode} service", event="startup", mode=self.mode)
        self.sample_sensor()
        self.apply_standby_outputs("startup")

    def stop(self) -> None:
        self.apply_standby_outputs("shutdown")
        self.hardware.stop()
        self.running = False
        self._log_service(f"shutdown {self.mode} service", event="shutdown", mode=self.mode)

    def connect_artisan(self) -> None:
        self.state_machine.connect(self.clock.now_seconds)
        self._log_service("artisan connected", event="client_connect")

    def disconnect_artisan(self) -> None:
        self.state_machine.disconnect(self.clock.now_seconds)
        self._log_service("artisan disconnected", event="client_disconnect")

    def handle_command(
        self,
        command: SetHeatCommand | SetFanCommand | RoastEventCommand,
    ) -> CommandResult:
        result = self.state_machine.handle_command(command, self.clock.now_seconds)
        self._log_roast(
            f"command {result.command} {result.status.value}"
            + (f" error={result.error}" if result.error else ""),
            event="command",
            command=result.command,
            status=result.status.value,
            error=result.error,
        )
        if result.accepted:
            self._after_accepted_command(command)
        return result

    def tick(self) -> None:
        previous_state = self.state_machine.state
        self.state_machine.tick(self.clock.now_seconds)
        if previous_state != self.state_machine.state:
            self._log_roast(
                f"state {previous_state.value}->{self.state_machine.state.value}",
                event="state_transition",
                previous_state=previous_state.value,
                state=self.state_machine.state.value,
            )
        if self.state_machine.state in {
            RoastState.ROASTING,
            RoastState.LOST_ARTISAN_GRACE,
        }:
            self.apply_active_heat_output("tick")
        elif (
            self.state_machine.state == RoastState.STANDBY
            and previous_state != RoastState.STANDBY
        ):
            self.apply_standby_outputs("standby")

    def sample_sensor(self) -> None:
        reading = self.hardware.thermocouple.read()
        self.state_machine.update_sensor(reading.status, reading.bt_celsius)
        self._log_roast(
            f"sensor {reading.status.value}",
            event="sensor",
            sensor_status=reading.status.value,
            bt=reading.bt_celsius,
        )

    def build_snapshot(self) -> DataSnapshot:
        self._update_actual_heat_since_last_snapshot()
        return DataSnapshot(
            bt=self.state_machine.bt_celsius,
            requested_heat_percent=self.state_machine.requested_heat_percent,
            actual_accumulated_heat_percent=self.actual_accumulated_heat_percent,
            low_heat_setting=self.low_heat_setting,
            high_heat_setting=self.high_heat_setting,
            fan_setting=self.state_machine.fan_setting,
            state=self.state_machine.state.value,
            sensor_status=self.state_machine.sensor_status.value,
            control_status=self.state_machine.control_status,
            last_command=self.state_machine.last_command,
            last_command_status=self.state_machine.last_command_status,
            last_error=self.state_machine.last_error,
        )

    def record_protocol_error(self, error: str) -> None:
        self.state_machine.last_command = "protocol"
        self.state_machine.last_command_status = CommandStatus.REJECTED.value
        self.state_machine.last_error = error
        self._log_service(
            f"protocol rejected error={error}",
            event="protocol_error",
            error=error,
        )

    def apply_standby_outputs(self, reason: str) -> None:
        self.current_heat_plan = requested_heat_percent_to_heat_plan(
            0.0,
            self.config.heat_control,
        )
        self.low_heat_setting = 1
        self.high_heat_setting = 1
        self.actual_accumulated_heat_percent = 0.0
        self.summary_logged_for_current_window = False
        self._apply_output(
            heat_setting=1,
            heat_voltage=heat_setting_to_output_voltage(1, self.config.heat_control),
            fan_setting=100,
            reason=reason,
        )
        self._reset_actual_heat_reporting(1)
        self._log_roast(
            "output standby heat_setting=1 fan_setting=100",
            event="output",
            mode="standby",
            heat_setting=1,
            heat_voltage=heat_setting_to_output_voltage(1, self.config.heat_control),
            fan_setting=100,
            reason=reason,
        )

    def _apply_output(
        self,
        *,
        heat_setting: int,
        heat_voltage: float,
        fan_setting: int,
        reason: str,
    ) -> None:
        self._record_heat_interval_before_output_change(heat_setting)
        self.hardware.output.apply_output(
            heat_setting=heat_setting,
            heat_voltage=heat_voltage,
            fan_setting=fan_setting,
            reason=reason,
        )

    def apply_active_heat_output(self, reason: str) -> None:
        if self.current_heat_plan is None:
            self._set_heat_plan(self.state_machine.requested_heat_percent)
        assert self.current_heat_plan is not None

        elapsed = self.clock.now_seconds - self.heat_window_started_at_seconds
        completed_window = False
        if elapsed >= self.config.heat_control.control_window_seconds:
            completed_window = True
            self._update_actual_accumulated_heat(
                self.config.heat_control.control_window_seconds
            )
            completed_windows = math.floor(
                elapsed / self.config.heat_control.control_window_seconds
            )
            self.heat_window_started_at_seconds += (
                completed_windows * self.config.heat_control.control_window_seconds
            )
            elapsed = self.clock.now_seconds - self.heat_window_started_at_seconds
            self.summary_logged_for_current_window = False

        active_setting = active_heat_setting_for_elapsed(
            self.current_heat_plan,
            elapsed,
            self.config.heat_control.control_window_seconds,
        )
        active_voltage = heat_setting_to_output_voltage(
            active_setting,
            self.config.heat_control,
        )
        if not completed_window or elapsed > 0:
            self._update_actual_accumulated_heat(elapsed)
        self._apply_output(
            heat_setting=active_setting,
            heat_voltage=active_voltage,
            fan_setting=self.state_machine.fan_setting,
            reason=reason,
        )
        if completed_window:
            self._record_completed_window_summary(active_setting, active_voltage, reason)
        else:
            self._record_output_summary(active_setting, active_voltage, reason)

    def _after_accepted_command(
        self,
        command: SetHeatCommand | SetFanCommand | RoastEventCommand,
    ) -> None:
        if isinstance(command, SetHeatCommand):
            self._set_heat_plan(command.requested_heat_percent)
            self.apply_active_heat_output("setHeat")
            return
        if isinstance(command, SetFanCommand):
            self.apply_active_heat_output("setFan")
            return
        if command.event == "CHARGE":
            self._set_heat_plan(self.state_machine.requested_heat_percent)
            self.apply_active_heat_output("CHARGE")
        elif command.event in {"DROP", "OFF"}:
            self.apply_standby_outputs(command.event)

    def _set_heat_plan(self, requested_heat_percent: float) -> None:
        self.current_heat_plan = requested_heat_percent_to_heat_plan(
            requested_heat_percent,
            self.config.heat_control,
        )
        self.low_heat_setting = self.current_heat_plan.low_heat_setting
        self.high_heat_setting = self.current_heat_plan.high_heat_setting
        self.heat_window_started_at_seconds = self.clock.now_seconds
        self.actual_accumulated_heat_percent = 0.0
        self._log_roast(
            "heat_plan "
            f"requested_heat_percent={requested_heat_percent} "
            f"low={self.low_heat_setting} high={self.high_heat_setting} "
            f"duty={self.current_heat_plan.pwm_duty_ratio:.3f}",
            event="heat_plan",
            requested_heat_percent=requested_heat_percent,
            low_heat_setting=self.low_heat_setting,
            high_heat_setting=self.high_heat_setting,
            pwm_duty_ratio=self.current_heat_plan.pwm_duty_ratio,
        )

    def _record_heat_interval_before_output_change(
        self,
        next_heat_setting: int,
    ) -> None:
        now = self.clock.now_seconds
        if next_heat_setting == self.last_output_heat_setting:
            return
        duration = now - self.last_output_changed_at_seconds
        if duration > 0:
            self.heat_since_last_snapshot.append(
                TimedHeatSetting(
                    heat_setting=self.last_output_heat_setting,
                    duration_seconds=duration,
                )
            )
        self.last_output_heat_setting = next_heat_setting
        self.last_output_changed_at_seconds = now

    def _update_actual_heat_since_last_snapshot(self) -> None:
        now = self.clock.now_seconds
        duration = now - self.last_output_changed_at_seconds
        timed_settings = list(self.heat_since_last_snapshot)
        if duration > 0:
            timed_settings.append(
                TimedHeatSetting(
                    heat_setting=self.last_output_heat_setting,
                    duration_seconds=duration,
                )
            )
        if timed_settings:
            self.actual_accumulated_heat_percent = actual_accumulated_heat_percent(
                tuple(timed_settings),
                self.config.heat_control,
            )
        else:
            self.actual_accumulated_heat_percent = 0.0
        self.heat_since_last_snapshot.clear()
        self.last_output_changed_at_seconds = now

    def _reset_actual_heat_reporting(self, heat_setting: int) -> None:
        self.heat_since_last_snapshot.clear()
        self.last_output_heat_setting = heat_setting
        self.last_output_changed_at_seconds = self.clock.now_seconds
        self.actual_accumulated_heat_percent = 0.0

    def _update_actual_accumulated_heat(self, elapsed_seconds: float) -> None:
        if self.current_heat_plan is None or elapsed_seconds <= 0:
            self.actual_accumulated_heat_percent = 0.0
            return

        bounded_elapsed = min(
            elapsed_seconds,
            self.config.heat_control.control_window_seconds,
        )
        high_duration = min(
            self.current_heat_plan.pwm_duty_ratio
            * self.config.heat_control.control_window_seconds,
            bounded_elapsed,
        )
        low_duration = bounded_elapsed - high_duration
        timed_settings = []
        if high_duration > 0:
            timed_settings.append(
                TimedHeatSetting(
                    heat_setting=self.current_heat_plan.high_heat_setting,
                    duration_seconds=high_duration,
                )
            )
        if low_duration > 0:
            timed_settings.append(
                TimedHeatSetting(
                    heat_setting=self.current_heat_plan.low_heat_setting,
                    duration_seconds=low_duration,
                )
            )
        if not timed_settings:
            self.actual_accumulated_heat_percent = 0.0
            return

        self.actual_accumulated_heat_percent = actual_accumulated_heat_percent(
            tuple(timed_settings),
            self.config.heat_control,
        )

    def _record_output_summary(
        self,
        active_setting: int,
        active_voltage: float,
        reason: str,
    ) -> None:
        message = (
            f"output active heat_setting={active_setting} "
            f"fan_setting={self.state_machine.fan_setting}"
        )
        self.log_entries.append(message)
        if self.file_logger is None:
            return
        if reason != "tick":
            self.file_logger.roast_event(
                self.clock.now_seconds,
                "output",
                mode="active",
                heat_setting=active_setting,
                heat_voltage=active_voltage,
                fan_setting=self.state_machine.fan_setting,
                reason=reason,
            )
            return
        elapsed = self.clock.now_seconds - self.heat_window_started_at_seconds
        if (
            elapsed < self.config.heat_control.control_window_seconds
            or self.summary_logged_for_current_window
        ):
            return
        self.file_logger.summary(
            self.clock.now_seconds,
            requested_heat_percent=self.state_machine.requested_heat_percent,
            actual_accumulated_heat_percent=self.actual_accumulated_heat_percent,
            active_heat_setting=active_setting,
            low_heat_setting=self.low_heat_setting,
            high_heat_setting=self.high_heat_setting,
            fan_setting=self.state_machine.fan_setting,
            sensor_status=self.state_machine.sensor_status.value,
            state=self.state_machine.state.value,
        )
        self.summary_logged_for_current_window = True

    def _record_completed_window_summary(
        self,
        active_setting: int,
        active_voltage: float,
        reason: str,
    ) -> None:
        if self.file_logger is None or self.summary_logged_for_current_window:
            return
        self.file_logger.summary(
            self.clock.now_seconds,
            requested_heat_percent=self.state_machine.requested_heat_percent,
            actual_accumulated_heat_percent=self._current_plan_average_heat_percent(),
            active_heat_setting=active_setting,
            low_heat_setting=self.low_heat_setting,
            high_heat_setting=self.high_heat_setting,
            fan_setting=self.state_machine.fan_setting,
            sensor_status=self.state_machine.sensor_status.value,
            state=self.state_machine.state.value,
        )
        self.summary_logged_for_current_window = True

    def _current_plan_average_heat_percent(self) -> float:
        if self.current_heat_plan is None:
            return 0.0
        high_duration = (
            self.current_heat_plan.pwm_duty_ratio
            * self.config.heat_control.control_window_seconds
        )
        low_duration = self.config.heat_control.control_window_seconds - high_duration
        timed_settings = []
        if high_duration > 0:
            timed_settings.append(
                TimedHeatSetting(
                    heat_setting=self.current_heat_plan.high_heat_setting,
                    duration_seconds=high_duration,
                )
            )
        if low_duration > 0:
            timed_settings.append(
                TimedHeatSetting(
                    heat_setting=self.current_heat_plan.low_heat_setting,
                    duration_seconds=low_duration,
                )
            )
        if not timed_settings:
            return 0.0
        return actual_accumulated_heat_percent(
            tuple(timed_settings),
            self.config.heat_control,
        )

    def _log_service(self, message: str, event: str, **fields: object) -> None:
        self.log_entries.append(message)
        if self.file_logger is not None:
            self.file_logger.service_event(self.clock.now_seconds, event, **fields)

    def _log_roast(self, message: str, event: str, **fields: object) -> None:
        self.log_entries.append(message)
        if self.file_logger is not None:
            self.file_logger.roast_event(self.clock.now_seconds, event, **fields)


def create_fake_service(
    config: AppConfig,
    *,
    log_dir: Path | None = None,
    session_id: str = "fake-session",
    retention_count: int = 5,
) -> ServiceCore:
    file_logger = None
    if log_dir is not None:
        file_logger = RoastFileLogger(
            log_dir=log_dir,
            session_id=session_id,
            retention_count=retention_count,
        )
    return ServiceCore(
        config=config,
        hardware=FakeHardware(),
        mode="fake",
        file_logger=file_logger,
    )


def create_real_service(
    config: AppConfig,
    *,
    log_dir: Path | None = None,
    session_id: str = "real-session",
    retention_count: int = 5,
    hardware: HardwareBundle | None = None,
) -> ServiceCore:
    file_logger = None
    if log_dir is not None:
        file_logger = RoastFileLogger(
            log_dir=log_dir,
            session_id=session_id,
            retention_count=retention_count,
        )
    return ServiceCore(
        config=config,
        hardware=hardware or RealHardware(),
        mode="real",
        clock=MonotonicClock(),
        file_logger=file_logger,
    )
