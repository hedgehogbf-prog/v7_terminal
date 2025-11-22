# mppt/renderer.py
from tkinter import Text, END
from util.ansi import parse_ansi_segments


class MPPTRenderer:
    """
    Рендерит полученный блок от MPPTParser в Tk.Text.

    Главная задача:
    ✔ не мерцать
    ✔ не удалять теги лишний раз
    ✔ обновлять только изменившиеся строки
    ✔ корректно отображать ANSI-цвета

    Мы отрисовываем:
    - если это первый блок — полностью
    - последующие блоки — только дифф строк
    """

    def __init__(self, text_widget: Text):
        self.text = text_widget
        self.last_block: list[str] = []

    # ------------------------------------------------------------------
    # Вставка строки с ANSI-поддержкой
    # ------------------------------------------------------------------
    def _insert_ansi_line(self, line: str):
        segments = parse_ansi_segments(line)  # [(text, color), ...]
        for ch, color in segments:
            tag = f"fg_{color}"
            if tag not in self.text.tag_names():
                self.text.tag_config(tag, foreground=color)
            self.text.insert(END, ch, tag)

    # ------------------------------------------------------------------
    # Основной рендер
    # ------------------------------------------------------------------
    def render_block(self, block: list[str]):
        text = self.text
        text.configure(state="normal")

        old = self.last_block
        new = block

        old_n = len(old)
        new_n = len(new)

        # ----------------- первая полная отрисовка ---------------------
        if not old:
            text.delete("1.0", END)
            for line in new:
                if line.strip():
                    self._insert_ansi_line(line)
                text.insert(END, "\n")

        # -------------------- диффовая отрисовка ------------------------
        else:
            # Добавить недостающие строки в конец
            if new_n > old_n:
                for _ in range(new_n - old_n):
                    text.insert(END, "\n")

            # Обновить только отличающиеся строки
            for i in range(new_n):
                old_line = old[i] if i < old_n else ""
                new_line = new[i]

                if new_line != old_line:
                    # Удалить старую строку
                    text.delete(f"{i+1}.0", f"{i+2}.0")
                    # Вставить новую
                    if new_line.strip():
                        self._insert_ansi_line(new_line)
                    text.insert(f"{i+1}.end", "\n")

            # Если новых линий меньше — удалить лишние
            if new_n < old_n:
                text.delete(f"{new_n+1}.0", END)

        text.configure(state="disabled")

        # обновляем копию блока
        self.last_block = new[:]
