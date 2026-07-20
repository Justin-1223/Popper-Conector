"""MCP4728 DAC conversion and driver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


MCP4728_I2C_ADDRESS = 0x60
MCP4728_I2C_BUS = 1
MCP4728_REFERENCE_VOLTAGE = 5.0
MCP4728_MAX_RAW_VALUE = 4095
FAN_CHANNEL = 0
HEAT_CHANNEL = 1


@dataclass(frozen=True)
class DacWrite:
    channel: int
    voltage: float
    raw_value: int
    command_byte: int
    data: tuple[int, int]


class DacOutput(Protocol):
    def set_heat_voltage(self, voltage: float) -> None:
        """Set the heat knob output voltage."""

    def set_fan_voltage(self, voltage: float) -> None:
        """Set the fan knob output voltage."""


def voltage_to_raw_value(
    voltage: float,
    *,
    reference_voltage: float = MCP4728_REFERENCE_VOLTAGE,
) -> int:
    if reference_voltage <= 0:
        raise ValueError("reference_voltage must be greater than zero")
    if voltage < 0 or voltage > reference_voltage:
        raise ValueError("voltage must be between 0 and reference voltage")
    return round((voltage / reference_voltage) * MCP4728_MAX_RAW_VALUE)


def build_mcp4728_write(channel: int, voltage: float) -> DacWrite:
    if channel < 0 or channel > 3:
        raise ValueError("MCP4728 channel must be between 0 and 3")

    raw_value = voltage_to_raw_value(voltage)
    command_byte = 0x40 | (channel << 1)
    high_byte = raw_value >> 8
    low_byte = raw_value & 0xFF
    return DacWrite(
        channel=channel,
        voltage=voltage,
        raw_value=raw_value,
        command_byte=command_byte,
        data=(high_byte, low_byte),
    )


class Mcp4728DacOutput:
    def __init__(
        self,
        *,
        i2c_bus: int = MCP4728_I2C_BUS,
        address: int = MCP4728_I2C_ADDRESS,
        dry_run: bool = False,
    ) -> None:
        self.address = address
        self.dry_run = dry_run
        self.writes: list[DacWrite] = []
        self._bus = None if dry_run else self._open_i2c_bus(i2c_bus)

    def set_heat_voltage(self, voltage: float) -> None:
        self._write_voltage(HEAT_CHANNEL, voltage)

    def set_fan_voltage(self, voltage: float) -> None:
        self._write_voltage(FAN_CHANNEL, voltage)

    def close(self) -> None:
        if self._bus is not None:
            self._bus.close()

    def _write_voltage(self, channel: int, voltage: float) -> None:
        write = build_mcp4728_write(channel, voltage)
        self.writes.append(write)
        if self.dry_run:
            return
        if self._bus is None:
            raise RuntimeError("I2C bus is not open")
        self._bus.write_i2c_block_data(
            self.address,
            write.command_byte,
            list(write.data),
        )

    def _open_i2c_bus(self, i2c_bus: int):
        try:
            from smbus2 import SMBus
        except ImportError as error:
            raise RuntimeError(
                "Missing Python package 'smbus2'. Install it on the Raspberry Pi "
                "with: python3 -m pip install smbus2"
            ) from error

        return SMBus(i2c_bus)
