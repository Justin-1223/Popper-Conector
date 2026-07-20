"""Pure heat calibration and PWM math."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite

from roastpi.config import HeatControlConfig, HeatSettingCalibration


PERCENT_MIN = 0.0
PERCENT_MAX = 100.0
PWM_DUTY_STEP = 0.1


@dataclass(frozen=True)
class HeatPlan:
    requested_heat_percent: float
    requested_heater_watts: float
    low_heat_setting: int
    high_heat_setting: int
    low_output_voltage: float
    high_output_voltage: float
    pwm_duty_ratio: float


@dataclass(frozen=True)
class TimedHeatSetting:
    heat_setting: int
    duration_seconds: float


def requested_heat_percent_to_heater_watts(
    requested_heat_percent: float,
    heat_config: HeatControlConfig,
) -> float:
    _validate_requested_heat_percent(requested_heat_percent)
    minimum = min_heater_watts(heat_config)
    maximum = max_heater_watts(heat_config)
    return minimum + ((maximum - minimum) * (requested_heat_percent / PERCENT_MAX))


def heater_watts_to_heat_plan(
    requested_heater_watts: float,
    heat_config: HeatControlConfig,
) -> HeatPlan:
    minimum = min_heater_watts(heat_config)
    maximum = max_heater_watts(heat_config)
    if requested_heater_watts < minimum or requested_heater_watts > maximum:
        raise ValueError("requested_heater_watts must be inside calibration range")

    lower, upper = _bracket_heater_watts(requested_heater_watts, heat_config.calibration)
    requested_heat_percent = heater_watts_to_requested_heat_percent(
        requested_heater_watts,
        heat_config,
    )
    duty_ratio = _duty_ratio_on_upper(requested_heater_watts, lower, upper)

    return HeatPlan(
        requested_heat_percent=requested_heat_percent,
        requested_heater_watts=requested_heater_watts,
        low_heat_setting=lower.setting,
        high_heat_setting=upper.setting,
        low_output_voltage=lower.output_voltage,
        high_output_voltage=upper.output_voltage,
        pwm_duty_ratio=duty_ratio,
    )


def requested_heat_percent_to_heat_plan(
    requested_heat_percent: float,
    heat_config: HeatControlConfig,
) -> HeatPlan:
    requested_heater_watts = requested_heat_percent_to_heater_watts(
        requested_heat_percent,
        heat_config,
    )
    return heater_watts_to_heat_plan(requested_heater_watts, heat_config)


def heat_setting_to_output_voltage(
    heat_setting: int,
    heat_config: HeatControlConfig,
) -> float:
    return _setting_by_number(heat_setting, heat_config.calibration).output_voltage


def active_heat_setting_for_elapsed(
    plan: HeatPlan,
    elapsed_seconds: float,
    control_window_seconds: float,
) -> int:
    if elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be greater than or equal to zero")
    if control_window_seconds <= 0:
        raise ValueError("control_window_seconds must be greater than zero")
    if plan.low_heat_setting == plan.high_heat_setting:
        return plan.low_heat_setting

    slot_count = max(1, round(1.0 / PWM_DUTY_STEP))
    high_slots = round(plan.pwm_duty_ratio * slot_count)
    slot_fraction = elapsed_seconds / control_window_seconds
    slot_index = floor((slot_fraction * slot_count) + 1e-9)
    slot_index = min(max(slot_index, 0), slot_count - 1)
    if slot_index < high_slots:
        return plan.high_heat_setting
    return plan.low_heat_setting


def actual_accumulated_heat_percent(
    timed_settings: tuple[TimedHeatSetting, ...],
    heat_config: HeatControlConfig,
) -> float:
    if not timed_settings:
        raise ValueError("timed_settings must not be empty")

    total_duration = 0.0
    weighted_watts = 0.0
    for timed_setting in timed_settings:
        if timed_setting.duration_seconds < 0:
            raise ValueError("duration_seconds must be greater than or equal to zero")
        calibration = _setting_by_number(
            timed_setting.heat_setting,
            heat_config.calibration,
        )
        total_duration += timed_setting.duration_seconds
        weighted_watts += (
            calibration.estimated_heater_watts * timed_setting.duration_seconds
        )

    if total_duration <= 0:
        raise ValueError("total duration must be greater than zero")

    average_watts = weighted_watts / total_duration
    return _bounded_heater_watts_to_requested_heat_percent(average_watts, heat_config)


def heater_watts_to_requested_heat_percent(
    heater_watts: float,
    heat_config: HeatControlConfig,
) -> float:
    minimum = min_heater_watts(heat_config)
    maximum = max_heater_watts(heat_config)
    if heater_watts < minimum or heater_watts > maximum:
        raise ValueError("heater_watts must be inside calibration range")
    return ((heater_watts - minimum) / (maximum - minimum)) * PERCENT_MAX


def _bounded_heater_watts_to_requested_heat_percent(
    heater_watts: float,
    heat_config: HeatControlConfig,
) -> float:
    minimum = min_heater_watts(heat_config)
    maximum = max_heater_watts(heat_config)
    bounded_heater_watts = min(max(heater_watts, minimum), maximum)
    return heater_watts_to_requested_heat_percent(bounded_heater_watts, heat_config)


def min_heater_watts(heat_config: HeatControlConfig) -> float:
    return heat_config.calibration[0].estimated_heater_watts


def max_heater_watts(heat_config: HeatControlConfig) -> float:
    return heat_config.calibration[-1].estimated_heater_watts


def _validate_requested_heat_percent(requested_heat_percent: float) -> None:
    if (
        isinstance(requested_heat_percent, bool)
        or not isinstance(requested_heat_percent, (int, float))
        or not isfinite(requested_heat_percent)
        or requested_heat_percent < PERCENT_MIN
        or requested_heat_percent > PERCENT_MAX
    ):
        raise ValueError("requested_heat_percent must be between 0 and 100")


def _bracket_heater_watts(
    requested_heater_watts: float,
    calibration: tuple[HeatSettingCalibration, ...],
) -> tuple[HeatSettingCalibration, HeatSettingCalibration]:
    for entry in calibration:
        if requested_heater_watts == entry.estimated_heater_watts:
            return entry, entry

    for index, upper in enumerate(calibration[1:], start=1):
        lower = calibration[index - 1]
        if lower.estimated_heater_watts < requested_heater_watts < upper.estimated_heater_watts:
            return lower, upper

    raise ValueError("requested_heater_watts must be inside calibration range")


def _duty_ratio_on_upper(
    requested_heater_watts: float,
    lower: HeatSettingCalibration,
    upper: HeatSettingCalibration,
) -> float:
    if lower.setting == upper.setting:
        return 0.0

    span = upper.estimated_heater_watts - lower.estimated_heater_watts
    raw_duty_ratio = (requested_heater_watts - lower.estimated_heater_watts) / span
    snapped_duty_ratio = round(raw_duty_ratio / PWM_DUTY_STEP) * PWM_DUTY_STEP
    return min(max(snapped_duty_ratio, 0.0), 1.0)


def _setting_by_number(
    heat_setting: int,
    calibration: tuple[HeatSettingCalibration, ...],
) -> HeatSettingCalibration:
    for entry in calibration:
        if entry.setting == heat_setting:
            return entry
    raise ValueError(f"unknown heat setting: {heat_setting}")
