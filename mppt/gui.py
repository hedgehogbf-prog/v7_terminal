# mppt/gui.py — финальная рабочая версия
# --------------------------------------------------
# ✔ стабильный рендер без мерцания
# ✔ правильная работа с ANSI
# ✔ строгая сборка блока post-ESC[2J
# ✔ автоподключение к ST-Link VCP
# ✔ идеальный _reader_loop без слипания строк
# --------------------------------------------------

import threading
import time
from tkinter import (
    Frame,
    BOTH,
    TOP,
    X,
    LEFT,
    Button,
    StringVar,
    Label,
)
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from mppt.serial_auto import SerialAuto
from mppt.parser import MPPTParser
from mppt.renderer import MPPTRenderer
from mppt.logger import MPPTLogger


class MPPTTerminalPanel(Frame):
    """
    MPPT Terminal Panel:
    - читает сырые ANSI со ST-Link VCP
    - собирает кадры MPPT как в реальном терминале
    - выводит без мерцания
    - поддерживает автоконнект
    """

    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

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

        # ---------------- Терминал ----------------
        self.text = ScrolledText(
            self,
            bg="#202124",
            fg="#e8eaed",
            insertbackground="#e8eaed",
            state="disabled",
            wrap="none",
            height=18,
        )
        self.text.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        # ---------------- MPPT логика ----------------
        self.serial = SerialAuto(baudrate=115200)
        self.renderer = MPPTRenderer(self.text)
        self.logger = MPPTLogger(status_callback=self._set_status_stub)
        self.parser = MPPTParser(on_block_ready=self.renderer.render_block)

        self.running = False
        self.thread = None

        self.rescan_ports()
        self.after(500, self._autoconnect_loop)

    # ------------------------------------------------------------------
    # Статус
    # ------------------------------------------------------------------
    def _set_status_stub(self, msg, color="white"):
        print(msg)

    def set_global_status(self, status_func):
        self._set_status_stub = status_func
        self.logger.status_callback = status_func

    # ------------------------------------------------------------------
    # Работа с портами
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Автоконнект
    # ------------------------------------------------------------------
    def _autoconnect_loop(self):
        if not self.running:
            port_name = self.port_var.get().strip() or None
            if self.serial.ensure(port_name):
                self.running = True
                self.btn_connect.config(
                    text=f"Disconnect ({self.serial.current_port})"
                )
                self._set_status_stub(
                    f"MPPT: автоподключено ({self.serial.current_port})",
                    "green",
                )
                self.thread = threading.Thread(
                    target=self._reader_loop, daemon=True
                )
                self.thread.start()

        self.after(500, self._autoconnect_loop)

    # ------------------------------------------------------------------
    # Ручное подключение
    # ------------------------------------------------------------------
    def toggle_connect(self):
        if self.running:
            self.running = False
            self.serial.close()
            self.btn_connect.config(text="Connect")
            self._set_status_stub("MPPT: отключено", "yellow")
            return

        port_name = self.port_var.get().strip()
        if not self.serial.ensure(port_name):
            self._set_status_stub("MPPT: не удалось открыть порт", "red")
            return

        if not port_name:
            self.port_var.set(self.serial.current_port)

        self.running = True
        self.btn_connect.config(text=f"Disconnect ({self.serial.current_port})")
        self._set_status_stub(
            f"MPPT: подключено ({self.serial.current_port})", "green"
        )

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------
    # IDEAL ANSI LINE READER
    # ------------------------------------------------------------------
    def _reader_loop(self):
        """
        Стабильный сборщик строк:
        ✔ режет только по '\n'
        ✔ не ломает ANSI
        ✔ убирает \x00 полностью
        ✔ не смешивает строки
        ✔ не пропускает содержимое
        """
        buf = ""

        while self.running and self.serial.ser:
            try:
                data = self.serial.ser.read_all()
            except Exception:
                self._set_status_stub("MPPT: ошибка чтения", "red")
                self.serial.close()
                self.running = False
                break

            if not data:
                time.sleep(0.01)
                continue

            try:
                text = data.decode(errors="ignore")
            except Exception:
                continue

            text = text.replace("\x00", "")

            for ch in text:
                if ch == "\n":
                    line = buf.rstrip("\r")
                    buf = ""

                    if not line.strip():
                        continue

                    # Передача строки парсеру
                    self.parser.feed_line(line)
                else:
                    buf += ch

    # ------------------------------------------------------------------
    # Логирование блока
    # ------------------------------------------------------------------
    def save_block(self):
        self.logger.save_block(self.renderer.last_block)
