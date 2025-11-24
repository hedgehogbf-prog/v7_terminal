# mppt/logger.py — новая версия с записью в Excel по кадру экрана pyte
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
    - всё остальное (в т.ч. белый/жёлтый/синий) -> 000000 (чёрный)
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
        # txt + xlsx пути задаются через util.fileutil.get_log_paths
        self.txt_path, self.xlsx_path = get_log_paths(base_dir)
        self.status_callback = status_callback

    # ----------------------------------------------------------
    def _set_status(self, msg, color="white"):
        if self.status_callback:
            self.status_callback(msg, color)
        else:
            print(msg)

    # ----------------------------------------------------------
    def _ensure_workbook(self):
        """
        Гарантируем наличие xlsx-файла.
        Если его нет — создаём с первой строкой-заголовком.
        """
        if os.path.exists(self.xlsx_path):
            wb = load_workbook(self.xlsx_path)
            ws = wb.active
            return wb, ws

        wb = Workbook()
        ws = wb.active
        # Заголовок – можно потом отредактировать вручную
        ws.append([
            "ID",       # 1
            "UART",     # 2
            "Voltage",  # 3
            "U_bat",    # 4
            "U_src",    # 5
            "Current",  # 6
            "I_crg",    # 7
            "I_ch1",    # 8
            "I_ch2",    # 9
            "Charger",  # 10
            "M_sens",   # 11
            "L_sens",   # 12
        ])
        wb.save(self.xlsx_path)
        return wb, ws

    # ----------------------------------------------------------
    def _row_hex_color(self, color_matrix, row_idx: int) -> str | None:
        """
        Берём цвет строки из last_colors CanvasTerminal.
        color_matrix – это self.canvas_term.last_colors: список списков "#RRGGBB".
        """
        if color_matrix is None:
            return None
        if not (0 <= row_idx < len(color_matrix)):
            return None
        row = color_matrix[row_idx]
        if not row:
            return None
        # первый ненулевой цвет в строке
        for c in row:
            if c:
                return c
        return None

    # ----------------------------------------------------------
    def _parse_frame(self, lines: list[str], color_matrix):
        """
        Парсинг кадра (18 строк pyte.get_lines()) в:
        - values[0..11]   — значения для 12 столбцов Excel
        - colors[0..11]   — цвета шрифта в Excel ("RRGGBB")

        Соответствие столбцов:
        1  -> ID (без "ID:")
        2  -> UART        [ ... ]
        3  -> Voltage     [ ... ]
        4  -> U_bat       число
        5  -> U_src       число
        6  -> Current     [ ... ]
        7  -> I_crg       число
        8  -> I_ch1       число
        9  -> I_ch2       число
        10 -> Charger     [ ... ]
        11 -> M_sens      [ ... ]
        12 -> L_sens      [ ... ]
        """
        # 12 столбцов, по умолчанию пустые/чёрные
        values: list[str] = ["" for _ in range(12)]
        colors: list[str] = ["000000" for _ in range(12)]

        plain_lines = [strip_ansi(l) for l in lines]

        # ---------- Столбец 1: ID (из "ID:XXXX") ----------
        id_pattern = re.compile(r"ID:([0-9A-Fa-f]{4})")
        for row_idx, line in enumerate(plain_lines):
            m = id_pattern.search(line)
            if m:
                values[0] = m.group(1).upper()
                term_hex = self._row_hex_color(color_matrix, row_idx)
                colors[0] = _excel_color_from_hex(term_hex)
                break

        # ---------- Остальные столбцы по меткам ----------
        # режим:
        #   "bracket" — берём текст внутри [...]
        #   "number"  — берём число после метки
        rules = [
            ("UART",    1, "bracket"),
            ("Voltage", 2, "bracket"),
            ("U_bat",   3, "number"),
            ("U_src",   4, "number"),
            ("Current", 5, "bracket"),
            ("I_crg",   6, "number"),
            ("I_ch1",   7, "number"),
            ("I_ch2",   8, "number"),
            ("Charger", 9, "bracket"),
            ("M_sens",  10, "bracket"),
            ("L_sens",  11, "bracket"),
        ]

        for row_idx, line in enumerate(plain_lines):
            if not line.strip():
                continue

            for label, col_idx, mode in rules:
                if label not in line:
                    continue

                term_hex = self._row_hex_color(color_matrix, row_idx)
                colors[col_idx] = _excel_color_from_hex(term_hex)

                if mode == "bracket":
                    m = re.search(r"\[([^\]]*)\]", line)
                    if m:
                        values[col_idx] = m.group(1).strip()
                elif mode == "number":
                    # ищем целое число после метки
                    m = re.search(rf"{re.escape(label)}\s+(-?\d+)", line)
                    if m:
                        values[col_idx] = m.group(1).strip()

        return values, colors

    # ----------------------------------------------------------
    def save_block(self, lines: list[str], color_matrix=None, short_id=None):
        """
        Основной метод:
        - пишет TXT-лог (чистый текст без ANSI)
        - добавляет строку в Excel

        lines        — список строк экрана (pyte.get_lines())
        color_matrix — матрица цветов CanvasTerminal.last_colors ("#RRGGBB")
        """
        if not lines:
            self._set_status("MPPT: нет блока для сохранения", "red")
            return

        ts = timestamp_str()
        clean_block = [strip_ansi(l) for l in lines]

        # ---------- TXT-лог ----------
        os.makedirs(os.path.dirname(self.txt_path), exist_ok=True)
        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write("\n" + "-" * 50 + "\n")
            f.write(f"[{ts}]\n")
            for l in clean_block:
                f.write(l.rstrip() + "\n")
            f.write("-" * 50 + "\n")

        # ---------- Excel ----------
        wb, ws = self._ensure_workbook()

        values, colors = self._parse_frame(lines, color_matrix)
        
        # --- ПРИНУДИТЕЛЬНАЯ запись ID из short_id (если был передан из GUI) ---
        if short_id:
            values[0] = short_id.upper()
            colors[0] = "000000"  # всегда чёрный
        # дописываем в конец
        row_idx = ws.max_row + 1

        for i, (val, col) in enumerate(zip(values, colors), start=1):
            cell = ws.cell(row=row_idx, column=i, value=val)
            cell.font = Font(color=col)

        wb.save(self.xlsx_path)
        self._set_status(f"MPPT: блок сохранён (строка {row_idx})", "green")
