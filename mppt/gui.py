# mppt/gui.py — панель MPPT с автоподключением, Excel-логированием и отдельным Git-status-bar
from __future__ import annotations

import threading
import time
import re
import zlib
from typing import Optional

from tkinter import (
    Frame,
    BOTH,
    TOP,
    X,
    LEFT,
    BOTTOM,
    Button,
    StringVar,
    Label,
    Canvas,
)
from tkinter import ttk

from mppt.serial_auto import SerialAuto
from mppt.logger import MPPTLogger
from util.ansi import strip_ansi
from mppt.terminal_pyte import PyteTerminal
from mppt.terminal_canvas import CanvasTerminal


def extract_com_number(text: str) -> str:
    """Извлекает 'COMxx' из строки вида 'Something (COMxx)'. Если не найдено – возвращает исходную строку."""
    m = re.search(r"(COM\d+)", text)
    if m:
        return m.group(1)
    return text


class MPPTTerminalPanel(Frame):
    """
    Панель MPPT-терминала:
    - буферизация по кадрам между ESC[2J]
    - универсальная маскировка UID → ID:XXXX
    - кнопка "+" с удержанием
    - авто-сохранение в Excel при появлении PASSED (через MPPTLogger.save_block(auto=True))
    - кнопки Git: Commit и Push
    - отдельный Git-status-bar (нижняя строка в панели)
    """

    # UID: строго 4 группы, разделённые "-", группы — любые символы кроме пробела, CR, LF и "-"
    UID_REGEX = re.compile(r"\x1b\[0m\s*([^- \r\n]+-[^- \r\n]+-[^- \r\n]+-[^- \r\n]+)")
    ESC_CLEAR = "\x1b[2J"

    def __init__(self, master, bg: str = "#202124", fg: str = "#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg
        self.autoconnect_enabled = True  # автоконнект включён, пока пользователь не нажмёт Disconnect

        # Короткий ID для текущего кадра (CRC16 от UID-строки)
        self.device_short_id: Optional[str] = None

        # Буфер текущего кадра (между ESC[2J])
        self._frame_buf: str = ""

        # ---------------- Верхняя панель ----------------
        top = Frame(self, bg=bg)
        top.pack(side=TOP, fill=X)

        Label(top, text="COM MPPT:", bg=bg, fg=fg).pack(side=TOP, anchor="w")

        # Широкий COM-Combobox
        self.port_var = StringVar()

        self.combo_port = ttk.Combobox(
            top,
            textvariable=self.port_var,
            width=50,
            state="readonly",
        )
        self.combo_port.pack(side=TOP, fill=X, pady=2)

        # ряд кнопок под комбобоксом
        btn_row = Frame(top, bg=bg)
        btn_row.pack(side=TOP, fill=X, pady=(2, 4))

        btn_rescan = Button(
            btn_row,
            text="Обновить",
            command=self.rescan_ports,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        btn_rescan.pack(side=LEFT, padx=2)

        self.btn_connect = Button(
            btn_row,
            text="Connect",
            command=self.toggle_connect,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_connect.pack(side=LEFT, padx=2)

        self.btn_save = Button(
            btn_row,
            text="Save block",
            command=self.save_block,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_save.pack(side=LEFT, padx=2)

        # Кнопка "+" (удержание)
        self._plus_running = False
        self.btn_plus = Button(
            btn_row,
            text="+",
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
            width=4,
        )
        self.btn_plus.pack(side=LEFT, padx=2)
        self.btn_plus.bind("<ButtonPress-1>", lambda e: self._plus_press())
        self.btn_plus.bind("<ButtonRelease-1>", lambda e: self._plus_release())

        # Git-кнопки
        self.btn_commit = Button(
            btn_row,
            text="Commit",
            command=self._git_commit_click,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_commit.pack(side=LEFT, padx=2)

        self.btn_push = Button(
            btn_row,
            text="Push",
            command=self._git_push_click,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_push.pack(side=LEFT, padx=2)

        # ---------------- Canvas-терминал ----------------
        self.canvas = Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        # ---------------- Git-status-bar (отдельный) ----------------
        # Основной статусбар задаётся снаружи через set_global_status,
        # а этот — только для Git-сообщений.
        self.git_status_label = Label(
            self,
            text="",
            bg=bg,
            fg="#85c1ff",
            anchor="w",
            justify="left",
            wraplength=400   # ← можно изменить под ширину твоего окна
        )

        # Вариант 3: в самом низу панели
        self.git_status_label.pack(side=BOTTOM, fill=X, padx=4, pady=(0, 4))

        # ---------------- Логика терминала ----------------
        self.serial = SerialAuto(baudrate=115200)
        self.term = PyteTerminal(cols=64, rows=18)
        self.canvas_term = CanvasTerminal(
            self.canvas,
            self.term,
            cols=64,
            rows=18,
            bg=bg,
            font_name="Consolas",
            font_size=11,
        )

        self.logger = MPPTLogger(status_callback=self._set_status_stub)
        # назначаем GUI status_callback (дублируется позже в set_global_status)
        self.logger.status_callback = self._set_status_stub
        # и отдельный Git-status
        self.logger.git_status_callback = self._set_git_status

        # вызываем git pull уже после появления интерфейса
        self.after(200, self.logger._git_pull_on_start_ui)

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._render_scheduled = False

        self.rescan_ports()
        self.after(500, self._autoconnect_loop)

    # --------------------------------------------------------------
    # Статус
    # --------------------------------------------------------------
    def _set_status_stub(self, msg: str, color: str = "white") -> None:
        """
        Заглушка статуса: по умолчанию печатает в консоль.
        В реальном приложении заменяется через set_global_status().
        """
        print(msg)

    def _set_git_status(self, msg: str, color: str = "#85c1ff") -> None:
        """Обновление отдельного Git-status-bar внизу панели."""
        self.git_status_label.config(text=msg, fg=color)

    def set_global_status(self, status_func) -> None:
        """
        Вызывается AppLayout'ом, чтобы передать общий статусбар.
        """
        self._set_status_stub = status_func
        self.logger.status_callback = status_func

    # --------------------------------------------------------------
    # Работа с портами
    # --------------------------------------------------------------
    def rescan_ports(self) -> None:
        """Обновляет список COM-портов с читаемым описанием."""
        ports = self.serial.list_ports()
        labels = []

        for p in ports:
            desc = p.description or p.hwid or "Неизвестное устройство"
            # убираем "(COMxx)" из description, если Windows уже так делает
            if f"({p.device})" in desc:
                desc = desc.replace(f" ({p.device})", "")

            label = f"{desc} ({p.device})"
            labels.append(label)

        self.combo_port["values"] = labels

        if self.serial.current_port:
            cur = self.serial.current_port
            for lbl in labels:
                if cur in lbl:
                    self.port_var.set(lbl)
                    break
        elif labels:
            self.port_var.set(labels[0])
        else:
            self.port_var.set("")
            self.combo_port["values"] = []

        self._set_status_stub("Порты MPPT обновлены", "green")

    def rescan_ports_external(self) -> None:
        """Внешний вызов из других частей GUI."""
        self.rescan_ports()

    # --------------------------------------------------------------
    # Автоконнект
    # --------------------------------------------------------------
    def _autoconnect_loop(self) -> None:
        if not self.autoconnect_enabled:
            self.after(500, self._autoconnect_loop)
            return

        if not self.running:
            port_display = self.port_var.get().strip() or None
            port = extract_com_number(port_display) if port_display else None

            if self.serial.ensure(port):
                self.running = True
                self.btn_connect.config(text=f"Disconnect ({self.serial.current_port})")
                self._set_status_stub(f"Автоподключено к {self.serial.current_port}", "green")
                self.thread = threading.Thread(target=self._reader_loop, daemon=True)
                self.thread.start()

        self.after(500, self._autoconnect_loop)

    # --------------------------------------------------------------
    # Ручное подключение
    # --------------------------------------------------------------
    def toggle_connect(self) -> None:
        # ======= ОТКЛЮЧЕНИЕ =======
        if self.running:
            self.running = False
            # пользователь явно отключил — автоконнект выключаем
            self.autoconnect_enabled = False

            try:
                self.serial.close()
            except Exception as e:
                self._set_status_stub(f"Ошибка при отключении: {e}", "red")
            else:
                self._set_status_stub("COM порт отключён", "yellow")

            self.btn_connect.config(text="Connect")
            return

        # ======= ПОДКЛЮЧЕНИЕ =======
        # пользователь хочет подключиться — автоконнект включаем
        self.autoconnect_enabled = True

        port_display = self.port_var.get().strip()
        port = extract_com_number(port_display)

        if not self.serial.ensure(port):
            self.running = False
            self.btn_connect.config(text="Connect")
            self._set_status_stub(f"Не удалось открыть порт: {port}", "red")
            return

        if not port:
            self.port_var.set(self.serial.current_port)

        self.running = True
        self.btn_connect.config(text=f"Disconnect ({self.serial.current_port})")
        self._set_status_stub(f"Подключено к {self.serial.current_port}", "green")

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    # --------------------------------------------------------------
    # Обработка потери порта
    # --------------------------------------------------------------
    def _on_port_lost(self, msg: str) -> None:
        """Обработчик потери COM-порта (вызывается из GUI-потока)."""
        self.running = False
        # автоконнект НЕ выключаем — пусть дальше пытается переподключиться
        try:
            self.serial.close()
        except Exception:
            pass

        self.btn_connect.config(text="Connect")
        self._set_status_stub(msg, "red")

    # --------------------------------------------------------------
    # Чтение UART + буферизация по кадрам (между ESC[2J])
    # --------------------------------------------------------------
    def _reader_loop(self) -> None:
        esc = self.ESC_CLEAR

        while self.running and self.serial.ser:
            try:
                data = self.serial.ser.read_all()
            except Exception:
                msg = f"COM-порт {self.serial.current_port or ''} недоступен (устройство отключено?)"
                self.after(0, lambda m=msg: self._on_port_lost(m))
                break

            if not data:
                time.sleep(0.01)
                continue

            chunk = data.decode(errors="ignore").replace("\x00", "")
            if not chunk:
                continue

            buf = chunk

            # Разбираем текущий chunk на части относительно ESC[2J]
            while True:
                idx = buf.find(esc)
                if idx == -1:
                    # в этом куске больше нет ESC[2J] — просто добавляем остаток в текущий кадр
                    self._frame_buf += buf
                    break

                # всё до ESC[2J] — хвост предыдущего кадра
                prefix = buf[:idx]
                if prefix:
                    self._frame_buf += prefix

                # если в буфере уже что-то есть — это завершённый кадр
                if self._frame_buf:
                    self._process_full_frame(self._frame_buf)

                # начинаем новый кадр: кладём ESC[2J] как начало
                self._frame_buf = esc

                # обрезаем обработанную часть + ESC[2J]
                buf = buf[idx + len(esc):]

    # --------------------------------------------------------------
    # Обработка завершённого кадра
    # --------------------------------------------------------------
    def _process_full_frame(self, frame_text: str) -> None:
        """
        На вход приходит ПОЛНЫЙ кадр, начинающийся с ESC[2J] и заканчивающийся
        перед следующим ESC[2J].
        """
        # --- 1. UID → short ID ---
        m = self.UID_REGEX.search(frame_text)

        if not m:
            # В этом кадре UID нет — ID для этого кадра отсутствует
            self.device_short_id = None
        else:
            full_uid = m.group(1)  # например "7-c-32305311-20383346" или любой другой вариант

            # CRC считаем по UID как по строке (ASCII)
            uid_bytes = full_uid.encode("ascii", errors="ignore")
            crc = zlib.crc32(uid_bytes) & 0xFFFF
            short = f"{crc:04X}"

            self.device_short_id = short
            start, end = m.span()
            masked = f"ID:{short}".ljust(end - start)
            frame_text = frame_text[:start] + masked + frame_text[end:]

        # --- 2. Кормим pyte целым кадром ---
        self.term.feed(frame_text)

        # --- 3. Авто-PASSED-сохранение ---
        try:
            lines = self.term.get_lines()
        except Exception:
            lines = []

        has_passed = False
        if lines:
            plain_lines = [strip_ansi(l) for l in lines]
            for ln in plain_lines:
                if "PASSED" in ln.upper():
                    has_passed = True
                    break

        if has_passed:
            self.logger.save_block(
                lines,
                getattr(self.canvas_term, "last_colors", None),
                self.device_short_id,
                auto=True,
            )

        # --- 4. Обновляем UI ---
        self._schedule_render()

    # --------------------------------------------------------------
    # Кнопка "+"
    # --------------------------------------------------------------
    def _plus_press(self) -> None:
        """Начать непрерывную отправку '+' при удержании кнопки."""
        if not self.running or not self.serial.ser:
            return

        if self._plus_running:
            return

        self._plus_running = True

        def worker():
            while self._plus_running and self.running and self.serial.ser:
                try:
                    self.serial.ser.write(b"+")
                except Exception:
                    break
                time.sleep(0.07)

        threading.Thread(target=worker, daemon=True).start()

    def _plus_release(self) -> None:
        """Остановить поток отправки '+' и отправить один '+' при отпускании."""
        self._plus_running = False

        try:
            if self.running and self.serial.ser:
                self.serial.ser.write(b"+")
        except Exception:
            pass

    # --------------------------------------------------------------
    # Git-кнопки
    # --------------------------------------------------------------
    def _git_commit_click(self) -> None:
        """Обработчик кнопки Commit — делаем git commit логов."""
        try:
            self.logger.git_commit_logs()
        except Exception as e:
            self._set_git_status(f"Git: ошибка при commit: {e}", "red")

    def _git_push_click(self) -> None:
        """Обработчик кнопки Push — делаем git push."""
        try:
            self.logger.git_push()
        except Exception as e:
            self._set_git_status(f"Git: ошибка при push: {e}", "red")

    # --------------------------------------------------------------
    # Рендер
    # --------------------------------------------------------------
    def _schedule_render(self) -> None:
        if self._render_scheduled:
            return
        self._render_scheduled = True
        self.after(0, self._do_render)

    def _do_render(self) -> None:
        self._render_scheduled = False
        if not self.running:
            return

        self.canvas_term.render_diff()

    # --------------------------------------------------------------
    # Ручное логирование
    # --------------------------------------------------------------
    def save_block(self) -> None:
        """
        Сохраняем текущий экран по кнопке:
        - lines  — строки pyte (без ANSI)
        - colors — матрица цветов из CanvasTerminal.last_colors
        """
        lines = self.term.get_lines()
        color_matrix = getattr(self.canvas_term, "last_colors", None)
        self.logger.save_block(lines, color_matrix, self.device_short_id)
