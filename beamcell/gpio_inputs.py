"""
Real buttons and switches on the Jetson's 40-pin header (optional - set [gpio] in config/cell.toml).

Wiring (each safety input): a normally-CLOSED contact between the pin and GND, plus a 10 kOhm
pull-up resistor from the pin to 3.3 V (pin 1). Healthy = contact closed = pin reads 0.
Pressed / opened / wire cut / plug pulled = pin reads 1 = STOP. That's what "fail-safe" means:
any fault in the wiring stops the machine instead of hiding a stop.

    estop_pin    the E-stop button's AUXILIARY contact. Its main contacts must still cut the
                 motor power through a safety relay - the Jetson only REPORTS the E-stop.
    gate_pin     gate interlock switch (closed when the gate is shut)
    curtain_pin  a relay contact driven by the light curtain's OSSD outputs (closed = clear)
    reset_pin    blue Reset push-button, normally OPEN to GND (pressed = 0)

Libraries tried, in order: Jetson.GPIO (comes with JetPack), then gpiod. If neither works
while [gpio] is enabled, the safety controller gets a GPIO fault and the machine can't run.
"""
import threading
import time


def _jetson_backend(pins):
    import Jetson.GPIO as GPIO                       # noqa: N814 - library's own name
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    for p in pins:
        GPIO.setup(p, GPIO.IN)
    return lambda p: GPIO.input(p), "Jetson.GPIO"


def _gpiod_backend(pins):
    raise RuntimeError("gpiod needs line numbers, not BOARD pins - use Jetson.GPIO (sudo apt install python3-jetson-gpio)")


class GpioInputs:
    def __init__(self, safety, cfg, backend=None):
        self.safety = safety
        self.cfg = cfg
        self.pins = {k: cfg[k] for k in ("estop_pin", "gate_pin", "curtain_pin", "reset_pin") if cfg.get(k)}
        self.backend = backend                       # tests pass a fake: (read(pin), name)
        self.name = "none"
        self.error = ""
        self.values = {}
        self._stop = threading.Event()

    def start(self):
        if not self.cfg.get("enabled"):
            self.name = "disabled"
            return self
        try:
            read, self.name = self.backend or self._open()
        except Exception as e:                       # noqa: BLE001 - any failure is a stop
            self.error = f"GPIO not available: {e}"
            self.safety.gpio_fault(self.error)
            return self
        for key in ("gate_closed", "curtain_clear"):
            pin = {"gate_closed": "gate_pin", "curtain_clear": "curtain_pin"}[key]
            if pin in self.pins:
                self.safety.input_source[key] = "gpio"
        self._read = read
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _open(self):
        pins = list(self.pins.values())
        try:
            return _jetson_backend(pins)
        except ImportError:
            return _gpiod_backend(pins)

    def poll_once(self):
        """Read every pin once and pass the result on (used by the loop and by the tests)."""
        try:
            v = {k: int(self._read(p)) for k, p in self.pins.items()}
        except Exception as e:                       # noqa: BLE001
            self.error = f"reading GPIO failed: {e}"
            self.safety.gpio_fault(self.error)
            return
        prev, self.values = self.values, v
        if self.error:
            self.error = ""
            self.safety.gpio_restored()
        if "estop_pin" in v:
            if v["estop_pin"]:
                self.safety.press_estop("button")
            elif prev.get("estop_pin"):
                self.safety.release_estop("button")
        if "gate_pin" in v:
            self.safety.set_input("gate_closed", v["gate_pin"] == 0, source="gpio")
        if "curtain_pin" in v:
            self.safety.set_input("curtain_clear", v["curtain_pin"] == 0, source="gpio")
        if "reset_pin" in v and v["reset_pin"] == 0 and prev.get("reset_pin", 1) == 1:
            self.safety.reset("reset button")

    def _loop(self):
        period = 1.0 / max(5, self.cfg.get("poll_hz", 50))
        while not self._stop.is_set():
            self.poll_once()
            time.sleep(period)

    def stop(self):
        self._stop.set()

    def status(self):
        return {"backend": self.name, "pins": self.pins, "values": self.values, "error": self.error}
