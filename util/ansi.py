# util/ansi.py
import re

SGR_RE = re.compile(r'\x1b\[([0-9;]*)m')

COLOR_MAP = {
    '30': '000000', '31': 'FF5555', '32': '50FA7B', '33': 'F1FA8C',
    '34': 'BD93F9', '35': 'FF79C6', '36': '8BE9FD', '37': 'F8F8F2'
}

COLOR_BRIGHT = {
    '90': '6272A4', '91': 'FF6E6E', '92': '69FF94', '93': 'FFFFA5',
    '94': 'D6ACFF', '95': 'FF92DF', '96': 'A4FFFF', '97': 'FFFFFF'
}


def strip_ansi(s: str) -> str:
    """Удалить все ANSI коды."""
    return re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', s).replace("\x00", "")


def parse_ansi_segments(line: str):
    """
    Преобразует строку с ANSI-кодами в список (text, #RRGGBB).
    Все ESC кроме SGR игнорируются.
    """
    segments = []
    i = 0
    L = len(line)
    current_color = "#F8F8F2"  # светлый как в Dracula

    while i < L:
        ch = line[i]
        if ch == "\x1b":
            m = SGR_RE.match(line, i)
            if m:
                codes = [c for c in m.group(1).split(";") if c]
                for c in codes:
                    if c in COLOR_MAP:
                        current_color = "#" + COLOR_MAP[c]
                    elif c in COLOR_BRIGHT:
                        current_color = "#" + COLOR_BRIGHT[c]
                    elif c == "0":
                        current_color = "#F8F8F2"
                i = m.end()
                continue
            else:
                # игнорируем не-SGR ESC
                j = i + 1
                while j < L and not line[j].isalpha():
                    j += 1
                i = j + 1
                continue

        # обычный символ
        segments.append((ch, current_color))
        i += 1

    return segments
