from tkinter import Tk
from gui.layout import AppLayout
import sys
import os

APP_TITLE = "v7 Terminal"
APP_WIDTH = 1280
APP_HEIGHT = 760

def resource_path(relative_path):
    """ Возвращает корректный путь как при запуске .py, так и .exe """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return relative_path

def main():
    root = Tk()
    root.title(APP_TITLE)
    root.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")

    # Устанавливаем иконку
    ico_path = resource_path("ward.ico")
    try:
        root.iconbitmap(ico_path)
    except Exception as e:
        print(f"Icon load error: {e}")

    # Тёмная тема
    bg = "#202124"
    fg = "#e8eaed"
    root.configure(bg=bg)

    app = AppLayout(root, bg=bg, fg=fg)
    app.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
