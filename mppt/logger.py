# mppt/logger.py — версия с записью в Excel и жёсткой авто-записью PASSED
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
import os
import re

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
    def __init__(self, base_dir=None, status_callback=None):
        self.txt_path, self.xlsx_path = get_log_paths(base_dir)
        self.status_callback = status_callback
        # запоминаем, для какого ID уже автозаписывали PASSED в этом сеансе
        self.last_passed_id: str | None = None

    # ----------------------------------------------------------
    def _set_status(self, msg, color="white"):
        if self.status_callback:
            self.status_callback(msg, color)
        else:
            print(msg)

    # ----------------------------------------------------------
    def _ensure_workbook(self):
        """
        Создаёт/открывает Excel-файл.
        Возвращает три листа:
            wb, основной ws, PASSED-лист ws_passed
        """
        if os.path.exists(self.xlsx_path):
            wb = load_workbook(self.xlsx_path)

            # основной лист
            ws = wb.active

            # PASSED лист – создать, если его ещё нет
            if "PASSED" in wb.sheetnames:
                ws_passed = wb["PASSED"]
            else:
                ws_passed = wb.create_sheet("PASSED")
                ws_passed.append(
                    [
                        "ID",
                        "UART",
                        "Voltage",
                        "U_bat",
                        "U_src",
                        "Current",
                        "I_crg",
                        "I_ch1",
                        "I_ch2",
                        "Charger",
                        "M_sens",
                        "L_sens",
                    ]
                )

            return wb, ws, ws_passed

        # ----- Если файла нет, создаём -----
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet"

        header = [
            "ID",
            "UART",
            "Voltage",
            "U_bat",
            "U_src",
            "Current",
            "I_crg",
            "I_ch1",
            "I_ch2",
            "Charger",
            "M_sens",
            "L_sens",
        ]
        ws.append(header)

        ws_passed = wb.create_sheet("PASSED")
        ws_passed.append(header)

        wb.save(self.xlsx_path)
        return wb, ws, ws_passed

    # ----------------------------------------------------------
    def _row_hex_color(self, color_matrix, row_idx: int) -> str | None:
        """
        Берёт цвет первой видимой цветной ячейки строки pyte.
        """
        if color_matrix is None:
            return None
        if not (0 <= row_idx < len(color_matrix)):
            return None

        row = color_matrix[row_idx]
        if not row:
            return None

        for c in row:
            if c:
                return c
        return None

    # ----------------------------------------------------------
    def _parse_frame(self, lines: list[str], color_matrix):
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
                term_hex = self._row_hex_color(color_matrix, row_idx)
                colors[0] = _excel_color_from_hex(term_hex)
                break

        # ---------- Остальные поля ----------
        rules = [
            ("UART", 1, "bracket"),
            ("Voltage", 2, "bracket"),
            ("U_bat", 3, "number"),
            ("U_src", 4, "number"),
            ("Current", 5, "bracket"),
            ("I_crg", 6, "number"),
            ("I_ch1", 7, "number"),
            ("I_ch2", 8, "number"),
            ("Charger", 9, "bracket"),
            ("M_sens", 10, "bracket"),
            ("L_sens", 11, "bracket"),
        ]

        for row_idx, ln in enumerate(plain_lines):
            if not ln.strip():
                continue

            for label, col_idx, mode in rules:
                if label not in ln:
                    continue

                term_hex = self._row_hex_color(color_matrix, row_idx)
                colors[col_idx] = _excel_color_from_hex(term_hex)

                if mode == "bracket":
                    m = re.search(r"\[([^\]]*)\]", ln)
                    if m:
                        values[col_idx] = m.group(1).strip()

                elif mode == "number":
                    m = re.search(rf"{re.escape(label)}\s+(-?\d+)", ln)
                    if m:
                        values[col_idx] = m.group(1).strip()

        return values, colors

    # ----------------------------------------------------------
    def save_block(self, lines: list[str], color_matrix=None, short_id=None, auto: bool = False):
        """
        Пишем TXT-лог и строку Excel.

        Режимы:
        - auto=False (ручное сохранение по кнопке):
            * если в кадре есть PASSED → запись в лист PASSED (один раз на ID)
            * иначе → запись в основной лист Sheet
        - auto=True (авто-сохранение при появлении PASSED):
            * если PASSED нет → Excel не трогаем, только TXT-лог
            * если PASSED есть → запись ТОЛЬКО в лист PASSED (один раз на ID)
        """
        if not lines:
            self._set_status("MPPT: нет блока для сохранения", "red")
            return

        ts = timestamp_str()
        plain = [strip_ansi(l) for l in lines]

        # ---------- TXT LOG (всегда) ----------
        os.makedirs(os.path.dirname(self.txt_path), exist_ok=True)
        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write("\n" + "-" * 50 + "\n")
            f.write(f"[{ts}]\n")
            for l in plain:
                f.write(l.rstrip() + "\n")
            f.write("-" * 50 + "\n")

        # ---------- Проверка PASSED по ВСЕМ строкам ----------
        is_passed = any("PASSED" in l.upper() for l in plain)

        # Авто-режим: если PASSED нет — Excel не трогаем
        if auto and not is_passed:
            self._set_status("MPPT: авто-сохранение — PASSED не найден, Excel пропущен", "yellow")
            return

        # ---------- Excel ----------
        wb, ws, ws_passed = self._ensure_workbook()

        values, colors = self._parse_frame(lines, color_matrix)

        # принудительная запись ID из short_id (из GUI)
        if short_id:
            values[0] = short_id.upper()
            colors[0] = "000000"

        cur_id = values[0]

        if is_passed:
            # строгая логика: если ID есть и уже использовался — пропускаем дубль
            if cur_id:
                if self.last_passed_id == cur_id:
                    #self._set_status(
                    #    f"MPPT: сохранено в лист PASSED", "green"
                    #)
                    return
                # новый ID → разрешаем и запоминаем
                self.last_passed_id = cur_id

            target_ws = ws_passed
        else:
            # обычная ручная запись (без PASSED)
            target_ws = ws

        # запись в конец выбранного листа
        row_idx = target_ws.max_row + 1

        for i, (val, col) in enumerate(zip(values, colors), start=1):
            cell = target_ws.cell(row=row_idx, column=i, value=val)
            cell.font = Font(color=col)

        try:
            wb.save(self.xlsx_path)

            if is_passed:
                self._set_status(f"MPPT: сохранено в лист PASSED (строка {row_idx})", "green")
            else:
                self._set_status(f"MPPT: блок сохранён (строка {row_idx})", "green")

        except PermissionError:
            # Excel-файл занят другой программой (обычно Excel)
            if is_passed:
                self._set_status(
                    f"MPPT: Excel-файл занят — PASSED для ID {cur_id} НЕ сохранён",
                    "red"
                )
            else:
                self._set_status(
                    f"MPPT: Excel-файл занят — сохранение пропущено",
                    "yellow"
                )

        except Exception as e:
            self._set_status(f"MPPT: ошибка сохранения Excel: {e}", "red")

