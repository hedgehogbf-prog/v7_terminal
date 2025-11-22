# mppt/gui.py — версия с PyteTerminal + CanvasTerminal
# -----------------------------------------------------------
# ✔ pyte эмулирует настоящий терминал (ANSI, курсор, clear)
# ✔ CanvasTerminal рисует сетку 64x18 без мерцания
# ✔ ОБНОВЛЕНИЯ GUI идут только из main-thread через .after()
# -----------------------------------------------------------

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

        # ---------------- Canvas-терминал ----------------
        self.canvas = Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        # ---------------- Логика MPPT ----------------
        self.serial = SerialAuto(baudrate=115200)
        # Эмулятор терминала pyte
        self.term = PyteTerminal(cols=64, rows=18)
        # Рендер pyte-экрана на Canvas
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

        # флаг, чтобы не заспамить .after()
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
    # Чтение UART (фоновый поток, БЕЗ прямого доступа к Tk)
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

            # Кормим pyte в фоновом потоке (без Tk)
            self.term.feed(text_raw)

            # Просим перерисовать Canvas в главном потоке
            self._schedule_render()

    # --------------------------------------------------------------
    # Планировщик рендера (UI только через .after)
    # --------------------------------------------------------------
    def _schedule_render(self):
        if self._render_scheduled:
            return
        self._render_scheduled = True
        # отрисовка в главном потоке
        self.after(0, self._do_render)

    def _do_render(self):
        self._render_scheduled = False
        if not self.running:
            return
        # перерисовываем только изменившиеся ячейки
        self.canvas_term.render_diff()

    # --------------------------------------------------------------
    # Логирование блока (для Excel и т.п.)
    # --------------------------------------------------------------
    def save_block(self):
        """
        Сохраняем текущий "экран" pyte как список строк.
        MPPTLogger дальше сделает txt/xlsx.
        """
        block = self.term.get_lines()
        self.logger.save_block(block)
