# mppt/renderer.py
from tkinter import Text, END
from util.ansi import parse_ansi_segments


class MPPTRenderer:
    """
    Рендер блока в Tk.Text:
    - блок может быть любой длины
    - обновляет только изменившиеся строки
    """

    def __init__(self, text_widget: Text):
        self.text = text_widget
        self.last_block: list[str] = []

    def _insert_ansi_line(self, line: str):
        segments = parse_ansi_segments(line)
        for ch, color in segments:
            tag = f"fg_{color}"
            if tag not in self.text.tag_names():
                self.text.tag_config(tag, foreground=color)
            self.text.insert(END, ch, tag)

    def render_block(self, block: list[str]):
        text = self.text
        text.configure(state="normal")

        old = self.last_block
        new = block
        old_n = len(old)
        new_n = len(new)

        # если виджет пустой — первая отрисовка
        if not old:
            text.delete("1.0", END)
            for line in new:
                if line.strip():
                    self._insert_ansi_line(line)
                text.insert(END, "\n")
        else:
            # гарантируем нужное количество строк
            if new_n > old_n:
                for _ in range(new_n - old_n):
                    text.insert(END, "\n")

            for i in range(new_n):
                old_line = old[i] if i < old_n else ""
                new_line = new[i]
                if new_line != old_line:
                    text.delete(f"{i+1}.0", f"{i+2}.0")
                    if new_line.strip():
                        self._insert_ansi_line(new_line)
                    text.insert(f"{i+1}.end", "\n")

            if new_n < old_n:
                text.delete(f"{new_n+1}.0", END)

        text.configure(state="disabled")
        self.last_block = new[:]
