# mppt/gui.py — финальная версия с маскированием UID в pyte screen
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
from mppt.terminal_pyte import PyteTerminal
from mppt.terminal_canvas import CanvasTerminal


class MPPTTerminalPanel(Frame):
    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        self.device_short_id: str | None = None

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
        self._plus_running = False  # флаг удержания

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

        # обработчики удержания
        self.btn_plus.bind("<ButtonPress-1>", lambda e: self._plus_press())
        self.btn_plus.bind("<ButtonRelease-1>", lambda e: self._plus_release())


        # ---------------- Canvas-терминал ----------------
        self.canvas = Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        # ---------------- Логика MPPT ----------------
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
            self._set_status_stub("MPPT: список COM обновлён", "cyan")
        else:
            self.port_var.set("")
            self.combo_port["values"] = []
            self._set_status_stub("MPPT: портов нет", "yellow")

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
                self._set_status_stub(
                    f"MPPT: автоподключено ({self.serial.current_port})", "green"
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
            self._set_status_stub("MPPT: отключено", "yellow")
            return

        port = self.port_var.get().strip()
        if not self.serial.ensure(port):
            self._set_status_stub("MPPT: не удалось открыть порт", "red")
            return

        if not port:
            self.port_var.set(self.serial.current_port)

        self.running = True
        self.btn_connect.config(text=f"Disconnect ({self.serial.current_port})")
        self._set_status_stub(
            f"MPPT: подключено ({self.serial.current_port})", "green"
        )

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    # --------------------------------------------------------------
    # Чтение UART
    # --------------------------------------------------------------
    def _reader_loop(self):
        while self.running and self.serial.ser:
            try:
                data = self.serial.ser.read_all()
            except Exception:
                self._set_status_stub("MPPT: ошибка чтения", "red")
                self.running = False
                break

            if not data:
                time.sleep(0.01)
                continue

            text_raw = data.decode(errors="ignore")
            text_raw = text_raw.replace("\x00", "")

            # Кормим pyte
            self.term.feed(text_raw)

            # Маскаруем UID внутри pyte
            self._mask_uid_in_screen()

            # Обновляем UI
            self._schedule_render()
            
    # --------------------------------------------------------------
    # +++++++++
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
                time.sleep(0.07)  # частота повторения 70 мс

        threading.Thread(target=worker, daemon=True).start()

    def _plus_release(self):
        """Остановить поток отправки '+' и отправить один плюс."""
        self._plus_running = False

        try:
            if self.running and self.serial.ser:
                self.serial.ser.write(b"+")
        except:
            pass


    # --------------------------------------------------------------
    # Маскирование UID в pyte buffer
    # --------------------------------------------------------------
    def _mask_uid_in_screen(self):
        screen = self.term.screen
        cols = screen.columns
        rows = len(screen.buffer)

        # UID универсальный паттерн STM32
        uid_pattern = re.compile(
            r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9A-Fa-f]+"
        )

        from pyte.screens import Char

        for row in range(rows):
            rowbuf = screen.buffer.get(row, {})
            if not rowbuf:
                continue

            line_chars = "".join(
                (rowbuf.get(c).data if rowbuf.get(c) else " ")
                for c in range(cols)
            )

            m = uid_pattern.search(line_chars)
            if not m:
                continue

            full_uid = m.group(0)
            start, end = m.span()

            # CRC16 при первом найденном UID
            if not self.device_short_id:
                parts = full_uid.split("-", maxsplit=2)
                hex_uid = full_uid.replace("-", "")
                uid_bytes = bytes.fromhex(hex_uid)
                crc = zlib.crc32(uid_bytes) & 0xFFFF
                self.device_short_id = f"{crc:04X}"
                print("Short UID =", self.device_short_id)

            replacement = f"ID:{self.device_short_id}"
            replacement = replacement.ljust(end - start)

            new_line = line_chars[:start] + replacement + line_chars[end:]

            # Запись обратно через создание НОВЫХ Char()
            for c, ch in enumerate(new_line):
                old = rowbuf.get(c)
                if old:
                    rowbuf[c] = Char(
                        ch,
                        old.fg,
                        old.bg,
                        old.bold,
                        old.italics,
                        old.underscore,
                        old.strikethrough,
                        old.reverse
                    )
                else:
                    rowbuf[c] = Char(ch)

            return

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
        self.canvas_term.render_diff()

    # --------------------------------------------------------------
    # Логирование
    # --------------------------------------------------------------
    def save_block(self):
        block = self.term.get_lines()
        self.logger.save_block(block)
