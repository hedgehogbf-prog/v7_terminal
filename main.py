# main.py
from tkinter import Tk
from gui.layout import AppLayout

APP_TITLE = "v7_terminal — MPPT + Owon PSU"
APP_WIDTH = 1280
APP_HEIGHT = 760


def main():
    root = Tk()
    root.title(APP_TITLE)
    root.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")

    # Тёмная тема
    bg = "#202124"
    fg = "#e8eaed"
    root.configure(bg=bg)

    app = AppLayout(root, bg=bg, fg=fg)
    app.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
