# psu/gui.py
"""
Панель управления ЛБП OWON (серия SPE, например SPE6103) для v7_terminal.

- Использует psu.owon.OwonPSU (обёртка над owon_psu 0.0.4)
- Автоматически:
    - открывает порт
    - включает REMOTE режим (SYST:REM)
    - включает KeyLock
    - выключает выход при подключении

Функционал:
- Выбор COM-порта
- Подключение/отключение ЛБП
- Reset COM
- Измеренные U/I (крупно)
- Установленные U/I (мелко)
- Автоматическое включение выхода при применении уставок
- Кнопка ВЫХОД ON/OFF
- Пресеты U/I с редактором
"""

from __future__ import annotations

from tkinter import (
    Frame, TOP, LEFT, RIGHT, BOTTOM, BOTH, X, Y, END,
    Label, Button, Entry, Toplevel, Listbox, SINGLE, StringVar
)
from tkinter import ttk
from tkinter import font as tkfont

import os
import json

from serial.tools import list_ports

from psu.owon import OwonPSU


# Файл пресетов: ~\Documents\v7\psu_presets.json
DEFAULT_PRESETS_PATH = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "v7",
    "psu_presets.json",
)

DEFAULT_PRESETS = {
    "0V 0A": {"U": 0.0, "I": 0.0},
    "5V 1A": {"U": 5.0, "I": 1.0},
    "12V 3A": {"U": 12.0, "I": 3.0},
}


