# mppt/serial_auto.py
"""
Автоматический выбор/открытие COM-порта для MPPT.

Ключевые моменты:
- Выделены списки фильтров PREFERRED_DESCRIPTIONS / IGNORED_DESCRIPTIONS,
  чтобы их было легко менять под другое устройство.
- Есть:
    * list_ports()          — вернуть список подходящих портов для GUI
    * connect(port_name)    — открыть заданный порт или автоподбор, если None
    * ensure(port_name)     — гарантировать открытое соединение
    * close()               — закрыть порт
"""

import serial
from serial.tools import list_ports
from typing import List, Optional

# Порты, которые мы явно хотим игнорировать (клоны UART-адаптеров и т.п.)
IGNORED_DESCRIPTIONS: list[str] = [
    "CH340",
]

# Порты, которые считаем целевыми в первую очередь.
# Для ST-Link MPPT-терминала нас интересует Virtual COM Port от ST.
PREFERRED_DESCRIPTIONS: list[str] = [
    "STMicroelectronics STLink Virtual COM Port",
    "STLink Virtual COM Port",
]


class SerialAuto:
    def __init__(self, baudrate: int):
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.current_port: Optional[str] = None

    # ------------------------ Вспомогательные методы ------------------------

    def _is_ignored(self, p) -> bool:
        """True, если этот порт надо отфильтровать по IGNORED_DESCRIPTIONS."""
        desc = (p.description or "").strip()
        for bad in IGNORED_DESCRIPTIONS:
            if bad and bad in desc:
                return True
        return False

    def list_ports(self):
        """
        Вернуть список портов, которые не попали под IGNORED_DESCRIPTIONS.
        Используется GUI (ComboBox) для выбора порта вручную.
        """
        ports = list(list_ports.comports())
        return [p for p in ports if not self._is_ignored(p)]

    def _pick_port(self):
        """
        Выбрать порт автоматически.

        Алгоритм:
        1) среди подходящих портов ищем те, у кого description содержит
           любую из строк в PREFERRED_DESCRIPTIONS
        2) если такой не нашли — берём первый доступный
        """
        ports = self.list_ports()
        if not ports:
            return None

        # сначала ищем «идеальный» порт по описанию
        preferred: List = []
        for p in ports:
            desc = (p.description or "").strip()
            if any(mark in desc for mark in PREFERRED_DESCRIPTIONS):
                preferred.append(p)

        if preferred:
            return preferred[0]

        # иначе просто первый подходящий
        return ports[0]

    # ---------------------------- Открытие порта ----------------------------

    def connect(self, port_name: Optional[str] = None) -> bool:
        """
        Открыть порт.

        :param port_name: Явное имя порта ("COM5", "/dev/ttyACM0") или None.
                          Если None — используется автоподбор (_pick_port()).
        :return: True, если порт открыт успешно.
        """
        # На всякий случай закрываем предыдущий
        self.close()

        target_name: Optional[str] = port_name

        if not target_name:
            info = self._pick_port()
            if not info:
                return False
            target_name = info.device

        try:
            self.ser = serial.Serial(
                port=target_name,
                baudrate=self.baudrate,
                timeout=0.05,
            )
            self.current_port = target_name
            return True
        except Exception:
            self.ser = None
            self.current_port = None
            return False

    def ensure(self, port_name: Optional[str] = None) -> bool:
        """
        Убедиться, что порт открыт.

        Если уже открыт — возвращает True.
        Если закрыт — пытается открыть (с учётом port_name или автоподбора).
        """
        if self.ser and self.ser.is_open:
            return True
        return self.connect(port_name=port_name)

    def close(self):
        """Аккуратно закрыть порт."""
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.current_port = None
