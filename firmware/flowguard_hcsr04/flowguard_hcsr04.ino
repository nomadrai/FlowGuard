/*
 * flowguard_hcsr04.ino — ESP32 firmware for FlowGuard's physical node.
 *
 * Reads an HC-SR04 ultrasonic sensor and streams CSV over Serial:
 *   t_ms,distance_cm,water_level_cm
 *
 * Wiring (see docs/FULL_HARDWARE_BUILD.md):
 *   HC-SR04 VCC  -> ESP32 5V/VIN
 *   HC-SR04 GND  -> ESP32 GND
 *   HC-SR04 Trig -> ESP32 GPIO5
 *   HC-SR04 Echo -> 1kOhm -> GPIO18 (junction) -> 2kOhm -> GND
 *                   (voltage divider: 5V Echo signal -> ~3.3V safe for ESP32)
 *
 * Setup:
 *   1. Upload with the channel empty, note the printed distance_cm.
 *   2. Set SENSOR_MOUNT_HEIGHT_CM to that value and re-upload.
 *   3. With the channel still empty, water_level_cm should read ~0.
 */

const int TRIG_PIN = 5;
const int ECHO_PIN = 18;

// Distance from sensor face to the empty channel floor (cm).
// Set this from a real empty-channel reading (see docs/FULL_HARDWARE_BUILD.md Step 9).
const float SENSOR_MOUNT_HEIGHT_CM = 20.0;

// HC-SR04 valid range is ~2cm-400cm; treat anything outside that as a bad reading.
const float MIN_VALID_CM = 2.0;
const float MAX_VALID_CM = 400.0;
const unsigned long ECHO_TIMEOUT_US = 30000UL;  // ~5m round trip, generous margin

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  if (duration == 0) {
    return -1.0;  // no echo received (timeout)
  }

  float distance_cm = duration * 0.0343 / 2.0;
  if (distance_cm < MIN_VALID_CM || distance_cm > MAX_VALID_CM) {
    return -1.0;  // out of sensor's reliable range
  }
  return distance_cm;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  Serial.println("t_ms,distance_cm,water_level_cm");
}

void loop() {
  float distance_cm = readDistanceCm();
  float water_level_cm = -1.0;
  if (distance_cm >= 0.0) {
    water_level_cm = SENSOR_MOUNT_HEIGHT_CM - distance_cm;
    if (water_level_cm < 0.0) {
      water_level_cm = 0.0;
    }
  }

  Serial.print(millis());
  Serial.print(",");
  Serial.print(distance_cm, 2);
  Serial.print(",");
  Serial.println(water_level_cm, 2);

  delay(500);
}
