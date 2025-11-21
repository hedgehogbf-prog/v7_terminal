# gui/layout.py
from tkinter import Frame, LEFT, RIGHT, BOTH, X, TOP
from mppt.gui import MPPTTerminalPanel
from psu.gui import PSUControlPanel
from gui.statusbar import StatusBar


class AppLayout(Frame):
    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        # Верхний контейнер: слева MPPT, справа PSU
        top = Frame(self, bg=bg)
        top.pack(side=TOP, fill=BOTH, expand=True)

        self.mppt_panel = MPPTTerminalPanel(top, bg=bg, fg=fg)
        self.mppt_panel.pack(side=LEFT, fill=BOTH, expand=True)

        self.psu_panel = PSUControlPanel(top, bg=bg, fg=fg, width=300)
        self.psu_panel.pack(side=RIGHT, fill="y")

        # Статусбар
        self.status = StatusBar(self, bg=bg, fg=fg)
        self.status.pack(side=TOP, fill=X)
