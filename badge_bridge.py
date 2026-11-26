"""Harald's Messengers: laptop side of the Bluetooth badge.

Setup (once):
    python -m venv venv
    source venv/bin/activate
    pip install bleak

Test by hand:
    python badge_bridge.py
Then type a command and press Enter:
    1 = STAGE:1    2 = STAGE:2    3 = STAGE:3 (finale)
    e = ERR        r = RESET      q = quit
Pressing the button on the badge prints "Badge button pressed".

Use from the game code:
    badge = Badge(on_button=my_function)
    await badge.connect()
    await badge.stage(1)
"""

import asyncio

from bleak import BleakClient, BleakScanner

BADGE_NAME = "MSG-01"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # laptop -> badge
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # badge -> laptop


class Badge:
    def __init__(self, name=BADGE_NAME, on_button=None, on_message=None):
        self.name = name
        self.on_button = on_button
        self.on_message = on_message   # gets every other text, e.g. "PROX:TOKYO:-63"
        self.client = None

    async def connect(self, timeout=15.0):
        print(f"Looking for badge {self.name} ...")
        device = await BleakScanner.find_device_by_name(self.name, timeout=timeout)
        if device is None:
            raise RuntimeError(
                f"Badge {self.name} not found. Is it powered, and is LED 1 blinking?"
            )
        self.client = BleakClient(device, disconnected_callback=self._on_disconnect)
        await self.client.connect()
        await self.client.start_notify(TX_UUID, self._on_notify)
        print(f"Connected to {self.name}")

    def _on_disconnect(self, _client):
        print("Badge disconnected")

    def _on_notify(self, _sender, data):
        message = bytes(data).decode(errors="ignore").strip()
        if message == "BTN":
            if self.on_button:
                self.on_button()
            else:
                print("Badge button pressed")
        elif self.on_message:
            self.on_message(message)
        else:
            print(f"Badge says: {message}")

    async def send(self, command):
        if self.client is None or not self.client.is_connected:
            print(f"Not connected, could not send {command}")
            return
        await self.client.write_gatt_char(RX_UUID, command.encode())

    async def stage(self, number):
        await self.send(f"STAGE:{number}")

    async def error(self):
        await self.send("ERR")

    async def reset(self):
        await self.send("RESET")

    async def disconnect(self):
        if self.client is not None and self.client.is_connected:
            await self.client.disconnect()


KEYS = {"1": "STAGE:1", "2": "STAGE:2", "3": "STAGE:3", "e": "ERR", "r": "RESET"}


async def main():
    badge = Badge()
    await badge.connect()
    print("Type 1, 2, 3, e, r or q, then Enter")
    loop = asyncio.get_running_loop()
    try:
        while True:
            key = (await loop.run_in_executor(None, input, "> ")).strip().lower()
            if key == "q":
                break
            if key in KEYS:
                await badge.send(KEYS[key])
                print(f"Sent {KEYS[key]}")
            elif key:
                print("Unknown key. Use 1, 2, 3, e, r or q")
    finally:
        await badge.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
