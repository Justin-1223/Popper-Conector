"""Configuration loading for Joe build."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "defaults.json"


@dataclass(frozen=True)
class HeatSettingCalibration:
    setting: int
    total_power_watts: float
    estimated_heater_watts: float
    voltage_min: float
    voltage_max: float
    output_voltage: float


@dataclass(frozen=True)
class HeatControlConfig:
    control_window_seconds: float
    calibration: tuple[HeatSettingCalibration, ...]


@dataclass(frozen=True)
class AppConfig:
    websocket_host: str
    websocket_port: int
    websocket_path: str
    mode: str
    heat_control: HeatControlConfig


def load_default_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    with path.open("r", encoding="utf-8") as config_file:
        raw: dict[str, Any] = json.load(config_file)

    websocket = raw["websocket"]
    heat_control = _parse_heat_control(raw["heat_control"])
    return AppConfig(
        websocket_host=str(websocket["host"]),
        websocket_port=int(websocket["port"]),
        websocket_path=str(websocket["path"]),
        mode=str(raw.get("mode", "fake")),
        heat_control=heat_control,
    )


def _parse_heat_control(raw: dict[str, Any]) -> HeatControlConfig:
    control_window_seconds = float(raw["control_window_seconds"])
    if control_window_seconds <= 0:
        raise ValueError("control_window_seconds must be greater than zero")

    calibration = tuple(_parse_heat_setting(entry) for entry in raw["calibration"])
    _validate_calibration_table(calibration)
    return HeatControlConfig(
        control_window_seconds=control_window_seconds,
        calibration=calibration,
    )


def _parse_heat_setting(raw: dict[str, Any]) -> HeatSettingCalibration:
    voltage_range = raw["voltage_range"]
    if len(voltage_range) != 2:
        raise ValueError("voltage_range must contain exactly two values")

    voltage_min = float(min(voltage_range))
    voltage_max = float(max(voltage_range))
    output_voltage = float(raw["output_voltage"])

    return HeatSettingCalibration(
        setting=int(raw["setting"]),
        total_power_watts=float(raw["total_power_watts"]),
        estimated_heater_watts=float(raw["estimated_heater_watts"]),
        voltage_min=voltage_min,
        voltage_max=voltage_max,
        output_voltage=output_voltage,
    )


def _validate_calibration_table(
    calibration: tuple[HeatSettingCalibration, ...],
) -> None:
    if not calibration:
        raise ValueError("heat calibration table must not be empty")

    settings = [entry.setting for entry in calibration]
    if settings != sorted(settings):
        raise ValueError("heat calibration settings must be sorted")
    if len(set(settings)) != len(settings):
        raise ValueError("heat calibration settings must be unique")

    heater_watts = [entry.estimated_heater_watts for entry in calibration]
    if heater_watts != sorted(heater_watts):
        raise ValueError("estimated heater watts must increase by setting")

    for entry in calibration:
        if entry.estimated_heater_watts <= 0:
            raise ValueError("estimated heater watts must be greater than zero")
        if not entry.voltage_min <= entry.output_voltage <= entry.voltage_max:
            raise ValueError("output voltage must be inside the voltage range")
