// Harald's Messengers: station beacon
// Upload this to a SPARE ESP32 (board: "ESP32 Dev Module"). No wiring needed,
// just power it over USB (laptop, charger or power bank) and put it at the station.
// It only shouts its name over Bluetooth. The badge listens for names starting with "STN-".
//
// Change the name for each station: STN-TOKYO, STN-LONDON, STN-PARIS, STN-ROUEN,
// STN-UTRECHT, STN-YORBA, STN-VARDE, STN-HVIDOVRE, STN-VIBORG, STN-SANFRANCISCO

#include <BLEDevice.h>

#define STATION_NAME "STN-TOKYO"

void setup() {
  Serial.begin(115200);
  BLEDevice::init(STATION_NAME);
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->setScanResponse(true);
  adv->setMinInterval(160);   // shout every 100 ms, so the badge reacts quickly
  adv->setMaxInterval(160);
  BLEDevice::startAdvertising();
  Serial.println("Beacon running as " STATION_NAME);
}

void loop() {
  delay(1000);
}
