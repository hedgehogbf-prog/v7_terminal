# rigol/device.py
"""
Обёртка для Rigol DL3000 (DL3021) через PyVISA.

Требуется:
    pip install pyvisa

Поддерживаемые функции:
- open / close
- read_identity()
- measure_voltage(), measure_current()
- set_current(), get_current()
- set_output(True/False), get_output()

SCPI-команды основаны на DL3000 Programming / Performance manuals:
- :SOUR:CURR:RANG
- :SOUR:CURR:LEV:IMM <value>
- :SOUR:INP:STAT 1/0
- :MEAS:VOLT?
- :MEAS:CURR?
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, List

import pyvisa


@dataclass
class RigolPreset:
    """Описание пресета плавного изменения тока."""
    name: str
    i_start: float
    i_end: float
    step: float
    delay_s: float


class RigolDL3000:
    """
    Простая обёртка над DL3021/DL3000.

    Пример использования:

        dev = RigolDL3000("USB0::0x1AB1::0x0E11::DL3A261100199::INSTR")
        dev.open()
        print(dev.read_identity())
        dev.set_current(1.0)
        dev.set_output(True)
    """

    def __init__(self, resource_name: str, timeout_ms: int = 2000) -> None:
        self.resource_name = resource_name
        self.timeout_ms = timeout_ms

        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.resources.MessageBasedResource] = None
        self._lock = threading.Lock()

    # ---------------- Вспомогательныe ----------------

    def is_open(self) -> bool:
        return self._inst is not None

    # ---------------- Жизненный цикл -----------------

    def open(self) -> None:
        if self.is_open():
            return
        self._rm = pyvisa.ResourceManager()
        inst = self._rm.open_resource(self.resource_name)
        inst.timeout = self.timeout_ms
        # Переводим в CC по току и ставим 0 A
        inst.write(":SOUR:FUNC CURR")
        inst.write(":SOUR:CURR:LEV:IMM 0")
        # Выключаем вход на всякий случай
        inst.write(":SOUR:INP:STAT 0")
        self._inst = inst

    def close(self) -> None:
        if not self.is_open():
            return
        try:
            # Отключим нагрузку
            self._inst.write(":SOUR:INP:STAT 0")
        except Exception:
            pass
        try:
            self._inst.close()
        except Exception:
            pass
        self._inst = None
        if self._rm is not None:
            try:
                self._rm.close()
            except Exception:
                pass
        self._rm = None

    # ---------------- Базовые SCPI -------------------

    def _write(self, cmd: str) -> None:
        if not self.is_open():
            raise RuntimeError("Rigol DL3000 not open")
        with self._lock:
            self._inst.write(cmd)

    def _query(self, cmd: str) -> str:
        if not self.is_open():
            raise RuntimeError("Rigol DL3000 not open")
        with self._lock:
            return self._inst.query(cmd).strip()

    # ---------------- API высокого уровня ------------

    def read_identity(self) -> str:
        return self._query("*IDN?")

    # Измерения

    def measure_voltage(self) -> float:
        resp = self._query(":MEAS:VOLT?")
        return float(resp)

    def measure_current(self) -> float:
        resp = self._query(":MEAS:CURR?")
        return float(resp)

    # Настройка тока / диапазона

    def set_current(self, value: float) -> None:
        """
        Установить ток в режиме CC.

        Для DL3000 из мануала:
            :SOUR:CURR:RANG <range>
            :SOUR:CURR:LEV:IMM <value>
        Здесь диапазон не трогаем, только уровень.
        """
        self._write(f":SOUR:FUNC CURR")
        self._write(f":SOUR:CURR:LEV:IMM {value:.6f}")

    def get_current_set(self) -> float:
        resp = self._query(":SOUR:CURR:LEV:IMM?")
        return float(resp)

    # Вход / выход (input state)

    def set_output(self, state: bool) -> None:
        self._write(f":SOUR:INP:STAT {1 if state else 0}")

    def get_output(self) -> bool:
        resp = self._query(":SOUR:INP:STAT?")
        try:
            return bool(int(float(resp)))
        except Exception:
            return False

    # ---------------- Статические хелперы ------------

    @staticmethod
    def discover_usb_resources() -> List[str]:
        """
        Вернуть список VISA-ресурсов, похожих на DL3000 (USB устройства).
        """
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        candidates: List[str] = []
        for r in resources:
            ur = r.upper()
            if "USB" in ur and ("DL3" in ur or "RIGOL" in ur or "0X1AB1" in ur):
                candidates.append(r)
        rm.close()
        return candidates
