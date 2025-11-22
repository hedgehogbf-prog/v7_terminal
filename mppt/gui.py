# mppt/gui.py — ИСПРАВЛЕННАЯ ПОЛНАЯ ВЕРСИЯ
# --------------------------------------------------
# ✔ правильная передача ANSI-строк
# ✔ нет потерь строк
# ✔ нет разрывов ESC-кодов
# ✔ нет мерцания
# ✔ нормальное автоподключение
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
    MPPT Terminal Panel (fixed)
    - Correct raw ANSI receiving
    - No flicker rendering
    - Auto reconnect
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
            width=14,
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
            text="Connect MPPT",
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

        # ---------------- Логика MPPT ----------------
        self.serial = SerialAuto(baudrate=115200)
        self.renderer = MPPTRenderer(self.text)
        self.logger = MPPTLogger(status_callback=self._set_status_stub)
        self.parser = MPPTParser(on_block_ready=self.renderer.render_block)

        self.running = False
        self.thread = None

        self.rescan_ports()

        # авто-коннект каждые 500 мс
        self.after(500, self._autoconnect_loop)

    # ------------------------------------------------------------------
    def _set_status_stub(self, msg, color="white"):
        print(msg)

    def set_global_status(self, status_func):
        self._set_status_stub = status_func
        self.logger.status_callback = status_func

    # ------------------------------------------------------------------
    def rescan_ports(self):
        ports = self.serial.list_ports()
        devs = [p.device for p in ports]

        self.combo_port["values"] = devs

        if devs:
            if self.port_var.get() not in devs:
                self.port_var.set(devs[0])
            self._set_status_stub("MPPT: список COM-портов обновлён", "cyan")
        else:
            self.port_var.set("")
            self.combo_port["values"] = []
            self._set_status_stub("MPPT: нет доступных COM-портов", "yellow")

    def rescan_ports_external(self):
        self.rescan_ports()

    # ------------------------------------------------------------------
    def _autoconnect_loop(self):
        """Постоянная попытка подключиться."""
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
                self.thread = threading.Thread(target=self._reader_loop, daemon=True)
                self.thread.start()

        self.after(500, self._autoconnect_loop)

    # ------------------------------------------------------------------
    def toggle_connect(self):
        if self.running:
            self.running = False
            self.serial.close()
            self.btn_connect.config(text="Connect MPPT")
            self._set_status_stub("MPPT: отключено", "yellow")
            return

        port_name = self.port_var.get().strip()
        ok = self.serial.ensure(port_name if port_name else None)

        if not ok or not self.serial.current_port:
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
    # 🔥 САМЫЙ ГЛАВНЫЙ БЛОК — ПРАВИЛЬНЫЙ ЧТЕНИЕ UART
    # ------------------------------------------------------------------
     # ------------------------------------------------------------------
    # Чтение данных и сборка блока
    # ------------------------------------------------------------------
    def _reader_loop(self):
        """
        Чтение UART и разбор на строки.

        ВАЖНО:
        - читаем сырой поток, делим только по '\n'
        - удаляем только \x00 (мусор) и \r
        - НИЧЕГО не strip'аем и не фильтруем по "пустоте"
        - каждую готовую строку отдаём в MPPTParser.feed_line()
        """
        buf = ""
        while self.running and self.serial.ser:
            try:
                data = self.serial.ser.read_all()
            except Exception:
                self._set_status_stub("MPPT: ошибка чтения, отключаюсь", "red")
                self.serial.close()
                self.running = False
                break

            if data:
                try:
                    text = data.decode(errors="ignore")
                except Exception:
                    text = ""
                for ch in text:
                    if ch == "\n":
                        # завершаем строку, вычищаем NUL, но НЕ strip'аем ANSI
                        line = buf.replace("\x00", "")
                        # передаём как есть — даже если там только ESC-последовательности
                        if line:
                            self.parser.feed_line(line)
                        buf = ""
                    elif ch == "\r":
                        # игнорируем CR (типичные \r\n)
                        continue
                    else:
                        buf += ch
            else:
                time.sleep(0.01)


    # ------------------------------------------------------------------
    def save_block(self):
        self.logger.save_block(self.renderer.last_block)
