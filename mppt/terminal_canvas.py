# mppt/terminal_canvas.py
# --------------------------------------------------
# Рендер терминала pyte в Tk.Canvas без мерцания.
# - фиксированная сетка cols x rows
# - каждая ячейка — отдельный canvas text item
# - дифф-отрисовка: обновляем только измененные ячейки
# --------------------------------------------------

from tkinter import Canvas
import tkinter.font as tkfont

from mppt.terminal_pyte import PyteTerminal, PYTE_FG_TO_HEX


class CanvasTerminal:
    """
    Обёртка: PyteTerminal + Tk.Canvas
    - хранит ссылку на PyteTerminal (screen/stream)
    - рисует символы на canvas
    - умеет дифф-обновлять только изменившиеся ячейки
    """

    def __init__(
        self,
        canvas: Canvas,
        term: PyteTerminal,
        cols: int = 64,
        rows: int = 18,
        bg: str = "#202124",
        font_name: str = "Consolas",
        font_size: int = 10,
    ):
        self.canvas = canvas
        self.term = term
        self.cols = cols
        self.rows = rows
        self.bg = bg

        # Шрифт фиксированной ширины
        self.font = tkfont.Font(family=font_name, size=font_size)
        # Размер ячейки
        self.cell_w = self.font.measure("M")
        self.cell_h = self.font.metrics("linespace")

        # Настраиваем канвас по размеру сетки
        canvas.configure(
            bg=bg,
            width=self.cell_w * cols,
            height=self.cell_h * rows,
            highlightthickness=0,
        )

        # Матрица элементов Canvas и кэша состояния
        self.items = [[None for _ in range(cols)] for _ in range(rows)]
        self.last_chars = [[" " for _ in range(cols)] for _ in range(rows)]
        default_color = PYTE_FG_TO_HEX.get("default", "#e8eaed")
        self.last_colors = [
            [default_color for _ in range(cols)] for _ in range(rows)
        ]

        # Предсоздаём все text-элементы
        for r in range(rows):
            y = r * self.cell_h
            for c in range(cols):
                x = c * self.cell_w
                item_id = canvas.create_text(
                    x,
                    y,
                    text=" ",
                    fill=default_color,
                    font=self.font,
                    anchor="nw",
                )
                self.items[r][c] = item_id

    # ----------------------------------------------------------
    def render_diff(self):
        """
        Дифф-отрисовка содержимого экрана pyte.
        Вызывать ТОЛЬКО из main-thread (через Tk.after).
        """
        screen = self.term.screen
        buf = screen.buffer
        rows = self.rows
        cols = self.cols
        default_color = PYTE_FG_TO_HEX.get("default", "#e8eaed")

        for r in range(rows):
            rowbuf = buf.get(r, {})
            for c in range(cols):
                cell = rowbuf.get(c)
                if cell is None:
                    ch = " "
                    fg_name = "default"
                else:
                    ch = cell.data or " "
                    fg_name = cell.fg or "default"

                # Убираем мусорные NUL, превращаем в пробел
                if ch == "\x00":
                    ch = " "

                fg_hex = PYTE_FG_TO_HEX.get(fg_name, default_color)

                if (
                    ch != self.last_chars[r][c]
                    or fg_hex != self.last_colors[r][c]
                ):
                    item_id = self.items[r][c]
                    # Обновляем только изменившиеся ячейки
                    self.canvas.itemconfig(item_id, text=ch, fill=fg_hex)
                    self.last_chars[r][c] = ch
                    self.last_colors[r][c] = fg_hex
