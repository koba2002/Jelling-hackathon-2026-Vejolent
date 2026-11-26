// Harald's Messengers: badge with Bluetooth (BLE), version 2: hot and cold
// NEW in v2: the badge also LISTENS for station beacons (any Bluetooth device
// whose name starts with "STN-", for example "STN-TOKYO"). The stronger the
// signal, the closer the station, the faster the badge ticks.
// Board in Arduino IDE: "ESP32 Dev Module"
// Same wiring as badge_test: LEDs on 25, 26, 27. Buzzer S on 32. Button = IO0.
//
// The badge advertises as "MSG-01". The laptop connects and sends text commands:
//   STAGE:1   LED 1 on, 1 beep      (first card delivered)
//   STAGE:2   LED 2 on, 2 beeps     (second card delivered)
//   STAGE:3   all LEDs on, fanfare  (quest finished)
//   ERR       quick flash + low beeps (wrong card)
//   RESET     all LEDs off          (new visitor)
//   TRACK:1   ticking on  (visitor is walking to a station)
//   TRACK:0   ticking off (visitor is at a challenge or finished)
// About twice a second the badge tells the laptop the nearest station and its
// signal strength, for example "PROX:TOKYO:-63", or "PROX:NONE".
// When a button is pressed (IO0 or the big button on D33), the badge sends "BTN".
// While no laptop is connected, LED 1 blinks slowly.

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <LiquidCrystal.h>   // Library Manager: "LiquidCrystal" by Arduino, Adafruit

#define BADGE_NAME "MSG-01"

// Nordic UART Service: a standard "text over BLE" service
#define SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define RX_UUID      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  // laptop -> badge
#define TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  // badge -> laptop

const int LED1 = 25;
const int LED2 = 26;
const int LED3 = 27;
const int BUZZER = 32;
const int BUTTON = 0;        // the small IO0 button on the ESP32 (still works as a backup)
const int BIG_BUTTON = 33;   // the real button: one leg to D33, the other leg to GND
// A plain button (2 or 4 legs) needs nothing else. If you use a button MODULE with
// 3 pins (S, +, -) and it does not react, set this to false:
const bool BIG_BUTTON_TO_GND = true;
const int leds[] = {LED1, LED2, LED3};
const int BOARD_LED = 2;  // small blue LED on most ESP32 boards, flashes with each tick

// ---- display (1602A, 16 pins) ----
// LCD pin -> ESP32:  RS -> P22,  E -> P23,  D4 -> P18,  D5 -> P19,  D6 -> P21,  D7 -> P4
// LCD GND, RW, BLK -> GND.   LCD VDD, BLA -> VIN (5V).   LCD VO -> GND (contrast).
// LCD D0-D3 stay empty.
LiquidCrystal lcd(22, 23, 18, 19, 21, 4);
String lcdNow[2] = {"", ""};
String statusLine = "Welcome";      // bottom line when not searching
unsigned long lastLcd = 0;
bool wasHere = false;

const bool TICK_SOUND = false;      // true = Geiger ticking again (noisy with many badges)

// ---- hot and cold settings (signal strength = RSSI, a negative number) ----
#define STATION_PREFIX "STN-"
const int RSSI_FAR = -90;     // this weak or weaker: slowest ticking
const int RSSI_NEAR = -50;    // this strong or stronger: fastest ticking
const int TICK_SLOW_MS = 1500;
const int TICK_FAST_MS = 110;
const unsigned long STATION_TIMEOUT_MS = 4000;  // forget a station not heard for this long

struct Station {
  char name[20];
  float rssi;              // smoothed
  unsigned long lastSeen;
  bool used;
};
const int MAX_STATIONS = 8;
Station stations[MAX_STATIONS];

BLEScan *scanner = nullptr;
volatile bool scanRunning = false;
bool tracking = true;
unsigned long lastTick = 0;
unsigned long lastReport = 0;

BLEServer *server = nullptr;
BLECharacteristic *txChar = nullptr;

volatile bool connected = false;
volatile bool justConnected = false;
volatile bool justDisconnected = false;
volatile bool hasCommand = false;
String pendingCommand = "";

bool lastButton = HIGH;
unsigned long lastButtonChange = 0;
unsigned long lastBlink = 0;
bool blinkState = false;

void beep(int freq, int ms) {
  tone(BUZZER, freq);
  delay(ms);
  noTone(BUZZER);
  digitalWrite(BUZZER, LOW);
  delay(70);
}

