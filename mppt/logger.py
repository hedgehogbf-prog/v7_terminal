# mppt/logger.py
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
import os
import re
from util.fileutil import get_log_paths, timestamp_str
from util.ansi import strip_ansi


class MPPTLogger:
    def __init__(self, base_dir=None, status_callback=None):
        self.txt_path, self.xlsx_path = get_log_paths(base_dir)
        self.status_callback = status_callback

    def _set_status(self, msg, color="white"):
        if self.status_callback:
            self.status_callback(msg, color)
        else:
            print(msg)

    def _extract_excel_row(self, block: list[str]):
        """
        Пример простого парсинга:
        ожидаем 12 типичных строк, как у тебя:
        UART, U_bat, U_src, Voltage, I_crg, I_ch1, I_ch2,
        Current, Charger, M_sens, L_sens
        Если формат поменяется – нужно подстроить regex.
        """
        labels = [
            "UART", "U_bat", "U_src", "Voltage",
            "I_crg", "I_ch1", "I_ch2", "Current",
            "Charger", "M_sens", "L_sens"
        ]
        result = {k: "" for k in labels}

        for raw in block:
            plain = strip_ansi(raw)
            for lab in labels:
                if lab in plain:
                    if "[" in plain and "]" in plain:
                        m = re.search(r'\[([^\]]*)\]', plain)
                        if m:
                            result[lab] = m.group(1).strip()
                    else:
                        m = re.search(rf'\b{re.escape(lab)}\b\s*([^\s]+)', plain)
                        if m:
                            result[lab] = m.group(1).strip()
        return result

    def save_block(self, block: list[str]):
        if not block:
            self._set_status("MPPT: нет блока для сохранения", "red")
            return

        ts = timestamp_str()
        clean_block = [strip_ansi(l) for l in block]

        # TXT
        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write("\n" + "-" * 50 + "\n")
            f.write(f"[{ts}]\n")
            f.write("\n".join(clean_block))
            f.write("\n" + "-" * 50 + "\n")

        # Excel
        if os.path.exists(self.xlsx_path):
            wb = load_workbook(self.xlsx_path)
            ws = wb.active
        else:
            wb = Workbook()
            ws = wb.active
            ws.append([
                "№", "UART", "U_bat", "U_src", "Voltage", "I_crg",
                "I_ch1", "I_ch2", "Current", "Charger", "M_sens", "L_sens"
            ])

        next_num = ws.max_row  # первая строка – заголовок
        row_data = self._extract_excel_row(block)

        row_idx = ws.max_row + 1
        ws.cell(row=row_idx, column=1, value=next_num)

        cols = [
            "UART", "U_bat", "U_src", "Voltage",
            "I_crg", "I_ch1", "I_ch2", "Current",
            "Charger", "M_sens", "L_sens"
        ]
        for i, lab in enumerate(cols, start=2):
            cell = ws.cell(row=row_idx, column=i, value=row_data.get(lab, ""))
            cell.font = Font(color="FFFFFF")

        wb.save(self.xlsx_path)
        self._set_status(f"MPPT: блок сохранён как №{next_num}", "green")
