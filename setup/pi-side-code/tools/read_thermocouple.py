"""Bench tool for reading the MAX31855 thermocouple."""

from __future__ import annotations

import argparse
import json
import sys

from tool_bootstrap import add_project_src_to_path

add_project_src_to_path()

from roastpi.hardware.thermocouple import Max31855Thermocouple


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read one MAX31855 thermocouple sample.")
    parser.parse_args(argv)

    sensor = Max31855Thermocouple()
    try:
        reading = sensor.read()
    finally:
        sensor.close()

    print(
        json.dumps(
            {
                "sensor_status": reading.status.value,
                "BT": reading.bt_celsius,
                "fault": reading.fault,
            },
            sort_keys=True,
        )
    )
    return 0 if reading.bt_celsius is not None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
