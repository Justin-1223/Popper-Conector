"""Fake hardware for tests and local smoke runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from roastpi.state import SensorStatus


@dataclass(frozen=True)
class FakeSensorReading:
    status: SensorStatus
    bt_celsius: float | None


@dataclass(frozen=True)
class FakeOutputAction:
    heat_setting: int
    heat_voltage: float
    fan_setting: int
    reason: str


@dataclass
class FakeThermocouple:
    status: SensorStatus = SensorStatus.MISSING
    bt_celsius: float | None = None

    def set_reading_celsius(self, bt_celsius: float) -> None:
        self.status = SensorStatus.OK
        self.bt_celsius = bt_celsius

    def set_missing(self) -> None:
        self.status = SensorStatus.MISSING
        self.bt_celsius = None

    def set_fault(self) -> None:
        self.status = SensorStatus.FAULT
        self.bt_celsius = None

    def read(self) -> FakeSensorReading:
        return FakeSensorReading(status=self.status, bt_celsius=self.bt_celsius)


@dataclass
class FakeOutputDriver:
    actions: list[FakeOutputAction] = field(default_factory=list)

    def apply_output(
        self,
        *,
        heat_setting: int,
        heat_voltage: float,
        fan_setting: int,
        reason: str,
    ) -> None:
        self.actions.append(
            FakeOutputAction(
                heat_setting=heat_setting,
                heat_voltage=heat_voltage,
                fan_setting=fan_setting,
                reason=reason,
            )
        )

    def set_heat_voltage(self, voltage: float) -> None:
        self.apply_output(
            heat_setting=-1,
            heat_voltage=voltage,
            fan_setting=-1,
            reason="set_heat_voltage",
        )

    def set_fan_voltage(self, voltage: float) -> None:
        self.apply_output(
            heat_setting=-1,
            heat_voltage=voltage,
            fan_setting=-1,
            reason="set_fan_voltage",
        )

    @property
    def last_action(self) -> FakeOutputAction | None:
        if not self.actions:
            return None
        return self.actions[-1]


@dataclass
class FakeHardware:
    started: bool = False
    stopped: bool = False
    actions: list[str] = field(default_factory=list)
    thermocouple: FakeThermocouple = field(default_factory=FakeThermocouple)
    output: FakeOutputDriver = field(default_factory=FakeOutputDriver)

    def start(self) -> None:
        self.started = True
        self.stopped = False
        self.actions.append("start")

    def stop(self) -> None:
        self.stopped = True
        self.started = False
        self.actions.append("stop")
