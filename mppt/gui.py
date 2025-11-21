# mppt/gui.py
import threading
import time
from tkinter import Frame, BOTH, TOP, X, LEFT, Button, Scrollbar, RIGHT, Y
from tkinter.scrolledtext import ScrolledText

from mppt.serial_auto import SerialAuto
from mppt.parser import MPPTParser
from mppt.renderer import MPPTRenderer
from mppt.logger import MPPTLogger


class MPPTTerminalPanel(Frame):
    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        # Верхняя панель кнопок
        top = Frame(self, bg=bg)
        top.pack(side=TOP, fill=X)

        self.btn_connect = Button(
            top, text="Connect MPPT", command=self.toggle_connect,
            bg="#303134", fg=fg, activebackground="#3c4043", activeforeground=fg
        )
        self.btn_connect.pack(side=LEFT, padx=4, pady=4)

        self.btn_save = Button(
            top, text="Save block", command=self.save_block,
            bg="#303134", fg=fg, activebackground="#3c4043", activeforeground=fg
        )
        self.btn_save.pack(side=LEFT, padx=4, pady=4)

        # Текстовое окно
        self.text = ScrolledText(
            self,
            bg="#202124",
            fg="#e8eaed",
            insertbackground="#e8eaed",
            state="disabled",
            wrap="none",
            height=18,
        )
        self.text.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        # Логика
        self.serial = SerialAuto(baudrate=115200)
        self.renderer = MPPTRenderer(self.text)
        self.logger = MPPTLogger(status_callback=self._set_status_stub)
        self.parser = MPPTParser(on_block_ready=self.renderer.render_block)

        self.running = False
        self.thread = None

    def _set_status_stub(self, msg, color="white"):
        # сюда можно протянуть глобальный статус-бар из gui/statusbar.py
        print(msg)

    def toggle_connect(self):
        if self.running:
            self.running = False
            self.serial.close()
            self.btn_connect.config(text="Connect MPPT")
            return

        if not self.serial.ensure():
            self._set_status_stub("MPPT: не удалось открыть порт", "red")
            return

        self.running = True
        self.btn_connect.config(text=f"Disconnect ({self.serial.current_port})")
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def _reader_loop(self):
        buf = ""
        while self.running and self.serial.ser:
            try:
                data = self.serial.ser.read_all()
            except Exception:
                self._set_status_stub("MPPT: ошибка чтения, отключаюсь", "red")
                self.serial.close()
                self.running = False
                break

            if data:
                try:
                    text = data.decode(errors="ignore")
                except Exception:
                    text = ""
                for ch in text:
                    if ch in ("\n", "\r"):
                        if buf.strip():
                            line = buf.replace("\x00", "")
                            self.parser.feed_line(line)
                            buf = ""
                    else:
                        buf += ch
            else:
                time.sleep(0.01)

    def save_block(self):
        # сохраняем последний показанный блок
        self.logger.save_block(self.renderer.last_block)
