"""MAX31855 thermocouple decoding and driver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from roastpi.state import SensorStatus


MAX31855_SPI_BUS = 0
MAX31855_SPI_DEVICE = 0
MAX31855_SPI_SPEED_HZ = 5_000_000


class Max31855Fault(RuntimeError):
    """Raised when MAX31855 reports a thermocouple fault."""


@dataclass(frozen=True)
class ThermocoupleReading:
    status: SensorStatus
    bt_celsius: float | None
    fault: str | None = None


class Thermocouple(Protocol):
    def read(self) -> ThermocoupleReading:
        """Return a thermocouple reading and explicit status."""


def decode_max31855(raw_bytes: bytes | list[int] | tuple[int, ...]) -> ThermocoupleReading:
    if len(raw_bytes) != 4:
        raise ValueError("MAX31855 sample must contain exactly 4 bytes")

    raw_value = int.from_bytes(bytes(raw_bytes), byteorder="big")
    if raw_value & 0x00010000:
        return ThermocoupleReading(
            status=SensorStatus.FAULT,
            bt_celsius=None,
            fault=decode_max31855_fault(raw_value),
        )

    thermocouple_value = raw_value >> 18
    if thermocouple_value & 0x2000:
        thermocouple_value -= 0x4000

    return ThermocoupleReading(
        status=SensorStatus.OK,
        bt_celsius=round(thermocouple_value * 0.25, 2),
        fault=None,
    )


def decode_max31855_fault(raw_value: int) -> str:
    if raw_value & 0x01:
        return "thermocouple_open"
    if raw_value & 0x02:
        return "thermocouple_short_to_ground"
    if raw_value & 0x04:
        return "thermocouple_short_to_vcc"
    return "unknown_thermocouple_fault"


class Max31855Thermocouple:
    def __init__(
        self,
        *,
        spi_bus: int = MAX31855_SPI_BUS,
        spi_device: int = MAX31855_SPI_DEVICE,
        spi_speed_hz: int = MAX31855_SPI_SPEED_HZ,
    ) -> None:
        self._spi = self._open_spi(spi_bus, spi_device, spi_speed_hz)

    def read(self) -> ThermocoupleReading:
        raw_bytes = self._spi.xfer2([0x00, 0x00, 0x00, 0x00])
        return decode_max31855(raw_bytes)

    def close(self) -> None:
        self._spi.close()

    def _open_spi(self, spi_bus: int, spi_device: int, spi_speed_hz: int):
        try:
            import spidev
        except ImportError as error:
            raise RuntimeError(
                "Missing Python package 'spidev'. Install it on the Raspberry Pi "
                "with: python3 -m pip install spidev"
            ) from error

        spi = spidev.SpiDev()
        spi.open(spi_bus, spi_device)
        spi.max_speed_hz = spi_speed_hz
        spi.mode = 0
        return spi
