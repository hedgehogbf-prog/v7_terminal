# gui/layout.py
from tkinter import Frame, TOP, BOTTOM, LEFT, RIGHT, BOTH, X
from mppt.gui import MPPTTerminalPanel
from psu.gui import PSUControlPanel
from gui.statusbar import StatusBar


class AppLayout(Frame):
    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        # -------- верхняя панель с глобальными кнопками --------
        top_bar = Frame(self, bg=bg)
        top_bar.pack(side=TOP, fill=X)

        # Кнопка глобального рескана COM
        from tkinter import Button  # локальный импорт, чтобы не тянуть наверх
        self.btn_rescan_all = Button(
            top_bar,
            text="COM Rescan All",
            command=self._rescan_all_com,
            bg="#303134",
            fg=fg,
            activebackground="#3c4043",
            activeforeground=fg
        )
        self.btn_rescan_all.pack(side=LEFT, padx=4, pady=4)

        # -------- основной контейнер: слева MPPT, справа ЛБП --------
        main = Frame(self, bg=bg)
        main.pack(side=TOP, fill=BOTH, expand=True)

        # Панель MPPT терминала
        self.mppt_panel = MPPTTerminalPanel(main, bg=bg, fg=fg)
        self.mppt_panel.pack(side=LEFT, fill=BOTH, expand=True)

        # Панель ЛБП (Owon SPE6103)
        self.psu_panel = PSUControlPanel(main, bg=bg, fg=fg, width=320)
        self.psu_panel.pack(side=RIGHT, fill="y")

        # -------- общий статусбар приложения --------
        self.status = StatusBar(self, bg=bg, fg=fg)
        self.status.pack(side=BOTTOM, fill=X)

        # Если панели умеют принимать глобальный статус — передадим
        if hasattr(self.mppt_panel, "set_global_status"):
            self.mppt_panel.set_global_status(self.status.set)
        if hasattr(self.psu_panel, "set_global_status"):
            self.psu_panel.set_global_status(self.status.set)

    # ============================================================
    #   Глобальные действия
    # ============================================================

    def _rescan_all_com(self):
        """
        Глобальный рескан портов:
        - ЛБП: обновить список COM
        - MPPT: если в будущем появится метод rescan_ports(), тоже дернём.
        """
        # ЛБП
        if hasattr(self.psu_panel, "rescan_ports"):
            self.psu_panel.rescan_ports()

        # MPPT (на будущее, если добавим такой метод)
        if hasattr(self.mppt_panel, "rescan_ports"):
            self.mppt_panel.rescan_ports()

        # Отобразим в общем статусбаре
        self.status.set("COM порты обновлены", color="cyan")
