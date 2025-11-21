# psu/owon.py
"""
OWON SPE6103 — драйвер управления через библиотеку owon-psu.

Требуется:
    pip install owon-psu

Документация:
    https://github.com/robbederks/owon-psu-control
"""

from owon_psu import OwonSPE6103


class OwonPSU:
    """
    Обёртка вокруг OwonSPE6103, чтобы интерфейс совпадал с тем,
    что требуется в программе (connect/read/set/reset).
    """

    def __init__(self, baudrate: int = 9600, timeout: float = 0.2):
        self.baudrate = baudrate
        self.timeout = timeout
        self.device: OwonSPE6103 | None = None
        self.connected = False
        self.port = None

    # --------------------------------------------------------
    #  Подключение и отключение
    # --------------------------------------------------------

    def connect(self, port: str) -> bool:
        try:
            self.device = OwonSPE6103(port=port, baudrate=self.baudrate, timeout=self.timeout)
            self.port = port
            self.connected = True
            return True
        except Exception:
            self.device = None
            self.connected = False
            return False

    def disconnect(self):
        if self.device:
            try:
                self.device.serial.close()
            except Exception:
                pass
        self.device = None
        self.connected = False
        self.port = None

    # --------------------------------------------------------
    #  Идентификация
    # --------------------------------------------------------

    def identify(self) -> str | None:
        """SPE6103 не всегда поддерживает *IDN?, но библиотека возвращает model string."""
        if not self.connected or not self.device:
            return None
        try:
            return self.device.get_model()
        except Exception:
            return None

    # --------------------------------------------------------
    #  Управление выходом и уставками
    # --------------------------------------------------------

    def set_output(self, on: bool):
        if not self.connected or not self.device:
            return False
        try:
            self.device.output(on)
            return True
        except Exception:
            return False

    def set_voltage_current(self, u: float, i: float):
        if not self.connected or not self.device:
            return False
        try:
            self.device.set_voltage(u)
            self.device.set_current(i)
            return True
        except Exception:
            return False

    # --------------------------------------------------------
    #  Измерения
    # --------------------------------------------------------

    def read_measurements(self):
        """
        Возвращает (U, I).
        Если не удаётся считать — возвращает (None, None).
        """
        if not self.connected or not self.device:
            return None, None
        try:
            v = self.device.get_voltage()
            a = self.device.get_current()
            return v, a
        except Exception:
            return None, None

    # --------------------------------------------------------
    #  Reset COM
    # --------------------------------------------------------

    def reset_com(self):
        if not self.port:
            return False
        self.disconnect()
        return self.connect(self.port)
