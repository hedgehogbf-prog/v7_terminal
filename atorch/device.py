from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple


# Путь к скрипту dl24.py из репозитория tshaddack/dl24
DL24_SCRIPT = Path(__file__).resolve().parent / "dl24.py"


class AtorchDL24:
    """
    Обёртка вокруг dl24.py (tshaddack/dl24),
    предоставляет API, совместимый с RigolDL3000:
        - open(), close(), is_open()
        - read_identity()
        - set_current()
        - get_current_set()
        - measure_voltage(), measure_current()
        - set_output(state), get_output()
    """

    def __init__(self, port: str, baudrate: int = 9600, timeout_s: float = 3.0) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s

        self._is_open: bool = False
        self._output_state: bool = False
        self._last_set_current: float = 0.0

    # ----------------------------------------------------------------------
    # helpers
    # ----------------------------------------------------------------------
    def is_open(self) -> bool:
        return self._is_open

    def _check_script(self) -> None:
        if not DL24_SCRIPT.is_file():
            raise RuntimeError(
                f"Не найден dl24.py рядом с atorch/device.py: {DL24_SCRIPT}"
            )

    def _run_dl24(self, *commands: str) -> str:
        """
        Запуск CLI: python dl24.py PORT=COM5@9600 <commands...>.
        Возвращает stdout.
        Бросает исключение при ненулевом RC.
        """
        self._check_script()

        args = [
            sys.executable,
            str(DL24_SCRIPT),
            f"PORT={self.port}@{self.baudrate}",
        ]
        args.extend(commands)

        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"dl24.py error (code={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
            )

        return proc.stdout.strip()

    # ----------------------------------------------------------------------
    # lifecycle
    # ----------------------------------------------------------------------
    def open(self) -> None:
        """
        У Atorch нет постоянного подключения.
        Я делаю только проверку наличия dl24.py.
        """
        self._check_script()
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def read_identity(self) -> str:
        return f"Atorch DL24 on {self.port} via dl24.py"

    # ----------------------------------------------------------------------
    # measurements (V/A)
    # ----------------------------------------------------------------------
    def _read_mv_ma(self) -> Tuple[float, float]:
        """
        dl24.py поддерживает команду:
            LINE QMV QMA
        которая выводит строку из двух чисел: millivolts milliamps.
        Пример: "12540 850"
        """
        out = self._run_dl24("LINE", "QMV", "QMA")
        line = out.strip().splitlines()[0]
        parts = line.split()
        if len(parts) < 2:
            raise RuntimeError(f"Unexpected output from dl24.py: {out!r}")

        mv = float(parts[0])
        ma = float(parts[1])
        return mv, ma

    def measure_voltage(self) -> float:
        mv, _ = self._read_mv_ma()
        return mv / 1000.0

    def measure_current(self) -> float:
        _, ma = self._read_mv_ma()
        return ma / 1000.0

    # ----------------------------------------------------------------------
    # current set
    # ----------------------------------------------------------------------
    def set_current(self, value: float) -> None:
        """
        Установка тока — команда вида "1.500A".
        """
        cmd = f"{value:.3f}A"
        self._run_dl24(cmd)
        self._last_set_current = float(value)

    def get_current_set(self) -> float:
        """
        У DL24 нет команды "прочитать уставку", поэтому храним последнюю.
        """
        return self._last_set_current

    # ----------------------------------------------------------------------
    # output on/off
    # ----------------------------------------------------------------------
    def set_output(self, state: bool) -> None:
        self._run_dl24("ON" if state else "OFF")
        self._output_state = bool(state)

    def get_output(self) -> bool:
        """
        В DL24 нельзя прочитать состояние выхода.
        Возвращаем последний установленный state.
        """
        return self._output_state
