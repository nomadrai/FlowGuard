/*
 * flowguard_hcsr04.ino — ESP32 + HC-SR04 firmware for FlowGuard.
 *
 * Measures water level inside the rectangular inlet box (base 308 cm²) and
 * streams readings over Serial at 115200 baud in CSV format:
 *
 *   t_ms,distance_cm,water_level_cm
 *
 * The drainage pipe (round, diameter 1.90 cm, area ≈ 2.8353 cm²) exits the
 * bottom of this box. The sensor is mounted above the open top of the box,
 * pointing straight down.
 *
 * ── WIRING (see docs/FULL_HARDWARE_BUILD.md) ──────────────────────────────
 *   HC-SR04 VCC  -> ESP32 5V (or VIN)
 *   HC-SR04 GND  -> ESP32 GND
 *   HC-SR04 Trig -> ESP32 GPIO5            (direct connection)
 *   HC-SR04 Echo -> 1 kΩ resistor -> GPIO18
 *                   junction of (1 kΩ output + GPIO18) -> 2 kΩ -> GND
 *   The 1 kΩ / 2 kΩ voltage divider reduces the 5 V Echo signal to ~3.3 V,
 *   which is safe for the ESP32 input pin.
 *
 * ── FIRST-TIME SETUP ──────────────────────────────────────────────────────
 *   1. Upload as-is (SENSOR_MOUNT_HEIGHT_CM = 20.0 as placeholder).
 *   2. Open Serial Monitor at 115200 baud with the inlet box COMPLETELY EMPTY.
 *   3. Note the distance_cm value — that is your real mount height.
 *   4. Set SENSOR_MOUNT_HEIGHT_CM below to that exact number.
 *   5. Re-upload. With the box still empty, water_level_cm should now read ≈ 0.
 *
 * ── INFLOW RATE ───────────────────────────────────────────────────────────
 *   This firmware reads water HEIGHT only — it does NOT measure inflow rate.
 *   Before starting a monitoring session, enter the rainfall inflow rate
 *   (mL/s) once in the FlowGuard dashboard sidebar. That value is used as
 *   Q_observed in the orifice equation: Q = Cd × A × √(2gh)
 *   where A = PIPE_AREA_CM2 = 2.8353 cm².
 *
 * ── READING THE OUTPUT ────────────────────────────────────────────────────
 *   Each Serial line looks like:  5002,17.412,2.588
 *   Copy the third value (water_level_cm) into the dashboard's
 *   "Current water height h (cm)" field, then click "Submit Reading".
 *   Rows containing "ERR" are bad sensor readings — skip them.
 */

// ── Pin assignments ────────────────────────────────────────────────────────
const int TRIG_PIN = 4;   // HC-SR04 Trigger → GPIO5
const int ECHO_PIN = 5;  // HC-SR04 Echo    → GPIO18 (via voltage divider)

// ── Physical constants ─────────────────────────────────────────────────────
// Distance (cm) from sensor face to the bottom of the inlet box.
// Measured: 13.53 cm. With the box empty, water_level_cm should read 0.
const float SENSOR_MOUNT_HEIGHT_CM = 13.53;

// Rectangular inlet box (where rainfall water collects)
const float INLET_BOX_BASE_AREA_CM2 = 308.0;  // cm² — base area of the water inlet box

// Round drainage pipe (exits the bottom of the inlet box)
const float PIPE_DIAMETER_CM  = 1.90;           // cm
const float PIPE_AREA_CM2     = 2.8353;         // cm² — pi × (1.90/2)² = pi × 0.9025

// HC-SR04 reliable range limits
const float MIN_VALID_CM = 2.0;
const float MAX_VALID_CM = 300.0;

// Echo timeout: 30 ms ≈ 515 cm round-trip — comfortably beyond any inlet box
const unsigned long ECHO_TIMEOUT_US = 30000UL;

// Speed of sound at ~25 °C: 343 m/s = 0.0343 cm/µs
// Adjust for local temperature if needed: v = 0.03313 + 0.0000606 × T_celsius
const float SOUND_SPEED_CM_PER_US = 0.0343;

// One reading per second is sufficient for slowly changing water levels
const unsigned long READING_INTERVAL_MS = 1000;

// ── Globals ────────────────────────────────────────────────────────────────
unsigned long last_reading_ms = 0;

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Fire one HC-SR04 pulse and return distance to water surface (cm).
 * Returns -1.0 on timeout or out-of-range reading.
 */
float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  if (duration == 0) return -1.0;  // no echo — sensor not seeing a surface

  float dist = (duration * SOUND_SPEED_CM_PER_US) / 2.0;
  if (dist < MIN_VALID_CM || dist > MAX_VALID_CM) return -1.0;
  return dist;
}

/**
 * Convert sensor air-gap distance to water level inside the inlet box.
 *   water_level = mount_height − distance_to_surface
 * Clamps to 0 when the box is empty (avoids small negative readings from noise).
 */
float distanceToWaterLevelCm(float dist_cm) {
  if (dist_cm < 0.0) return -1.0;
  float level = SENSOR_MOUNT_HEIGHT_CM - dist_cm;
  return (level < 0.0) ? 0.0 : level;
}

// ── Setup ──────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  // Allow Serial Monitor to connect before the header prints
  delay(1500);

  Serial.println("# FlowGuard v1.0  —  ESP32 + HC-SR04");
  Serial.println("# -------------------------------------------------------");
  Serial.print("# Inlet box base area  : "); Serial.print(INLET_BOX_BASE_AREA_CM2, 1);
  Serial.println(" cm2  (rectangular box)");
  Serial.print("# Drainage pipe diam.  : "); Serial.print(PIPE_DIAMETER_CM, 2);
  Serial.println(" cm  (round pipe)");
  Serial.print("# Drainage pipe area   : "); Serial.print(PIPE_AREA_CM2, 4);
  Serial.println(" cm2  [= pi*(d/2)^2]");
  Serial.print("# Sensor mount height  : "); Serial.print(SENSOR_MOUNT_HEIGHT_CM, 2);
  Serial.println(" cm  (update constant if empty-box reads non-zero)");
  Serial.println("# Inflow rate (mL/s)   : enter once in FlowGuard dashboard sidebar");
  Serial.println("# -------------------------------------------------------");
  Serial.println("t_ms,distance_cm,water_level_cm");
}

// ── Main loop ──────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();
  if (now - last_reading_ms < READING_INTERVAL_MS) return;
  last_reading_ms = now;

  float dist_cm  = readDistanceCm();
  float level_cm = distanceToWaterLevelCm(dist_cm);

  // CSV: t_ms, distance_cm, water_level_cm
  // "ERR" in any column = bad reading; skip those rows in the dashboard
  Serial.print(now);
  Serial.print(",");
  if (dist_cm  < 0.0) Serial.print("ERR"); else Serial.print(dist_cm,  3);
  Serial.print(",");
  if (level_cm < 0.0) Serial.println("ERR"); else Serial.println(level_cm, 3);
}
