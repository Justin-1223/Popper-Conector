"""Real Raspberry Pi hardware bundle for RoastPi."""

from __future__ import annotations

from dataclasses import dataclass, field

from roastpi.hardware.dac import Mcp4728DacOutput
from roastpi.hardware.thermocouple import Max31855Thermocouple


FAN_HIGH_VOLTAGE = 5.0


@dataclass(frozen=True)
class RealOutputAction:
    heat_setting: int
    heat_voltage: float
    fan_setting: int
    reason: str


@dataclass
class RealOutputDriver:
    dac: Mcp4728DacOutput = field(default_factory=Mcp4728DacOutput)
    actions: list[RealOutputAction] = field(default_factory=list)

    def apply_output(
        self,
        *,
        heat_setting: int,
        heat_voltage: float,
        fan_setting: int,
        reason: str,
    ) -> None:
        if fan_setting != 100:
            raise ValueError("V1 real hardware only supports fan_setting 100")
        self.dac.set_fan_voltage(FAN_HIGH_VOLTAGE)
        self.dac.set_heat_voltage(heat_voltage)
        self.actions.append(
            RealOutputAction(
                heat_setting=heat_setting,
                heat_voltage=heat_voltage,
                fan_setting=fan_setting,
                reason=reason,
            )
        )

    @property
    def last_action(self) -> RealOutputAction | None:
        if not self.actions:
            return None
        return self.actions[-1]

    def close(self) -> None:
        self.dac.close()


@dataclass
class RealHardware:
    thermocouple: Max31855Thermocouple = field(default_factory=Max31855Thermocouple)
    output: RealOutputDriver = field(default_factory=RealOutputDriver)
    started: bool = False
    stopped: bool = False
    actions: list[str] = field(default_factory=list)

    def start(self) -> None:
        self.started = True
        self.stopped = False
        self.actions.append("start")

    def stop(self) -> None:
        self.stopped = True
        self.started = False
        self.actions.append("stop")
        self.thermocouple.close()
        self.output.close()
