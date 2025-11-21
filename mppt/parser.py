# mppt/parser.py
from util.ansi import strip_ansi

ESC_CLEAR = "\x1b[2J"
ESC_HOME = "\x1b[1;1H"


class MPPTParser:
    """
    Собирает блоки между ESC[2J / ESC[1;1H.
    Блок = список сырых строк (с ANSI), длина может быть 12, 13 и т.д.
    """

    def __init__(self, on_block_ready):
        self.current_block: list[str] = []
        self.on_block_ready = on_block_ready  # callback(block: list[str])

    def feed_line(self, raw_line: str):
        # начало нового блока
        if ESC_CLEAR in raw_line or ESC_HOME in raw_line:
            if self.current_block:
                self.on_block_ready(self.current_block[:])
            self.current_block = [raw_line]
            return

        if not self.current_block:
            return

        # добавляем строку в текущий блок
        self.current_block.append(raw_line)

    def reset(self):
        self.current_block = []