void allLeds(bool on) {
  for (int i = 0; i < 3; i++) digitalWrite(leds[i], on ? HIGH : LOW);
}

// Write one line of the display (only if it changed, so it does not flicker)
void lcdShow(int row, String text) {
  while (text.length() < 16) text += ' ';
  text = text.substring(0, 16);
  if (text == lcdNow[row]) return;
  lcdNow[row] = text;
  lcd.setCursor(0, row);
  lcd.print(text);
}

// Short tick: the small board LED flashes (and a click, if TICK_SOUND is on)
void tick() {
  digitalWrite(BOARD_LED, HIGH);
  if (TICK_SOUND) tone(BUZZER, 3200);
  delay(14);
  if (TICK_SOUND) {
    noTone(BUZZER);
    digitalWrite(BUZZER, LOW);
  }
  digitalWrite(BOARD_LED, LOW);
}

// Runs every time the badge hears any Bluetooth device nearby.
class ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) override {
    if (!dev.haveName()) return;
    String name = String(dev.getName().c_str());
    if (!name.startsWith(STATION_PREFIX)) return;
    name = name.substring(strlen(STATION_PREFIX));
    int rssi = dev.getRSSI();

    int slot = -1;
    for (int i = 0; i < MAX_STATIONS; i++) {
      if (stations[i].used && name.equals(stations[i].name)) { slot = i; break; }
    }
    if (slot < 0) {
      for (int i = 0; i < MAX_STATIONS; i++) {
        if (!stations[i].used) { slot = i; break; }
      }
      if (slot < 0) return;  // table full
      name.toCharArray(stations[slot].name, sizeof(stations[slot].name));
      stations[slot].rssi = rssi;
      stations[slot].used = true;
    } else {
      // smoothing: Bluetooth signal jumps a lot, so mix old and new
      stations[slot].rssi = 0.7 * stations[slot].rssi + 0.3 * rssi;
    }
    stations[slot].lastSeen = millis();
  }
};

void scanDone(BLEScanResults results) {
  scanRunning = false;
}

// The station with the strongest signal right now, or -1
int nearestStation() {
  int best = -1;
  for (int i = 0; i < MAX_STATIONS; i++) {
    if (!stations[i].used) continue;
    if (millis() - stations[i].lastSeen > STATION_TIMEOUT_MS) { stations[i].used = false; continue; }
    if (best < 0 || stations[i].rssi > stations[best].rssi) best = i;
  }
  return best;
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *s) override {
    connected = true;
    justConnected = true;
  }
  void onDisconnect(BLEServer *s) override {
    connected = false;
    justDisconnected = true;
  }
};

// Runs when the laptop sends text. We only store it here and act on it in loop().
class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String value = String(c->getValue().c_str());
    value.trim();
    if (value.length() > 0) {
      pendingCommand = value;
      hasCommand = true;
    }
  }
};

