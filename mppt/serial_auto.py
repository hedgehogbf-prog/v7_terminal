# mppt/serial_auto.py
import serial
from serial.tools import list_ports

IGNORED_DESCRIPTIONS = ["CH340"]


class SerialAuto:
    def __init__(self, baudrate: int):
        self.baudrate = baudrate
        self.ser: serial.Serial | None = None
        self.current_port: str | None = None

    def _pick_port(self):
        ports = list(list_ports.comports())
        for p in ports:
            desc = (p.description or "")
            if any(bad.lower() in desc.lower() for bad in IGNORED_DESCRIPTIONS):
                continue
            return p
        return None

    def connect(self):
        if self.ser and self.ser.is_open:
            return True
        cand = self._pick_port()
        if not cand:
            return False
        try:
            self.ser = serial.Serial(cand.device, self.baudrate, timeout=0.02)
            self.current_port = cand.device
            return True
        except Exception:
            self.ser = None
            self.current_port = None
            return False

    def ensure(self):
        if self.ser and self.ser.is_open:
            return True
        return self.connect()

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.current_port = None
