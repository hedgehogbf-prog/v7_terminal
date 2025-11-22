# mppt/terminal_pyte.py
#
# Эмулятор терминала на базе pyte.
# - принимает сырой ANSI-поток (как Tabby)
# - ведёт полноценный экран с курсором
# - отдаёт содержимое экрана построчно
# - даёт цвета для каждого символа

import pyte


# Простая карта цветов pyte -> Tkinter
PYTE_FG_TO_HEX = {
    "default": "#e8eaed",
    "black":   "#000000",
    "red":     "#ff5555",
    "green":   "#50fa7b",
    "brown":   "#f1fa8c",  # обычно yellow
    "blue":    "#6272a4",
    "magenta": "#ff79c6",
    "cyan":    "#8be9fd",
    "white":   "#f8f8f2",

    # bright-цвета (если pyte их отдаёт)
    "brightblack":   "#4d4d4d",
    "brightred":     "#ff6e6e",
    "brightgreen":   "#69ff94",
    "brightyellow":  "#ffffa5",
    "brightblue":    "#d6acff",
    "brightmagenta": "#ff92df",
    "brightcyan":    "#a4ffff",
    "brightwhite":   "#ffffff",
}


class PyteTerminal:
    """
    Обёртка над pyte.Screen/Stream.

    screen: виртуальный экран (rows x cols)
    stream: принимает ANSI-поток (строки из COM)
    """

    def __init__(self, cols=80, rows=24):
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.Stream(self.screen)

        # последний "снимок" экрана в виде списка строк (для логгера)
        self.last_block: list[str] = []

    # -------------------- API для чтения из COM ------------------------
    def feed(self, text: str):
        """Кормим сырой ANSI-поток (как есть из COM)."""
        self.stream.feed(text)
        # обновляем кеш строк
        self.last_block = list(self.screen.display)

    # -------------------- API для GUI/логгера --------------------------
    def get_lines(self) -> list[str]:
        """Вернуть текущий экран как список строк (без цветов)."""
        return list(self.screen.display)

    def iter_colored_lines(self):
        """
        Итератор по строкам, выдаёт для каждой строки список
        (run_text, fg_color_hex).
        Удобно для покраски Tk.Text тегами.
        """
        lines_runs: list[list[tuple[str, str]]] = []

        rows = self.screen.lines
        cols = self.screen.columns

        # screen.buffer: row -> {col: Char}
        buf = self.screen.buffer

        for row in range(rows):
            rowbuf = buf.get(row, {})
            runs = []
            current_fg = None
            current_text = ""

            for col in range(cols):
                cell = rowbuf.get(col)
                ch = cell.data if cell is not None else " "
                fg_name = cell.fg if cell is not None else "default"
                fg_hex = PYTE_FG_TO_HEX.get(fg_name, PYTE_FG_TO_HEX["default"])

                if current_fg is None:
                    # первый символ строки
                    current_fg = fg_hex
                    current_text = ch
                elif fg_hex == current_fg:
                    # тот же цвет, расширяем текущий run
                    current_text += ch
                else:
                    # цвет изменился, завершаем предыдущий run
                    if current_text:
                        runs.append((current_text.rstrip("\x00"), current_fg))
                    current_fg = fg_hex
                    current_text = ch

            # дописываем последний run в строке
            if current_text:
                runs.append((current_text.rstrip("\x00"), current_fg))

            # убираем полностью пустые строки (только пробелы)
            if runs and any(t.strip() for (t, _c) in runs):
                lines_runs.append(runs)
            else:
                # всё равно добавим пустую строку, чтобы структура экрана сохранялась
                lines_runs.append([])

        return lines_runs
