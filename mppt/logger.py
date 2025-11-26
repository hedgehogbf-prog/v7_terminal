# mppt/logger.py — версия с записью в Excel, авто-записью PASSED и интеграцией с Git
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
import os
import re

from util.fileutil import get_log_paths, timestamp_str
from util.ansi import strip_ansi
from mppt.terminal_pyte import PYTE_FG_TO_HEX

# --- Git интеграция ---
GIT_REMOTE_URL = "http://dis-electronics:30000/scheck/swmpptv7_10a_rev1_reject.git"  # TODO: поменять на свой URL

try:
    from git import Repo, GitCommandError  # type: ignore
except Exception:  # GitPython не установлен или иная проблема
    Repo = None  # type: ignore
    GitCommandError = Exception  # type: ignore


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

        # каталог логов = корень git-репозитория
        self.log_dir = os.path.dirname(self.txt_path)
        self.repo = None  # type: ignore

        # инициализация Git (если GitPython установлен)
        self._init_git_repo()


    # ----------------------------------------------------------
    # Статус
    # ----------------------------------------------------------
    def _set_status(self, msg, color="white"):
        if self.status_callback:
            self.status_callback(msg, color)
        else:
            print(msg)

    # ----------------------------------------------------------
    # Git: инициализация
    # ----------------------------------------------------------
    def _init_git_repo(self):
        """
        Инициализируем / подключаем git-репозиторий в каталоге логов.

        Логика:
        - если GitPython недоступен → тихо выходим (git отключён);
        - если .git уже есть → открываем существующий Repo;
        - если .git нет:
            * если каталог пустой и задан GIT_REMOTE_URL → клонируем;
            * иначе → создаём локальный репозиторий (git init),
                      и, если задан GIT_REMOTE_URL, настраиваем origin.
        """
        if Repo is None:
            # GitPython не установлен — git-функции недоступны
            self._set_status("Git: GitPython не установлен — git интеграция отключена", "yellow")
            return

        try:
            os.makedirs(self.log_dir, exist_ok=True)
            git_dir = os.path.join(self.log_dir, ".git")

            if os.path.isdir(git_dir):
                from git import Repo as _Repo  # type: ignore
                self.repo = _Repo(self.log_dir)
                self._set_status("Git: локальный репозиторий найден", "white")
                return

            # .git нет — нужно решить, клонировать или init
            entries = [
                name
                for name in os.listdir(self.log_dir)
                if not name.startswith(".")
            ]

            from git import Repo as _Repo  # type: ignore

            if not entries and GIT_REMOTE_URL:
                # каталог пустой → можно безопасно клонировать
                self._set_status(f"Git: клонирую {GIT_REMOTE_URL} → {self.log_dir}", "white")
                self.repo = _Repo.clone_from(GIT_REMOTE_URL, self.log_dir)
                self._set_status("Git: клон успешно создан", "green")
            else:
                # каталог не пустой или нет URL → просто init
                self.repo = _Repo.init(self.log_dir)
                self._set_status("Git: локальный репозиторий инициализирован", "white")

                # если задан URL и нет origin — добавим remote
                if GIT_REMOTE_URL and "origin" not in [r.name for r in self.repo.remotes]:
                    self.repo.create_remote("origin", GIT_REMOTE_URL)
                    self._set_status(f"Git: remote 'origin' добавлен → {GIT_REMOTE_URL}", "white")

        except Exception as e:
            self.repo = None
            self._set_status(f"Git: отключён (ошибка инициализации: {e})", "yellow")

    # ----------------------------------------------------------
    # Git: pull при старте
    # ----------------------------------------------------------
    def _git_pull_on_start(self):
        """Пробуем подтянуть изменения с origin при старте."""
        if self.repo is None:
            return

        try:
            remotes = {r.name: r for r in self.repo.remotes}
        except Exception:
            return

        if "origin" not in remotes:
            # нет удалённого репозитория — нечего пуллить
            return

        origin = remotes["origin"]

        try:
            self._set_status("Git: pull origin (ff-only)...", "white")
            # fast-forward only, чтобы не плодить merge-коммиты
            self.repo.git.pull("--ff-only", origin.name)
            self._set_status("Git: pull завершён", "green")
        except GitCommandError as e:  # type: ignore
            # Не ломаем программу, просто предупреждаем
            self._set_status(f"Git: pull не удался: {e}", "yellow")
        except Exception as e:
            self._set_status(f"Git: общая ошибка pull: {e}", "yellow")

    # ----------------------------------------------------------
    # Git: commit
    # ----------------------------------------------------------
    def git_commit_logs(self, message: str | None = None):
        """
        Добавляем txt/xlsx лог в индекс и делаем commit.
        Вызывается из GUI по кнопке "Commit".
        """
        if self.repo is None:
            self._set_status("Git: репозиторий не инициализирован", "yellow")
            return

        try:
            # относительные пути относительно корня репозитория
            rel_txt = os.path.relpath(self.txt_path, self.log_dir)
            rel_xlsx = os.path.relpath(self.xlsx_path, self.log_dir)

            to_add = []
            if os.path.exists(self.txt_path):
                to_add.append(rel_txt)
            if os.path.exists(self.xlsx_path):
                to_add.append(rel_xlsx)

            if not to_add:
                self._set_status("Git: нет файлов логов для commit", "white")
                return

            self.repo.index.add(to_add)

            if message is None:
                from datetime import datetime
                message = f"MPPT logs {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            if self.repo.is_dirty(index=True, working_tree=True, untracked_files=True):
                self.repo.index.commit(message)
                self._set_status("Git: изменения закоммичены", "green")
            else:
                self._set_status("Git: нет изменений для commit", "white")

        except Exception as e:
            self._set_status(f"Git: ошибка commit: {e}", "red")

    # ----------------------------------------------------------
    # Git: push
    # ----------------------------------------------------------
    def git_push(self):
        """
        Отправляем локальные коммиты на origin.
        Вызывается из GUI по кнопке "Push".
        """
        if self.repo is None:
            self._set_status("Git: репозиторий не инициализирован", "yellow")
            return

        try:
            remotes = {r.name: r for r in self.repo.remotes}
        except Exception:
            self._set_status("Git: не удалось прочитать список remotes", "red")
            return

        if "origin" not in remotes:
            self._set_status("Git: remote 'origin' не настроен", "yellow")
            return

        origin = remotes["origin"]

        try:
            self._set_status("Git: push origin...", "white")
            origin.push()
            self._set_status("Git: push завершён", "green")

        except GitCommandError as e:  # type: ignore
            msg = str(e)
            if "non-fast-forward" in msg or "non fast-forward" in msg:
                self._set_status(
                    "Git: push отклонён (внешний репозиторий изменился). "
                    "Сделайте pull и решите конфликты вручную.",
                    "red",
                )
            else:
                self._set_status(f"Git: ошибка push: {e}", "red")
        except Exception as e:
            self._set_status(f"Git: общая ошибка push: {e}", "red")
            
            
    # ----------------------------------------------------------
    # Git: UI-friendly pull wrapper (вызов из GUI)
    # ----------------------------------------------------------
    def _git_pull_on_start_ui(self):
        """
        Вызывается из GUI после полной инициализации интерфейса.
        Выполняет pull и отправляет сообщения в статусбар,
        не выводя ничего в терминал VS Code.
        """
        try:
            self._set_status("Git: pull origin (ff-only)...", "white")
            self._git_pull_on_start()
        except Exception as e:
            self._set_status(f"Git: ошибка pull: {e}", "red")


    # ----------------------------------------------------------
    # Вспомогательные методы парсинга / Excel
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
    # Основной метод сохранения
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
                    self._set_status(
                        f"MPPT: PASSED уже был записан для ID {cur_id} — пропуск",
                        "yellow",
                    )
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

        # попытка сохранить Excel (защита от PermissionError, если файл открыт)
        try:
            wb.save(self.xlsx_path)

            if is_passed:
                self._set_status(
                    f"MPPT: сохранено в лист PASSED (строка {row_idx})",
                    "green",
                )
            else:
                self._set_status(
                    f"MPPT: блок сохранён (строка {row_idx})",
                    "green",
                )

        except PermissionError:
            # Excel-файл занят другой программой (обычно Excel)
            if is_passed:
                self._set_status(
                    f"MPPT: Excel-файл занят — PASSED для ID {cur_id} НЕ сохранён",
                    "red",
                )
            else:
                self._set_status(
                    "MPPT: Excel-файл занят — запись пропущена",
                    "yellow",
                )

        except Exception as e:
            self._set_status(f"MPPT: ошибка сохранения Excel: {e}", "red")
