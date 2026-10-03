/*
  Encoder wiring test: prints the raw state of CLK (pin 2), DT (pin 3), SW (pin 4).
  1 = HIGH, 0 = LOW. Turning should make CLK and DT flicker; pushing makes SW = 0.
*/
int last = -1;
unsigned long lastBeat = 0;

void setup() {
  Serial.begin(115200);
  pinMode(2, INPUT_PULLUP);
  pinMode(3, INPUT_PULLUP);
  pinMode(4, INPUT_PULLUP);
}

void loop() {
  int clk = digitalRead(2), dt = digitalRead(3), sw = digitalRead(4);
  int now = clk * 100 + dt * 10 + sw;
  if (now != last || millis() - lastBeat > 1000) {
    lastBeat = millis();
    last = now;
    Serial.print("CLK="); Serial.print(clk);
    Serial.print(" DT="); Serial.print(dt);
    Serial.print(" SW="); Serial.println(sw);
  }
}
