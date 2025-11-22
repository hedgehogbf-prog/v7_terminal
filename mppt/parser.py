from util.ansi import strip_ansi

ESC_CLEAR = "\x1b[2J"
ESC_HOME = "\x1b[1;1H"


class MPPTParser:
    """
    Собирает блоки между ESC[2J / ESC[1;1H.
    Блок = список сырых строк (с ANSI цветами), без управляющих
    команд очистки/позиционирования (они используются только как делимитеры).
    """

    def __init__(self, on_block_ready):
        # текущий блок строк (как их надо рендерить)
        self.current_block: list[str] = []
        # callback(block: list[str])
        self.on_block_ready = on_block_ready

    def feed_line(self, raw_line: str):
        """
        Получает ОДНУ логическую строку (без '\n', но с ANSI).
        Внутри строки могут встречаться ESC[2J / ESC[1;1H, которые
        означают начало нового кадра.
        Эти последовательности не должны попадать на экран — они только
        определяют границы блока.
        """

        if not raw_line:
            return

        line = raw_line

        # Проверка: есть ли в строке команды "начало нового кадра"
        has_clear = ESC_CLEAR in line
        has_home = ESC_HOME in line

        if has_clear or has_home:
            # если до этого что-то уже было — считаем это завершённым блоком
            if self.current_block:
                self.on_block_ready(self.current_block[:])

            # вырезаем управляющие команды из строки,
            # на экран они не нужны (Tk не настоящий терминал)
            line = line.replace(ESC_CLEAR, "").replace(ESC_HOME, "")

            # начинаем новый блок
            self.current_block = []

            # если после вырезания в первой строке что-то осталось —
            # добавляем её как первую видимую строку
            if line:
                self.current_block.append(line)

            return

        # если блок ещё не начат — игнорируем все строки до первого ESC[2J/ESC[1;1H]
        if not self.current_block:
            return

        # обычная строка внутри уже начатого блока
        self.current_block.append(line)

    def reset(self):
        self.current_block = []
