/*
  Real robot joint for the Orin digital twin.
  Input: potentiometer (knob) on A0.

  Wiring:
    Servo  brown/black -> GND
    Servo  red         -> 5V
    Servo  orange/yellow (signal) -> pin 9
    Potentiometer: left leg -> 5V, middle leg -> A0, right leg -> GND

  Talks to the Orin over USB at 115200 baud:
    Orin -> Arduino:  "S90\n"   move servo to 90 degrees (0..180)
    Arduino -> Orin:  "K123\n"  knob position in degrees (0..180), 20 times a second
*/
#include <Servo.h>

const int SERVO_PIN = 9;
const int KNOB_PIN = A0;

Servo joint;
String line = "";
unsigned long lastReport = 0;
float smoothKnob = -1;  // filtered knob reading (0..1023)

void setup() {
  Serial.begin(115200);
  joint.attach(SERVO_PIN);
  joint.write(90);  // start in the middle
  Serial.println("READY");
}

void loop() {
  // 1. Read commands from the Orin, one line at a time
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (line.startsWith("S")) {
        int angle = constrain(line.substring(1).toInt(), 0, 180);  // safety limit
        joint.write(angle);
      }
      line = "";
    } else if (c != '\r') {
      line += c;
    }
  }

  // 2. Read the knob and smooth it: each new reading only moves the value 10%
  //    of the way, so small electrical wobble is averaged out.
  int raw = analogRead(KNOB_PIN);
  if (smoothKnob < 0) smoothKnob = raw;
  smoothKnob = smoothKnob * 0.9 + raw * 0.1;

  // 3. Report the knob position every 50 ms
  if (millis() - lastReport >= 50) {
    lastReport = millis();
    int knob = map((int)smoothKnob, 0, 1023, 0, 180);
    Serial.print("K");
    Serial.println(knob);
  }
}
