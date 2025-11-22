from util.ansi import strip_ansi

# Управляющие команды
ESC_CLEAR = "\x1b[2J"
ESC_HOME = "\x1b[1;1H"
ESC_HIDE = "\x1b[?25l"


class MPPTParser:
    """
    Правильный парсер MPPT-кадров.

    Устройство присылает кадры в формате:
        ESC[1;1H ESC[?25l ESC[2J  <заголовок> <12–13 строк> ESC[36m ...

    Главные правила:
    ✔ Начало нового кадра — только ESC[2J
    ✔ Все управляющие команды вырезаются
    ✔ Линии ДО первого кадра игнорируются
    ✔ Блок заканчивается строго перед следующим ESC[2J
    """

    def __init__(self, on_block_ready):
        # текущий блок видимых строк
        self.current_block: list[str] = []
        self.on_block_ready = on_block_ready
        self.in_frame = False  # считаем ли мы сейчас блок

    def _strip_control(self, line: str) -> str:
        """
        Вырезает управляющие ANSI-коды, кроме цветовых.
        """
        return (
            line
            .replace(ESC_HOME, "")
            .replace(ESC_HIDE, "")
            .replace(ESC_CLEAR, "")
        )

    def feed_line(self, raw_line: str):
        """
        Получает ОДНУ логическую строку (ANSI внутри не трогаем).
        Работает по принципу:
        - ESC_CLEAR → начало кадра
        - всё до ESC_CLEAR → игнор
        - строки после ESC_CLEAR → часть кадра, пока не придёт новый ESC_CLEAR
        """

        if not raw_line:
            return

        # Начало нового кадра?
        if ESC_CLEAR in raw_line:
            # Завершить предыдущий блок
            if self.in_frame and self.current_block:
                self.on_block_ready(self.current_block[:])

            # Начать новый блок
            self.current_block = []
            self.in_frame = True

            # удалить управляющие команды
            cleaned = self._strip_control(raw_line)

            if cleaned.strip():
                self.current_block.append(cleaned)

            return

        # Если кадр ещё не начат — игнор
        if not self.in_frame:
            return

        # Внутри кадра: очищаем управляющие команды
        cleaned = self._strip_control(raw_line)

        # если строка пустая — игнорируем
        if not cleaned.strip():
            return

        self.current_block.append(cleaned)

    def reset(self):
        self.current_block = []
        self.in_frame = False
