# mppt/logger.py — версия с записью в Excel, автозаписью PASSED и Git-интеграцией с отдельным статусом
from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional, Tuple, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from util.fileutil import get_log_paths, timestamp_str
from util.ansi import strip_ansi
from mppt.terminal_pyte import PYTE_FG_TO_HEX


def _excel_color_from_hex(term_hex: str) -> str:
    """
    Преобразует цвет из CanvasTerminal ("#RRGGBB") в цвет Excel ("RRGGBB")
    по нашей схеме:
    - зелёный  -> 00AA00
    - красный  -> FF0000
    - всё остальное -> 000000 (чёрный)
    """
    if not term_hex:
        return "000000"
    hex_clean = term_hex.lstrip("#").lower()

    green_set = {
        PYTE_FG_TO_HEX["green"].lstrip("#").lower(),
        PYTE_FG_TO_HEX.get("brightgreen", "").lstrip("#").lower(),
    }
    red_set = {
        PYTE_FG_TO_HEX["red"].lstrip("#").lower(),
        PYTE_FG_TO_HEX.get("brightred", "").lstrip("#").lower(),
    }

    if hex_clean in green_set:
        return "00AA00"
    if hex_clean in red_set:
        return "FF0000"
    return "000000"


class MPPTLogger:
    """
    Логгер для MPPT:

    - ведёт txt-лог кадра (сырой текст без ANSI)
    - пишет в Excel:
        * основной лист "Sheet" — все сохранения
        * лист "PASSED"       — только кадры, в конце которых есть PASSED
    - защита от повторов: в одном сеансе для одного и того же ID автозапись
      PASSED делается только один раз
    - Git-интеграция:
        * git pull при старте (если каталог логов — git-репозиторий)
        * git add/commit по кнопке
        * git push по кнопке
      Все Git-статусы выводятся через отдельный git_status_callback.
    """

    def __init__(self, base_dir: Optional[str] = None, status_callback: Optional[Callable[[str, str], None]] = None):
        # пути к txt и xlsx логам
        self.txt_path, self.xlsx_path = get_log_paths(base_dir)
        # общий статус (главный status bar приложения)
        self.status_callback: Optional[Callable[[str, str], None]] = status_callback
        # отдельный Git-статус (заполняется в MPPTTerminalPanel)
        self.git_status_callback: Optional[Callable[[str, str], None]] = None

        # запоминаем, для какого ID уже автозаписывали PASSED в этом сеансе
        self.last_passed_id: Optional[str] = None

        # каталог, где лежат логи — там же ожидаем git-репозиторий
        self.logs_dir = os.path.dirname(self.txt_path) or os.getcwd()

    # ----------------------------------------------------------
    # Статусы
    # ----------------------------------------------------------
    def _set_status(self, msg: str, color: str = "white") -> None:
        """Общий статус (COM, Excel и т.п.)."""
        if self.status_callback:
            self.status_callback(msg, color)
        else:
            print(msg)

    def _set_git_status(self, msg: str, color: str = "white") -> None:
        """Отдельный статус для Git. Если git_status_callback не задан, используем общий статус."""
        if self.git_status_callback:
            try:
                self.git_status_callback(msg, color)
                return
            except Exception:
                # если что-то пошло не так с callback — не валимся, а пишем в общий статус/консоль
                pass
        self._set_status(msg, color)

    # ----------------------------------------------------------
    # Excel
    # ----------------------------------------------------------
    def _ensure_workbook(self) -> Tuple[Workbook, object, object]:
        """
        Создаёт/открывает Excel-файл.
        Возвращает три листа:
            wb, основной ws, PASSED-лист ws_passed
        """
        if os.path.exists(self.xlsx_path):
            wb = load_workbook(self.xlsx_path)

            # основной лист
            ws = wb.active
            if ws.title != "Sheet":
                ws = wb["Sheet"]

            # PASSED-лист
            if "PASSED" in wb.sheetnames:
                ws_passed = wb["PASSED"]
            else:
                ws_passed = wb.create_sheet("PASSED")
                # создаём шапку, если в основном листе она есть
                if ws.max_row >= 1:
                    header = [cell.value for cell in ws[1]]
                    ws_passed.append(header)

            return wb, ws, ws_passed

        # если файла нет — создаём новый
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet"

        header = [
            "ID", "UART", "Voltage", "U_bat", "U_src",
            "Current", "I_crg", "I_ch1", "I_ch2",
            "Charger", "M_sens", "L_sens",
        ]
        ws.append(header)

        ws_passed = wb.create_sheet("PASSED")
        ws_passed.append(header)

        os.makedirs(os.path.dirname(self.xlsx_path), exist_ok=True)
        wb.save(self.xlsx_path)
        return wb, ws, ws_passed

    # ----------------------------------------------------------
    # Парсинг кадра
    # ----------------------------------------------------------
    def _parse_frame(self, lines: List[str], color_matrix) -> Tuple[List[str], List[str]]:
        """
        Парсинг кадра (18 строк pyte.get_lines()) в массив значений и цветов.
        """
        values = ["" for _ in range(12)]
        colors = ["000000" for _ in range(12)]

        plain_lines = [strip_ansi(l) for l in lines]

        # ---------- ID ----------
        id_pattern = re.compile(r"ID:([0-9A-Fa-f]{4})")
        for row_idx, ln in enumerate(plain_lines):
            m = id_pattern.search(ln)
            if m:
                values[0] = m.group(1).upper()
                if color_matrix and row_idx < len(color_matrix):
                    # цвет первой "ячейки" считаем цветом ID
                    c = color_matrix[row_idx][0]
                    colors[0] = _excel_color_from_hex(c)
                break

        # --------- Вольты / токи и пр. ----------
        # Словарь: (метка_на_экране, индекс_колонки, режим)
        fields = [
            ("UART", 1, "text"),      # например "V'C"
            ("V:", 2, "number"),      # Voltage
            ("Ubat:", 3, "number"),
            ("Usrc:", 4, "number"),
            ("I:", 5, "number"),      # Current
            ("Icrg:", 6, "number"),
            ("Ich1:", 7, "number"),
            ("Ich2:", 8, "number"),
            ("CHG", 9, "text"),       # Charger state
            ("M:", 10, "text"),       # M_sens
            ("L:", 11, "text"),       # L_sens
        ]

        for label, col_idx, mode in fields:
            for row_idx, ln in enumerate(plain_lines):
                if label not in ln:
                    continue

                # цвет берём из color_matrix (первый символ строки)
                if color_matrix and row_idx < len(color_matrix):
                    term_hex = color_matrix[row_idx][0]
                    colors[col_idx] = _excel_color_from_hex(term_hex)

                if mode == "text":
                    # текст после метки
                    part = ln.split(label, 1)[-1].strip()
                    values[col_idx] = part
                elif mode == "number":
                    # число после метки
                    m = re.search(rf"{re.escape(label)}\s+(-?\d+)", ln)
                    if m:
                        values[col_idx] = m.group(1).strip()

        return values, colors

    # ----------------------------------------------------------
    # Сохранение блока
    # ----------------------------------------------------------
    def save_block(self, lines: List[str], color_matrix=None, short_id: Optional[str] = None, auto: bool = False) -> None:
        """
        Сохраняем блок:
        - lines        — строки pyte (с ANSI, мы сами очистим)
        - color_matrix — матрица цветов CanvasTerminal.last_colors
        - short_id     — ID устройства (CRC16 UID), если есть
        - auto         — True, если автосохранение по PASSED
        """
        ts = timestamp_str()
        plain = [strip_ansi(l) for l in lines]

        # ---------- TXT LOG ----------
        os.makedirs(os.path.dirname(self.txt_path), exist_ok=True)
        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write("\n" + "-" * 50 + "\n")
            f.write(f"[{ts}]\n")
            for l in plain:
                f.write(l.rstrip() + "\n")
            f.write("-" * 50 + "\n")

        # ---------- Excel ----------
        wb, ws, ws_passed = self._ensure_workbook()
        values, colors = self._parse_frame(lines, color_matrix)

        # если short_id передан — он приоритетнее ID из кадра
        if short_id:
            values[0] = short_id
            colors[0] = "000000"

        # --- Проверка PASSED ---
        last_line = plain[-1].upper() if plain else ""
        is_passed = "PASSED" in last_line
        cur_id = values[0]

        if auto:
            # автозапись включена — добавляем защиту от повторов
            if is_passed:
                # если ID пустой — всё равно запишем, но без защиты от повторов
                if cur_id:
                    if self.last_passed_id == cur_id:
                        # уже записывали PASSED для этого ID в этом сеансе
                        self._set_status(
                            f"MPPT: PASSED уже был записан для ID {cur_id} — пропуск",
                            "yellow",
                        )
                        return
                    # новый ID → разрешаем и запоминаем
                    self.last_passed_id = cur_id
                target_ws = ws_passed
            else:
                # в режиме auto, но без PASSED — не пишем вообще
                self._set_status("MPPT: auto-сохранение без PASSED — пропуск", "yellow")
                return
        else:
            # ручное сохранение — пишем всегда в основной лист
            target_ws = ws

        # запись в конец выбранного листа
        row_idx = target_ws.max_row + 1

        for i, (val, col) in enumerate(zip(values, colors), start=1):
            cell = target_ws.cell(row=row_idx, column=i, value=val)
            cell.font = Font(color=col)

        try:
            wb.save(self.xlsx_path)
        except PermissionError:
            self._set_status(
                f"MPPT: не удалось сохранить Excel (файл открыт?): {self.xlsx_path}",
                "red",
            )
            return

        if is_passed and auto:
            self._set_status(f"MPPT: сохранено в лист PASSED (строка {row_idx})", "green")
        else:
            self._set_status(f"MPPT: блок сохранён (строка {row_idx})", "green")

    # ----------------------------------------------------------
    # Git-поддержка
    # ----------------------------------------------------------
    def _is_git_repo(self) -> bool:
        return os.path.isdir(os.path.join(self.logs_dir, ".git"))

    def _run_git(self, *args: str) -> subprocess.CompletedProcess:
        """
        Запуск git-команды в каталоге логов.
        """
        cmd = list(args)
        proc = subprocess.run(
            cmd,
            cwd=self.logs_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git failed: {cmd}")
        return proc

    def _git_pull_on_start(self) -> None:
        """Пробуем подтянуть изменения из origin при старте (ff-only)."""
        if not self._is_git_repo():
            return

        try:
            self._set_git_status("Git: pull origin (ff-only)...", "#85c1ff")
            # fast-forward only, чтобы не плодить merge-коммиты
            self._run_git("git", "pull", "--ff-only")
            self._set_git_status("Git: pull завершён", "#85c1ff")
        except Exception as e:
            self._set_git_status(f"Git: pull не удался: {e}", "yellow")

    def _git_pull_on_start_ui(self) -> None:
        """
        Обёртка для вызова из GUI через after().
        Ничего не бросает наружу, только пишет статус.
        """
        try:
            self._git_pull_on_start()
        except Exception as e:
            self._set_git_status(f"Git: ошибка pull: {e}", "red")

    def git_commit_logs(self) -> None:
        """
        Добавить изменения в git и сделать commit.
        """
        if not self._is_git_repo():
            self._set_git_status("Git: каталог логов не является репозиторием", "yellow")
            return

        try:
            self._set_git_status("Git: commit...", "#85c1ff")
            self._run_git("git", "add", ".")
            msg = f"Auto log commit {timestamp_str()}"
            self._run_git("git", "commit", "-m", msg)
            self._set_git_status("Git: commit завершён", "green")
        except RuntimeError as e:
            # частый случай — "nothing to commit"
            text = str(e)
            if "nothing to commit" in text:
                self._set_git_status("Git: нечего коммитить", "yellow")
            else:
                self._set_git_status(f"Git: ошибка commit: {text}", "red")
        except Exception as e:
            self._set_git_status(f"Git: общая ошибка commit: {e}", "red")

    def git_push(self) -> None:
        """
        Выполнить git push.
        """
        if not self._is_git_repo():
            self._set_git_status("Git: каталог логов не является репозиторием", "yellow")
            return

        try:
            self._set_git_status("Git: push...", "#85c1ff")
            self._run_git("git", "push")
            self._set_git_status("Git: push завершён", "green")
        except Exception as e:
            self._set_git_status(f"Git: ошибка push: {e}", "red")