class PSUControlPanel(Frame):
    """Главная панель управления ЛБП в правой части окна."""
    POLL_INTERVAL_MS = 200

    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        # Объект ЛБП
        self.psu: OwonPSU | None = None
        self.connected: bool = False
        self.current_output_state: bool = False  # наше состояние выхода (ON/OFF)

        # COM-порт (выбранный в Combobox)
        self.port_var = StringVar()

        # Измеренные значения
        self.u_meas_var = StringVar(value="--.-- V")
        self.i_meas_var = StringVar(value="--.-- A")

        # Уставки
        self.u_set_var = StringVar(value="0.0")
        self.i_set_var = StringVar(value="0.0")
        self.u_set_label_var = StringVar(value="—")
        self.i_set_label_var = StringVar(value="—")

        # Пресеты
        self.presets_path = DEFAULT_PRESETS_PATH
        self.presets: dict[str, dict[str, float]] = {}
        self.preset_buttons: list[Button] = []

        # Глобальный статусбар (передаётся из AppLayout)
        self._global_status_cb = None

        # Шрифты
        self.font_big = tkfont.Font(size=28, weight="bold")
        self.font_small = tkfont.Font(size=11)

        # ID задачи опроса
        self._measure_job = None

        # Построение интерфейса
        self._build_ui()

        # Загрузим пресеты
        self._load_presets()
        self._refresh_presets_ui()

        # Первичный рескан портов
        self.rescan_ports()

    # ------------------------------------------------------------------
    # Связь с общим статусбаром
    # ------------------------------------------------------------------
    def set_global_status(self, cb):
        """
        cb(message: str, color: str)
        """
        self._global_status_cb = cb

    def _set_status(self, text: str, color: str = "white"):
        # локальный статус (над "Измерено")
        self.status_label.config(text=text, fg=color)
        # общий статусбар внизу
        if self._global_status_cb:
            self._global_status_cb(text, color=color)

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Верхняя строка: COM, Обновить, Подключить, Reset COM
        top = Frame(self, bg=self.bg)
        top.pack(side=TOP, fill=X, padx=4, pady=4)

        Label(top, text="COM ЛБП:", bg=self.bg, fg=self.fg).pack(side=LEFT)

        self.combo_port = ttk.Combobox(
            top, textvariable=self.port_var, width=10, state="readonly"
        )
        self.combo_port.pack(side=LEFT, padx=4)

        btn_rescan = Button(
            top,
            text="Обновить",
            command=self.rescan_ports,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        btn_rescan.pack(side=LEFT, padx=2)

        self.btn_connect = Button(
            top,
            text="Подключить",
            command=self._toggle_connect,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        self.btn_connect.pack(side=LEFT, padx=2)

        self.btn_reset = Button(
            top,
            text="Reset COM",
            command=self._reset_com,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        self.btn_reset.pack(side=LEFT, padx=2)

        # Статусбар ЛБП (над "Измерено")
        self.status_label = Label(
            self,
            text="Отключено",
            bg=self.bg,
            fg="#ff5555",
            anchor="w",
        )
        self.status_label.pack(side=TOP, fill=X, padx=4)

        # Центральная часть: слева измерения, справа уставки
        center = Frame(self, bg=self.bg)
        center.pack(side=TOP, fill=X, padx=4, pady=4)

        # Левая колонка — измеренные значения
        left = Frame(center, bg=self.bg)
        left.pack(side=LEFT, fill=BOTH, expand=True)

        Label(left, text="Измерено", bg=self.bg, fg=self.fg).pack(anchor="w")

        Label(
            left,
            textvariable=self.u_meas_var,
            bg=self.bg,
            fg="#55ff55",
            font=self.font_big,
        ).pack(anchor="w")

        Label(
            left,
            textvariable=self.i_meas_var,
            bg=self.bg,
            fg="#55ff55",
            font=self.font_big,
        ).pack(anchor="w")

        # Правая колонка — уставки
        right = Frame(center, bg=self.bg)
        right.pack(side=RIGHT, fill=Y)

        Label(right, text="Установлено", bg=self.bg, fg=self.fg).pack(anchor="w")

        # U-set
        row_u = Frame(right, bg=self.bg)
        row_u.pack(fill=X, pady=2)
        Label(row_u, text="U (В):", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(
            row_u,
            textvariable=self.u_set_var,
            bg="#303134",
            fg=self.fg,
            insertbackground=self.fg,
            width=8,
        ).pack(side=LEFT, padx=3)
        Label(
            row_u,
            textvariable=self.u_set_label_var,
            bg=self.bg,
            fg="#a0a0a0",
            font=self.font_small,
        ).pack(side=LEFT, padx=2)

        # I-set
        row_i = Frame(right, bg=self.bg)
        row_i.pack(fill=X, pady=2)
        Label(row_i, text="I (А):", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(
            row_i,
            textvariable=self.i_set_var,
            bg="#303134",
            fg=self.fg,
            insertbackground=self.fg,
            width=8,
        ).pack(side=LEFT, padx=3)
        Label(
            row_i,
            textvariable=self.i_set_label_var,
            bg=self.bg,
            fg="#a0a0a0",
            font=self.font_small,
        ).pack(side=LEFT, padx=2)

        # Кнопка "Применить"
        btn_apply = Button(
            right,
            text="Применить",
            command=self._apply_setpoints,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        btn_apply.pack(fill=X, pady=4)

        # Кнопка "Выход ON/OFF"
        self.btn_output = Button(
            right,
            text="Выход: OFF",
            command=self._toggle_output,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
            state="disabled",
        )
        self.btn_output.pack(fill=X, pady=2)

        # Блок пресетов
        presets_frame = Frame(self, bg=self.bg)
        presets_frame.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        top_presets = Frame(presets_frame, bg=self.bg)
        top_presets.pack(side=TOP, fill=X)

        Label(top_presets, text="Пресеты", bg=self.bg, fg=self.fg).pack(side=LEFT)

        btn_edit = Button(
            top_presets,
            text="Редактировать",
            command=self._open_presets_editor,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        btn_edit.pack(side=RIGHT)

        self.presets_container = Frame(presets_frame, bg=self.bg)
        self.presets_container.pack(side=TOP, fill=BOTH, expand=True)

    # ------------------------------------------------------------------
    # Работа с COM-портами
    # ------------------------------------------------------------------
    def rescan_ports(self):
        """Обновить список COM-портов ЛБП."""
        ports = list(list_ports.comports())
        devs = [p.device for p in ports]

        self.combo_port["values"] = devs

        if devs:
            if self.port_var.get() not in devs:
                self.port_var.set(devs[0])
            self._set_status("Порты ЛБП обновлены", "cyan")
        else:
            self.port_var.set("")
            self._set_status("ЛБП: нет доступных портов", "yellow")

    # вызываться из layout.AppLayout._rescan_all_com
    def rescan_ports_external(self):
        self.rescan_ports()

    # ------------------------------------------------------------------
    # Подключение / отключение
    # ------------------------------------------------------------------
    def _toggle_connect(self):
        """Подключить / отключить ЛБП."""
        # --- Отключение ---
        if self.connected and self.psu:
            if self._measure_job:
                self.after_cancel(self._measure_job)
                self._measure_job = None

            try:
                self.psu.close()
            except Exception:
                pass

            self.psu = None
            self.connected = False
            self.current_output_state = False

            self.btn_connect.config(text="Подключить")
            self.btn_output.config(state="disabled", text="Выход: OFF")
            self.u_meas_var.set("--.-- V")
            self.i_meas_var.set("--.-- A")
            self.u_set_label_var.set("—")
            self.i_set_label_var.set("—")

            self._set_status("ЛБП отключён", "yellow")
            return

        # --- Подключение ---
        port = self.port_var.get().strip()
        if not port:
            self._set_status("ЛБП: порт не выбран", "red")
            return

        try:
            psu = OwonPSU(port)
            psu.open()

            # Попробуем прочитать идентификатор
            try:
                ident = psu.read_identity()
                self._set_status(f"{ident} ({port})", "green")
            except Exception:
                self._set_status(f"ЛБП подключён ({port})", "green")

            # Попробуем получить текущие уставки
            try:
                u_set = psu.get_voltage()
                i_set = psu.get_current()
                self.u_set_label_var.set(f"{u_set:.3f} В")
                self.i_set_label_var.set(f"{i_set:.3f} А")
            except Exception:
                self.u_set_label_var.set("—")
                self.i_set_label_var.set("—")

            # Выход из драйвера на старте выключен (см. owon.py),
            # но проверим состояние
            try:
                out = psu.get_output()
                self.current_output_state = bool(out)
            except Exception:
                self.current_output_state = False

            self.btn_output.config(
                state="normal",
                text=f"Выход: {'ON' if self.current_output_state else 'OFF'}",
            )

            self.psu = psu
            self.connected = True
            self.btn_connect.config(text="Отключить")

            # Запускаем опрос
            self._schedule_measure()

        except Exception as e:
            self.psu = None
            self.connected = False
            self._set_status(f"Ошибка подключения ЛБП: {e}", "red")

    def _reset_com(self):
        """Переподключить ЛБП к тому же COM-порту."""
        if not self.psu or not self.connected:
            self._set_status("Reset COM: ЛБП не подключён", "red")
            return

        port = self.port_var.get().strip()
        if not port:
            self._set_status("Reset COM: порт не выбран", "red")
            return

        if self._measure_job:
            self.after_cancel(self._measure_job)
            self._measure_job = None

        try:
            self.psu.close()
        except Exception:
            pass

        try:
            psu = OwonPSU(port)
            psu.open()
            self.psu = psu
            self.connected = True

            self._set_status(f"Reset COM успешен ({port})", "green")
            self._schedule_measure()
        except Exception as e:
            self.psu = None
            self.connected = False
            self._set_status(f"Ошибка Reset COM: {e}", "red")

    # ------------------------------------------------------------------
    # Опрос измерений
    # ------------------------------------------------------------------
    def _schedule_measure(self):
        if not self.connected or not self.psu:
            return

        try:
            u = self.psu.measure_voltage()
            i = self.psu.measure_current()
            self.u_meas_var.set(f"{u:.3f} V")
            self.i_meas_var.set(f"{i:.3f} A")
        except Exception as e:
            self._set_status(f"Ошибка измерения ЛБП: {e}", "red")

        self._measure_job = self.after(self.POLL_INTERVAL_MS, self._schedule_measure)

    # ------------------------------------------------------------------
    # Уставки и выход
    # ------------------------------------------------------------------
    def _apply_setpoints(self):
        """Установить уставки U/I и включить выход при необходимости."""
        if not self.connected or not self.psu:
            self._set_status("Сначала подключите ЛБП", "red")
            return

        try:
            u = float(self.u_set_var.get().replace(",", "."))
            i = float(self.i_set_var.get().replace(",", "."))
        except ValueError:
            self._set_status("Некорректные значения U/I", "red")
            return

        try:
            self.psu.set_voltage(u)
            self.psu.set_current(i)
            self.u_set_label_var.set(f"{u:.3f} В")
            self.i_set_label_var.set(f"{i:.3f} А")

            # Автоматически включаем выход, если он был OFF
            if not self.current_output_state:
                self.psu.set_output(True)
                self.current_output_state = True
                self.btn_output.config(text="Выход: ON")

            self._set_status(f"Уставки применены: U={u:.3f} В, I={i:.3f} А", "green")
        except Exception as e:
            self._set_status(f"Ошибка задания уставок: {e}", "red")

    def _toggle_output(self):
        """Переключить выход ЛБП."""
        if not self.connected or not self.psu:
            self._set_status("Сначала подключите ЛБП", "red")
            return

        try:
            new_state = not self.current_output_state
            self.psu.set_output(new_state)
            self.current_output_state = new_state
            self.btn_output.config(text=f"Выход: {'ON' if new_state else 'OFF'}")
            self._set_status(
                f"Выход ЛБП {'включён' if new_state else 'выключен'}",
                "green" if new_state else "yellow",
            )
        except Exception as e:
            self._set_status(f"Ошибка переключения выхода: {e}", "red")

    # ------------------------------------------------------------------
    # Пресеты
    # ------------------------------------------------------------------
    def _load_presets(self):
        os.makedirs(os.path.dirname(self.presets_path), exist_ok=True)

        if not os.path.exists(self.presets_path):
            self.presets = DEFAULT_PRESETS.copy()
            self._save_presets()
            return

        try:
            with open(self.presets_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self.presets = data
                else:
                    self.presets = DEFAULT_PRESETS.copy()
        except Exception:
            self.presets = DEFAULT_PRESETS.copy()
            self._save_presets()

    def _save_presets(self):
        try:
            with open(self.presets_path, "w", encoding="utf-8") as f:
                json.dump(self.presets, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("Ошибка сохранения пресетов ЛБП:", e)

    def _refresh_presets_ui(self):
        for btn in self.preset_buttons:
            btn.destroy()
        self.preset_buttons.clear()

        for name, cfg in self.presets.items():
            u = cfg.get("U", 0.0)
            i = cfg.get("I", 0.0)

            def make_cmd(U=u, I=i):
                self.u_set_var.set(str(U))
                self.i_set_var.set(str(I))
                if self.connected and self.psu:
                    self._apply_setpoints()

            text = f"{name}\nU={u} В; I={i} А"
            b = Button(
                self.presets_container,
                text=text,
                justify="left",
                anchor="w",
                bg="#303134",
                fg=self.fg,
                activebackground="#3c4043",
                activeforeground=self.fg,
                command=make_cmd,
            )
            b.pack(fill=X, pady=2)
            self.preset_buttons.append(b)

    def _open_presets_editor(self):
        PresetsEditor(self, self.presets, self.presets_path, self._on_presets_changed)

    def _on_presets_changed(self, new_presets: dict[str, dict[str, float]]):
        self.presets = new_presets
        self._save_presets()
        self._refresh_presets_ui()


# ======================================================================
# Окно редактора пресетов
# ======================================================================

class PresetsEditor(Toplevel):
    def __init__(self, master: PSUControlPanel,
                 presets: dict[str, dict[str, float]],
                 path: str,
                 on_change):
        super().__init__(master)

        self.master_panel = master
        self.presets = dict(presets)
        self.path = path
        self.on_change = on_change

        self.bg = master.bg
        self.fg = master.fg

        self.title("Редактирование пресетов ЛБП")
        self.configure(bg=self.bg)

        self.name_var = StringVar()
        self.u_var = StringVar()
        self.i_var = StringVar()

        main = Frame(self, bg=self.bg)
        main.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Список пресетов
        left = Frame(main, bg=self.bg)
        left.pack(side=LEFT, fill=Y)

        self.listbox = Listbox(
            left,
            bg="#303134",
            fg=self.fg,
            selectmode=SINGLE,
            activestyle="dotbox",
        )
        self.listbox.pack(fill=Y, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        # Правая панель
        right = Frame(main, bg=self.bg)
        right.pack(side=RIGHT, fill=BOTH, expand=True, padx=8)

        # Имя
        row1 = Frame(right, bg=self.bg)
        row1.pack(fill=X, pady=2)
        Label(row1, text="Имя:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(
            row1,
            textvariable=self.name_var,
            bg="#303134",
            fg=self.fg,
            insertbackground=self.fg,
        ).pack(side=LEFT, fill=X, expand=True)

        # U
        row2 = Frame(right, bg=self.bg)
        row2.pack(fill=X, pady=2)
        Label(row2, text="U (В):", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(
            row2,
            textvariable=self.u_var,
            bg="#303134",
            fg=self.fg,
            insertbackground=self.fg,
            width=10,
        ).pack(side=LEFT)

        # I
        row3 = Frame(right, bg=self.bg)
        row3.pack(fill=X, pady=2)
        Label(row3, text="I (А):", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(
            row3,
            textvariable=self.i_var,
            bg="#303134",
            fg=self.fg,
            insertbackground=self.fg,
            width=10,
        ).pack(side=LEFT)

        # Кнопки
        btn_add = Button(
            right,
            text="Добавить/Обновить",
            command=self._apply,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        btn_add.pack(fill=X, pady=2)

        btn_del = Button(
            right,
            text="Удалить",
            command=self._delete,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        btn_del.pack(fill=X, pady=2)

        btn_close = Button(
            right,
            text="Закрыть",
            command=self._close,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        )
        btn_close.pack(fill=X, pady=2)

        self._reload_list()
        self.grab_set()
        self.focus_set()

    def _reload_list(self):
        self.listbox.delete(0, END)
        for name in self.presets.keys():
            self.listbox.insert(END, name)

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.listbox.get(idx)
        cfg = self.presets.get(name, {"U": 0.0, "I": 0.0})

        self.name_var.set(name)
        self.u_var.set(str(cfg.get("U", 0.0)))
        self.i_var.set(str(cfg.get("I", 0.0)))

    def _apply(self):
        name = self.name_var.get().strip()
        if not name:
            return
        try:
            u = float(self.u_var.get().replace(",", "."))
            i = float(self.i_var.get().replace(",", "."))
        except ValueError:
            return

        self.presets[name] = {"U": u, "I": i}
        self._reload_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.listbox.get(idx)
        if name in self.presets:
            del self.presets[name]
        self._reload_list()

    def _close(self):
        # перед закрытием — уведомляем панель ЛБП
        self.on_change(self.presets)
        self.destroy()
