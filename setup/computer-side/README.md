# Computer-side setup

The computer runs [Artisan](https://artisan-scope.org/), which displays and
records roast temperatures and sends control commands to the Raspberry Pi.

## Install Artisan and load the Popper settings

1. Go to the [official Artisan download page](https://artisan-scope.org/download/)
   and download the current release for your operating system.
2. Install Artisan:
   - **Windows:** extract the downloaded ZIP file and run the included installer.
   - **macOS:** open the downloaded DMG file and drag `Artisan.app` into the
     Applications folder.
   - **Linux:** install the package provided for your distribution.
3. Download
   [`popper-v1-phase-11-artisan-pid-visual-1hz-hotspot.aset`](popper-v1-phase-11-artisan-pid-visual-1hz-hotspot.aset)
   from this directory.
4. Connect the computer to the Raspberry Pi hotspot used by the Popper
   controller.
5. Open Artisan. From the menu, choose **Help > Load Settings**.
6. Select the downloaded `.aset` file and allow Artisan to load the settings.
7. Verify that the temperature readings appear before starting a roast. If the
   readings show `uu` or do not update, confirm that the computer is connected
   to the Pi hotspot and then reload the settings file.

Artisan can reopen this configuration later through **Help > Load Recent**.
Keep a backup of the `.aset` file before changing the configuration.

> **Safety:** Confirm that temperature monitoring and heater control work as
> expected before roasting. Never leave the roaster unattended.