void runCommand(String cmd) {
  Serial.print("Command: ");
  Serial.println(cmd);

  if (cmd == "STAGE:1") {
    statusLine = "Delivered: 1";
    digitalWrite(LED1, HIGH);
    beep(2000, 150);
  } else if (cmd == "STAGE:2") {
    statusLine = "Delivered: 2";
    digitalWrite(LED2, HIGH);
    beep(2000, 150);
    beep(2000, 150);
  } else if (cmd == "STAGE:3") {
    statusLine = "You are the 13th";
    allLeds(true);
    beep(1500, 120);
    beep(2000, 120);
    beep(2500, 120);
    beep(3000, 350);
  } else if (cmd == "ERR") {
    for (int i = 0; i < 3; i++) {
      digitalWrite(LED3, HIGH);
      beep(400, 80);
      digitalWrite(LED3, LOW);
    }
  } else if (cmd == "RESET") {
    statusLine = "Welcome";
    allLeds(false);
  } else if (cmd == "TRACK:1") {
    tracking = true;
  } else if (cmd == "TRACK:0") {
    tracking = false;
  } else {
    Serial.println("Unknown command");
  }
}

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 3; i++) {
    pinMode(leds[i], OUTPUT);
    digitalWrite(leds[i], LOW);
  }
  pinMode(BUZZER, OUTPUT);
  digitalWrite(BUZZER, LOW);
  pinMode(BUTTON, INPUT_PULLUP);
  pinMode(BIG_BUTTON, BIG_BUTTON_TO_GND ? INPUT_PULLUP : INPUT_PULLDOWN);
  pinMode(BOARD_LED, OUTPUT);
  digitalWrite(BOARD_LED, LOW);

  lcd.begin(16, 2);
  lcdShow(0, "Harald Messenger");
  lcdShow(1, "Starting...");

  BLEDevice::init(BADGE_NAME);
  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService *service = server->createService(SERVICE_UUID);

  txChar = service->createCharacteristic(TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  txChar->addDescriptor(new BLE2902());

  BLECharacteristic *rxChar = service->createCharacteristic(
      RX_UUID,
      BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rxChar->setCallbacks(new RxCallbacks());

  service->start();

  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();

  // Listen for station beacons in the background
  scanner = BLEDevice::getScan();
  scanner->setAdvertisedDeviceCallbacks(new ScanCallbacks(), true);  // true = report every packet
  scanner->setActiveScan(true);   // also ask each device for its name
  scanner->setInterval(160);      // every 100 ms...
  scanner->setWindow(80);         // ...listen for 50 ms (leaves time to talk to the laptop)

  beep(2000, 100);
  Serial.println("Badge ready, advertising as " BADGE_NAME);
}

void loop() {
  if (justConnected) {
    justConnected = false;
    allLeds(false);
    beep(2500, 100);
    Serial.println("Laptop connected");
  }

  if (justDisconnected) {
    justDisconnected = false;
    allLeds(false);
    delay(300);
    BLEDevice::startAdvertising();  // let the laptop find us again
    Serial.println("Laptop disconnected, advertising again");
  }

  // Waiting for the laptop: blink LED 1 slowly
  if (!connected && millis() - lastBlink > 600) {
    blinkState = !blinkState;
    digitalWrite(LED1, blinkState ? HIGH : LOW);
    lastBlink = millis();
  }

  if (hasCommand) {
    hasCommand = false;
    runCommand(pendingCommand);
  }

  // Keep listening for stations (restart the scan each time it finishes)
  if (!scanRunning) {
    scanner->clearResults();
    scanRunning = true;
    scanner->start(3, scanDone, false);
  }

  int near = nearestStation();

  // Hot and cold: tick faster when the station is closer
  if (tracking && near >= 0) {
    int rssi = constrain((int)stations[near].rssi, RSSI_FAR, RSSI_NEAR);
    unsigned long gap = map(rssi, RSSI_FAR, RSSI_NEAR, TICK_SLOW_MS, TICK_FAST_MS);
    if (millis() - lastTick > gap) {
      lastTick = millis();
      tick();
    }
  }

  // Display: distance bar while searching, status otherwise
  if (millis() - lastLcd > 250) {
    lastLcd = millis();
    if (tracking && near >= 0) {
      int rssi = constrain((int)stations[near].rssi, RSSI_FAR, RSSI_NEAR);
      int blocks = map(rssi, RSSI_FAR, RSSI_NEAR, 1, 16);
      String bar = "";
      for (int i = 0; i < blocks; i++) bar += (char)0xFF;   // solid block
      const char *label = blocks < 6 ? "Cold" : blocks < 11 ? "Warmer" : blocks < 15 ? "Hot" : "TAP YOUR CARD!";
      lcdShow(0, label);
      lcdShow(1, bar);
      if (blocks >= 15 && !wasHere) {   // one short beep on arrival
        wasHere = true;
        beep(2500, 80);
      }
      if (blocks < 12) wasHere = false;
    } else if (tracking) {
      lcdShow(0, "Find the stone");
      lcdShow(1, "Searching...");
    } else {
      lcdShow(0, "Harald Messenger");
      lcdShow(1, statusLine);
    }
  }

  // Tell the laptop what we hear, about twice a second
  if (millis() - lastReport > 500) {
    lastReport = millis();
    String msg = "PROX:NONE";
    if (near >= 0) msg = "PROX:" + String(stations[near].name) + ":" + String((int)stations[near].rssi);
    Serial.println(msg);
    if (connected) {
      txChar->setValue(msg.c_str());
      txChar->notify();
    }
  }

  // Button: send "BTN" once per press
  // Pressed = the small IO0 button OR the big button
  bool bigPressed = digitalRead(BIG_BUTTON) == (BIG_BUTTON_TO_GND ? LOW : HIGH);
  bool button = (digitalRead(BUTTON) == LOW || bigPressed) ? LOW : HIGH;
  if (button != lastButton && millis() - lastButtonChange > 50) {
    lastButtonChange = millis();
    lastButton = button;
    if (button == LOW) {
      Serial.println("Button pressed");
      if (connected) {
        txChar->setValue("BTN");
        txChar->notify();
      }
    }
  }

  delay(5);
}
