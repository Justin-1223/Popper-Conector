"""Pure protocol parsing and response models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal, Union


SUPPORTED_COMMANDS = frozenset({"getData", "setHeat", "setFan", "roastEvent"})
ROAST_EVENTS = frozenset({"CHARGE", "DROP", "OFF"})


class ProtocolError(ValueError):
    """Raised when an incoming WebSocket message does not match V1 schema."""


@dataclass(frozen=True)
class GetDataRequest:
    id: int | str
    roaster_id: int | str | None = None


@dataclass(frozen=True)
class SetHeatCommand:
    requested_heat_percent: float
    source: str | None = None


@dataclass(frozen=True)
class SetFanCommand:
    fan_setting: int
    source: str | None = None


@dataclass(frozen=True)
class RoastEventCommand:
    event: Literal["CHARGE", "DROP", "OFF"]
    t: float | None = None
    bt: float | None = None
    source: str | None = None


ParsedMessage = Union[GetDataRequest, SetHeatCommand, SetFanCommand, RoastEventCommand]


@dataclass(frozen=True)
class DataSnapshot:
    bt: float | None
    requested_heat_percent: float
    actual_accumulated_heat_percent: float
    low_heat_setting: int
    high_heat_setting: int
    fan_setting: int
    state: str
    sensor_status: str
    control_status: str
    timestamp_ms: int | None = None
    sample_age_ms: int | None = None
    active_heat_setting: int | None = None
    last_command: str | None = None
    last_command_status: str | None = None
    last_error: str | None = None


def parse_message(raw_message: str | bytes | dict[str, Any]) -> ParsedMessage:
    envelope = _load_envelope(raw_message)
    command = envelope.get("command")
    if not isinstance(command, str):
        raise ProtocolError("message command must be a string")
    if command not in SUPPORTED_COMMANDS:
        raise ProtocolError(f"unsupported command: {command}")

    if command == "getData":
        return _parse_get_data(envelope)
    if command == "setHeat":
        return _parse_set_heat(envelope)
    if command == "setFan":
        return _parse_set_fan(envelope)
    if command == "roastEvent":
        return _parse_roast_event(envelope)

    raise ProtocolError(f"unsupported command: {command}")


def build_get_data_response(request_id: int | str, snapshot: DataSnapshot) -> dict[str, Any]:
    if snapshot.sensor_status not in {"ok", "missing", "fault"}:
        raise ProtocolError("sensor_status must be ok, missing, or fault")
    if snapshot.sensor_status != "ok" and snapshot.bt is not None:
        raise ProtocolError("faulted or missing sensor must not carry BT")

    data: dict[str, Any] = {
        "requested_heat_percent": snapshot.requested_heat_percent,
        "actual_accumulated_heat_percent": snapshot.actual_accumulated_heat_percent,
        "low_heat_setting": snapshot.low_heat_setting,
        "high_heat_setting": snapshot.high_heat_setting,
        "fan_setting": snapshot.fan_setting,
        "state": snapshot.state,
        "sensor_status": snapshot.sensor_status,
        "control_status": snapshot.control_status,
        "last_command": snapshot.last_command,
        "last_command_status": snapshot.last_command_status,
        "last_error": snapshot.last_error,
    }

    if snapshot.sensor_status == "ok":
        if snapshot.bt is None:
            raise ProtocolError("ok sensor status requires a BT value")
        data["BT"] = snapshot.bt

    optional_fields = {
        "timestamp_ms": snapshot.timestamp_ms,
        "sample_age_ms": snapshot.sample_age_ms,
        "active_heat_setting": snapshot.active_heat_setting,
    }
    for key, value in optional_fields.items():
        if value is not None:
            data[key] = value

    return {"id": request_id, "data": data}


def _load_envelope(raw_message: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_message, dict):
        return raw_message

    try:
        decoded = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        raise ProtocolError("message must be valid JSON") from exc

    if not isinstance(decoded, dict):
        raise ProtocolError("message must be a JSON object")
    return decoded


def _parse_get_data(envelope: dict[str, Any]) -> GetDataRequest:
    if "id" not in envelope:
        raise ProtocolError("getData requires an id")
    request_id = envelope["id"]
    if isinstance(request_id, bool) or not isinstance(request_id, (int, str)):
        raise ProtocolError("getData id must be a string or integer")
    roaster_id = envelope.get("roasterID")
    if roaster_id is not None and (
        isinstance(roaster_id, bool) or not isinstance(roaster_id, (int, str))
    ):
        raise ProtocolError("roasterID must be a string or integer")
    return GetDataRequest(
        id=request_id,
        roaster_id=roaster_id,
    )


def _parse_set_heat(envelope: dict[str, Any]) -> SetHeatCommand:
    data = _data_object(envelope)
    value = data.get("requested_heat_percent")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError("setHeat requires numeric requested_heat_percent")
    requested_heat_percent = float(value)
    if (
        not isfinite(requested_heat_percent)
        or requested_heat_percent < 0.0
        or requested_heat_percent > 100.0
    ):
        raise ProtocolError("requested_heat_percent must be between 0 and 100")
    return SetHeatCommand(
        requested_heat_percent=requested_heat_percent,
        source=_optional_string(data, "source"),
    )


def _parse_set_fan(envelope: dict[str, Any]) -> SetFanCommand:
    data = _data_object(envelope)
    value = data.get("fan_setting")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError("setFan requires integer fan_setting")
    if value != 100:
        raise ProtocolError("Phase 2 V1 fan_setting must be 100")
    return SetFanCommand(
        fan_setting=value,
        source=_optional_string(data, "source"),
    )


def _parse_roast_event(envelope: dict[str, Any]) -> RoastEventCommand:
    data = _data_object(envelope)
    event = data.get("event")
    if event not in ROAST_EVENTS:
        raise ProtocolError("roastEvent requires CHARGE, DROP, or OFF")

    t = _optional_number(data, "t")
    bt = _optional_number(data, "BT")
    return RoastEventCommand(
        event=event,
        t=t,
        bt=bt,
        source=_optional_string(data, "source"),
    )


def _data_object(envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ProtocolError("message data must be an object")
    return data


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"{key} must be a string")
    return value


def _optional_number(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{key} must be numeric")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise ProtocolError(f"{key} must be finite")
    return numeric_value
