# Raspberry Pi setup

The Raspberry Pi reads the Popper thermocouple, controls the fan and heater
through the DAC, and provides the WebSocket server used by Artisan.

The current setup was verified with Raspbian GNU/Linux 13 (Trixie), Python
3.13, an MCP4728 DAC on I2C, and a MAX31855 thermocouple interface on SPI.

## Network and service details

| Setting | Value |
| --- | --- |
| Wi-Fi name | `PopperRoaster` |
| Wi-Fi password | `roastcoffee` |
| Raspberry Pi address | `192.168.50.1` |
| WebSocket URL | `ws://192.168.50.1:8080/WebSocket` |
| Linux user | `popper` |

## Files in this directory

- `pi/` contains the installable `roastpi` Python package.
- `config/defaults.json` contains the WebSocket and heater calibration values.
- `tools/run_real_server.py` starts the real-hardware WebSocket service.
- `tools/read_thermocouple.py` reads one thermocouple sample for verification.
- `tools/start_real_service_at_boot.sh` is a path-independent cron fallback.
- `systemd/roastpi.service` is the recommended boot service.

## 1. Prepare Raspberry Pi OS

Install Raspberry Pi OS, create a user named `popper`, and enable SSH. At a
terminal on the Pi, install the operating-system packages:

```bash
sudo apt update
sudo apt install -y git network-manager python3 python3-pip python3-venv
```

Enable I2C and SPI, then add the user to the hardware-access groups:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo usermod -aG i2c,spi popper
sudo reboot
```

After rebooting, verify that the hardware interfaces exist:

```bash
ls /dev/i2c-1 /dev/spidev0.0
```

## 2. Download and install the Pi software

Clone the public repository into the `popper` user's home directory:

```bash
cd /home/popper
git clone https://github.com/Justin-1223/Popper-Conector.git
cd /home/popper/Popper-Conector/setup/pi-side-code
```

Create a virtual environment and install the package. The project metadata
automatically installs `websockets`, `smbus2`, and `spidev`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e pi
```

## 3. Test the thermocouple

With the MAX31855 connected, read one sample:

```bash
.venv/bin/python tools/read_thermocouple.py
```

A working sensor returns JSON containing `"sensor_status": "ok"` and a value
for `BT`. Do not continue until thermocouple faults have been corrected.

## 4. Configure the Popper hotspot

The following NetworkManager commands create the Wi-Fi network expected by the
included Artisan settings:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name popper-hotspot autoconnect yes ssid PopperRoaster
sudo nmcli connection modify popper-hotspot 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared ipv4.addresses 192.168.50.1/24 ipv6.method disabled wifi-sec.key-mgmt wpa-psk wifi-sec.psk roastcoffee connection.autoconnect yes
sudo nmcli connection up popper-hotspot
```

Joining `PopperRoaster` may disconnect the computer from its normal Wi-Fi
network. Internet access is not required while roasting.

## 5. Install the boot service

The supplied service expects the repository at the path used above and runs as
the `popper` user:

```bash
sudo cp systemd/roastpi.service /etc/systemd/system/roastpi.service
sudo systemctl daemon-reload
sudo systemctl enable --now roastpi.service
```

Check the service and WebSocket listener:

```bash
systemctl status roastpi.service
journalctl -u roastpi.service -n 50 --no-pager
ss -ltn | grep ':8080'
```

The service creates runtime logs in `setup/pi-side-code/logs/`.

If systemd is unavailable, `tools/start_real_service_at_boot.sh` can be used
from the `popper` user's crontab instead:

```text
@reboot /home/popper/Popper-Conector/setup/pi-side-code/tools/start_real_service_at_boot.sh
```

Use either systemd or the crontab fallback, not both.

## 6. Connect Artisan

1. Join the `PopperRoaster` Wi-Fi network from the computer using the password
   `roastcoffee`.
2. Confirm that the Pi responds at `192.168.50.1`.
3. Open Artisan and load the hotspot `.aset` file from the neighboring
   `computer-side` directory using **Help > Load Settings**.
4. Confirm that bean temperature updates correctly before enabling roast
   control.

## Updating the software

```bash
cd /home/popper/Popper-Conector
git pull
setup/pi-side-code/.venv/bin/python -m pip install -e setup/pi-side-code/pi
sudo systemctl restart roastpi.service
```

## Troubleshooting

- If `BT` is empty or reports a fault, check the thermocouple, MAX31855 wiring,
  SPI configuration, and `/dev/spidev0.0` permissions.
- If the DAC cannot open, check the MCP4728 wiring, I2C configuration,
  `/dev/i2c-1` permissions, and address `0x60`.
- If Artisan cannot connect, confirm that the computer joined `PopperRoaster`,
  the Pi is reachable at `192.168.50.1`, and port `8080` is listening.
- View service errors with `journalctl -u roastpi.service -n 100 --no-pager`.

## Safety

This software controls a mains-powered heating appliance. Verify the
thermocouple, fan output, heater output, emergency shutoff behavior, and loss
of connection handling before roasting coffee. Keep the original thermal
protection in place and never leave the roaster unattended.
