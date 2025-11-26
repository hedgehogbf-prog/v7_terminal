# mppt/gui.py — версия с буферизацией по кадрам, авто-PASSED и интеграцией с Git (Commit / Push)
# -----------------------------------------------------------

import threading
import time
import re
import zlib
from tkinter import (
    Frame,
    BOTH,
    TOP,
    X,
    LEFT,
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


class MPPTTerminalPanel(Frame):
    """
    Панель MPPT-терминала:
    - буферизация по кадрам между ESC[2J]
    - универсальная маскировка UID → ID:XXXX
    - кнопка "+" с удержанием
    - авто-сохранение в Excel при появлении PASSED (строго через MPPTLogger.save_block(auto=True))
    - кнопки Git: Commit и Push
    """

    # UID: строго 4 группы, разделённые "-", группы — любые символы кроме пробела, CR, LF и самого "-"
    # Формат: <grp1>-<grp2>-<grp3>-<grp4>, длины любых групп могут быть любыми
    UID_REGEX = re.compile(r"\x1b\[0m\s*([^- \r\n]+-[^- \r\n]+-[^- \r\n]+-[^- \r\n]+)")

    ESC_CLEAR = "\x1b[2J"

    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        # Короткий ID для текущего кадра (CRC16 от UID-строки)
        self.device_short_id: str | None = None

        # Буфер текущего кадра (между ESC[2J])
        self._frame_buf: str = ""

        # ---------------- Верхняя панель ----------------
        top = Frame(self, bg=bg)
        top.pack(side=TOP, fill=X)

        self.port_var = StringVar()

        Label(top, text="COM MPPT:", bg=bg, fg=fg).pack(side=LEFT, padx=(4, 2))

        self.combo_port = ttk.Combobox(
            top,
            textvariable=self.port_var,
            width=18,
            state="readonly",
        )
        self.combo_port.pack(side=LEFT, padx=2, pady=4)

        btn_rescan = Button(
            top,
            text="Обновить",
            command=self.rescan_ports,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        btn_rescan.pack(side=LEFT, padx=2, pady=4)

        self.btn_connect = Button(
            top,
            text="Connect",
            command=self.toggle_connect,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_connect.pack(side=LEFT, padx=4, pady=4)

        self.btn_save = Button(
            top,
            text="Save block",
            command=self.save_block,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_save.pack(side=LEFT, padx=4, pady=4)

        # ---------------- Кнопка "+" ----------------
        self._plus_running = False

        self.btn_plus = Button(
            top,
            text="+",
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
            width=4,
        )
        self.btn_plus.pack(side=LEFT, padx=4, pady=4)

        self.btn_plus.bind("<ButtonPress-1>", lambda e: self._plus_press())
        self.btn_plus.bind("<ButtonRelease-1>", lambda e: self._plus_release())

        # ---------------- Git-кнопки ----------------
        self.btn_commit = Button(
            top,
            text="Commit",
            command=self._git_commit_click,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_commit.pack(side=LEFT, padx=4, pady=4)

        self.btn_push = Button(
            top,
            text="Push",
            command=self._git_push_click,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg,
        )
        self.btn_push.pack(side=LEFT, padx=4, pady=4)

        # ---------------- Canvas-терминал ----------------
        self.canvas = Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

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

                # назначаем GUI status_callback (ты уже это делаешь в set_global_status)
        self.logger.status_callback = self._set_status_stub

        # вызываем pull уже после появления интерфейса
        self.after(200, self.logger._git_pull_on_start_ui)

        self.running = False
        self.thread = None
        self._render_scheduled = False

        self.rescan_ports()
        self.after(500, self._autoconnect_loop)

    # --------------------------------------------------------------
    # Статус
    # --------------------------------------------------------------
    def _set_status_stub(self, msg, color="white"):
        print(msg)

    def set_global_status(self, status_func):
        self._set_status_stub = status_func
        self.logger.status_callback = status_func

    # --------------------------------------------------------------
    # Работа с портами
    # --------------------------------------------------------------
    def rescan_ports(self):
        ports = self.serial.list_ports()
        devs = [p.device for p in ports]

        self.combo_port["values"] = devs
        if devs:
            if self.port_var.get() not in devs:
                self.port_var.set(devs[0])
        else:
            self.port_var.set("")
            self.combo_port["values"] = []

    def rescan_ports_external(self):
        self.rescan_ports()

    # --------------------------------------------------------------
    # Автоконнект
    # --------------------------------------------------------------
    def _autoconnect_loop(self):
        if not self.running:
            port = self.port_var.get().strip() or None
            if self.serial.ensure(port):
                self.running = True
                self.btn_connect.config(
                    text=f"Disconnect ({self.serial.current_port})"
                )
                self.thread = threading.Thread(
                    target=self._reader_loop, daemon=True
                )
                self.thread.start()

        self.after(500, self._autoconnect_loop)

    # --------------------------------------------------------------
    # Ручное подключение
    # --------------------------------------------------------------
    def toggle_connect(self):
        if self.running:
            self.running = False
            self.serial.close()
            self.btn_connect.config(text="Connect")
            return

        port = self.port_var.get().strip()
        if not self.serial.ensure(port):
            return

        if not port:
            self.port_var.set(self.serial.current_port)

        self.running = True
        self.btn_connect.config(text=f"Disconnect ({self.serial.current_port})")

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()


    # --------------------------------------------------------------
    # Чтение UART + буферизация по кадрам (между ESC[2J])
    # --------------------------------------------------------------
    def _reader_loop(self):
        esc = self.ESC_CLEAR

        while self.running and self.serial.ser:
            try:
                data = self.serial.ser.read_all()
            except Exception:
                self.running = False
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
    def _process_full_frame(self, frame_text: str):
        """
        На вход приходит ПОЛНЫЙ кадр, начинающийся с ESC[2J] и заканчивающийся
        перед следующим ESC[2J].

        Логика:
        - ищем UID формата <grp1>-<grp2>-<grp3>-<grp4>
        - если UID найден → считаем CRC16 по строке UID и заменяем UID на ID:XXXX
        - если UID НЕ найден → очищаем device_short_id
        - кормим pyte целым кадром
        - после обновления терминала ищем PASSED во всём кадре и, если он есть,
          вызываем logger.save_block(..., auto=True) — это и решает, куда писать
        """
        # --- 1. UID → short ID ---
        m = self.UID_REGEX.search(frame_text)

        if not m:
            # В этом кадре UID нет — ID для этого кадра отсутствует
            self.device_short_id = None
        else:
            full_uid = m.group(1)  # например "7-c-32305311-20383346" или любой другой вариант

            # CRC считаем по UID как по строке (ASCII), без доп. предположений
            uid_bytes = full_uid.encode("ascii", errors="ignore")
            crc = zlib.crc32(uid_bytes) & 0xFFFF
            short = f"{crc:04X}"

            self.device_short_id = short
            #print(f"[ID DEBUG] Calculated ID for frame: {short}   from UID={full_uid}")
            start, end = m.span()
            masked = f"ID:{short}".ljust(end - start)
            frame_text = frame_text[:start] + masked + frame_text[end:]

        # --- 2. Кормим pyte целым кадром ---
        self.term.feed(frame_text)

        # --- 3. Авто-PASSED-сохранение (жёсткая логика, через logger) ---
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
            #print("[AUTO-PASSED] TRIGGERED in _process_full_frame")

            self.logger.save_block(
                lines,
                getattr(self.canvas_term, "last_colors", None),
                self.device_short_id,
                auto=True,  # <- включает режим "только PASSED в Excel, с защитой по ID"
            )

        # --- 4. Обновляем UI ---
        self._schedule_render()

    # --------------------------------------------------------------
    # Кнопка "+"
    # --------------------------------------------------------------
    def _plus_press(self):
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
                time.sleep(0.07)  # период повторения при удержании

        threading.Thread(target=worker, daemon=True).start()

    def _plus_release(self):
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
    def _git_commit_click(self):
        """Обработчик кнопки Commit — делаем git commit логов."""
        try:
            self.logger.git_commit_logs()
        except Exception as e:
            # на всякий случай, чтобы GUI не падал
            self._set_status_stub(f"Git: ошибка при commit: {e}", "red")

    def _git_push_click(self):
        """Обработчик кнопки Push — делаем git push."""
        try:
            self.logger.git_push()
        except Exception as e:
            self._set_status_stub(f"Git: ошибка при push: {e}", "red")

    # --------------------------------------------------------------
    # Рендер
    # --------------------------------------------------------------
    def _schedule_render(self):
        if self._render_scheduled:
            return
        self._render_scheduled = True
        self.after(0, self._do_render)

    def _do_render(self):
        self._render_scheduled = False
        if not self.running:
            return

        # обновление отображения
        self.canvas_term.render_diff()

    # --------------------------------------------------------------
    # Логирование (ручная кнопка — НЕ трогаем логику)
    # --------------------------------------------------------------
    def save_block(self):
        """
        Сохраняем текущий экран по кнопке:
        - lines  — строки pyte (без ANSI)
        - colors — матрица цветов из CanvasTerminal.last_colors

        Эта функция остаётся совместимой со старым поведением.
        """
        lines = self.term.get_lines()
        color_matrix = getattr(self.canvas_term, "last_colors", None)
        self.logger.save_block(lines, color_matrix, self.device_short_id)
