# psu/owon.py
"""
Обёртка над библиотекой owon_psu (pip install owon-psu).

Цель:
- Упростить работу с OwonPSU из GUI.
- При открытии:
    - открыть порт
    - включить REMOTE режим (SYST:REM)
    - включить KeyLock
    - гарантированно выключить выход (set_output(False))

Использование в коде:
    from psu.owon import OwonPSU

    psu = OwonPSU("COM3")
    psu.open()
    psu.set_voltage(5.0)
    psu.set_current(1.0)
    psu.set_output(True)
"""

from __future__ import annotations

from owon_psu import OwonPSU as _LibOwonPSU


class OwonPSU:
    """Высокоуровневая обёртка над owon_psu.OwonPSU."""

    def __init__(self, port: str):
        self._port = port
        self._dev: _LibOwonPSU | None = None
        self._opened = False

    # ---------------- Базовые операции подключения ----------------
    @property
    def port(self) -> str:
        return self._port

    def open(self):
        """Открыть соединение с ЛБП, включить REMOTE и KeyLock."""
        if self._opened and self._dev is not None:
            return

        dev = _LibOwonPSU(self._port)
        dev.open()

        # Попробуем включить REMOTE режим (игнорируем ошибку, если команда не поддерживается)
        try:
            dev._cmd("SYST:REM")
        except Exception:
            pass

        # Включим KeyLock, чтобы случайно не нажать что-то на панели
        try:
            dev.set_keylock(True)
        except Exception:
            pass

        # На всякий случай выключим выход на старте
        try:
            dev.set_output(False)
        except Exception:
            pass

        self._dev = dev
        self._opened = True

    def close(self):
        """Закрыть соединение."""
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None
        self._opened = False

    def is_open(self) -> bool:
        return self._opened and self._dev is not None

    # ---------------- Методы, повторяющие API библиотеки ----------------
    def read_identity(self) -> str:
        if not self.is_open():
            raise RuntimeError("PSU not open")
        return self._dev.read_identity()

    def measure_voltage(self) -> float:
        if not self.is_open():
            raise RuntimeError("PSU not open")
        return self._dev.measure_voltage()

    def measure_current(self) -> float:
        if not self.is_open():
            raise RuntimeError("PSU not open")
        return self._dev.measure_current()

    def get_voltage(self) -> float:
        if not self.is_open():
            raise RuntimeError("PSU not open")
        return self._dev.get_voltage()

    def get_current(self) -> float:
        if not self.is_open():
            raise RuntimeError("PSU not open")
        return self._dev.get_current()

    def set_voltage(self, value: float):
        if not self.is_open():
            raise RuntimeError("PSU not open")
        self._dev.set_voltage(value)

    def set_current(self, value: float):
        if not self.is_open():
            raise RuntimeError("PSU not open")
        self._dev.set_current(value)

    def set_output(self, state: bool):
        """Включить/выключить выход."""
        if not self.is_open():
            raise RuntimeError("PSU not open")
        self._dev.set_output(bool(state))

    def get_output(self) -> bool:
        if not self.is_open():
            raise RuntimeError("PSU not open")
        return bool(self._dev.get_output())
