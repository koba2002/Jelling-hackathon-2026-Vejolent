# Station beacon for the nRF54L15-DK

Each board shouts "STN-TOKYO" or "STN-LONDON" over Bluetooth. The badge listens and ticks
faster the closer it gets. Board target: `nrf54l15dk/nrf54l15/cpuapp` (nRF Connect SDK 2.8+).

1. Install VS Code, then the "nRF Connect for VS Code Extension Pack".
2. In the nRF Connect sidebar: install a toolchain and an SDK (newest stable). Big download.
3. Install SEGGER J-Link and nrfutil when the extension asks (needed to flash).
4. "Open an existing application" -> this folder.
5. "Add build configuration": board target `nrf54l15dk/nrf54l15/cpuapp` (NOT the one ending /ns).
6. Build. Plug the DK in with USB-C, power switch ON. Flash.
7. LED3 blinks = running. LED0 = Tokyo. Press BUTTON 1 = London (LED1).
8. For the second board, change DEFAULT_STATION in src/main.c to "STN-LONDON", build, flash.

Command line instead of VS Code (inside the nRF Connect terminal):
    west build -b nrf54l15dk/nrf54l15/cpuapp -p
    west flash
