# gui/statusbar.py
from tkinter import Frame, Label, StringVar


class StatusBar(Frame):
    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.var = StringVar(value="Готово")
        self.label = Label(self, textvariable=self.var, bg=bg, fg=fg, anchor="w")
        self.label.pack(fill="x")

    def set(self, msg: str, color="white"):
        self.var.set(msg)
        self.label.config(fg=color)
