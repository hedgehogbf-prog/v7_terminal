# rigol/gui.py
"""
Tkinter-панель управления электронной нагрузкой Rigol DL3021 (серия DL3000)
для встраивания в v7_terminal.

Функционал:
- выбор VISA-ресурса (USB0::...DL3...::INSTR)
- подключение / отключение
- включение / выключение входа нагрузки
- установка тока (ручной ввод)
- простые пресеты плавного ramp'а (увеличение / снижение тока)
- редактирование параметров выбранного пресета:
    - начальный ток
    - конечный ток
    - шаг тока
    - количество шагов
    - задержка между шагами
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from tkinter import (
    Frame,
    Label,
    Button,
    StringVar,
    DoubleVar,
    IntVar,
    Entry,
    OptionMenu,
    LEFT,
    RIGHT,
    TOP,
    BOTTOM,
    X,
    Y,
    BOTH,
)

from rigol.device import RigolDL3000, RigolPreset


PRESETS_FILE = Path(__file__).resolve().parent / "rigol_presets.json"


class RigolControlPanel(Frame):
    """
    Панель для размещения в правой части окна между MPPT и PSU.
    """

    def __init__(self, master, bg="#202124", fg="#e8eaed", **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.bg = bg
        self.fg = fg

        # ---------------- Состояние ----------------
        self._rigol: Optional[RigolDL3000] = None
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None

        self._ramp_thread: Optional[threading.Thread] = None
        self._ramp_stop_flag = False

        # ---------------- Переменные Tk ----------------
        self.status_var = StringVar(value="Rigol: не подключено")
        self.status_color = fg

        self.resource_var = StringVar(value="")
        self.output_state_var = StringVar(value="OFF")

        self.i_set_var = DoubleVar(value=0.0)
        self.v_meas_var = DoubleVar(value=0.0)
        self.i_meas_var = DoubleVar(value=0.0)

        # Пресеты
        self.presets: Dict[str, RigolPreset] = {}
        self._load_presets()

        self.preset_names_var = StringVar(value="")
        self.selected_preset_name = StringVar(value="")

        # Параметры редактирования пресета
        self.p_i_start = DoubleVar(value=0.0)
        self.p_i_end = DoubleVar(value=1.0)
        self.p_step = DoubleVar(value=0.1)
        self.p_delay = DoubleVar(value=0.1)

        # ---------------- Сборка интерфейса ----------------
        self._build_ui()

        # Первый рескан ресурсов
        self._rescan_resources()

    # =====================================================
    # UI
    # =====================================================

    def _build_ui(self):
        # ----- Заголовок + статус -----
        top = Frame(self, bg=self.bg)
        top.pack(side=TOP, fill=X, padx=4, pady=4)

        Label(
            top,
            text="Rigol DL3021",
            bg=self.bg,
            fg=self.fg,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=LEFT)

        self.status_label = Label(
            top,
            textvariable=self.status_var,
            bg=self.bg,
            fg=self.fg,
            anchor="w",
        )
        self.status_label.pack(side=LEFT, padx=8)

        # ----- Строка с ресурсом и кнопками -----
        row_res = Frame(self, bg=self.bg)
        row_res.pack(side=TOP, fill=X, padx=4, pady=2)

        Label(row_res, text="VISA:", bg=self.bg, fg=self.fg).pack(side=LEFT)

        self.resource_menu = OptionMenu(row_res, self.resource_var, "")
        self.resource_menu.config(bg="#303134", fg=self.fg, highlightthickness=0)
        self.resource_menu["menu"].config(bg="#303134", fg=self.fg)
        self.resource_menu.pack(side=LEFT, padx=4, fill=X, expand=True)

        Button(
            row_res,
            text="Rescan",
            command=self._rescan_resources,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        ).pack(side=LEFT, padx=2)

        self.btn_connect = Button(
            row_res,
            text="Connect",
            command=self._toggle_connect,
            bg="#1a73e8",
            fg="white",
            activebackground="#4285f4",
            activeforeground="white",
        )
        self.btn_connect.pack(side=LEFT, padx=2)

        # ----- Выход (input) и установка тока -----
        row_io = Frame(self, bg=self.bg)
        row_io.pack(side=TOP, fill=X, padx=4, pady=2)

        self.btn_output = Button(
            row_io,
            text="OUT OFF",
            command=self._toggle_output,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
            state="disabled",
        )
        self.btn_output.pack(side=LEFT, padx=2)

        Label(row_io, text="Iset (A):", bg=self.bg, fg=self.fg).pack(side=LEFT, padx=4)

        Entry(
            row_io,
            textvariable=self.i_set_var,
            bg="#303134",
            fg=self.fg,
            width=7,
        ).pack(side=LEFT, padx=2)

        Button(
            row_io,
            text="Set",
            command=self._apply_current,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
            state="disabled",
        ).pack(side=LEFT, padx=2)
        self.btn_set_current = _last_button(row_io)

        # ----- Показания V/I (как в MPPT) -----
        row_meas = Frame(self, bg=self.bg)
        row_meas.pack(side=TOP, fill=X, padx=4, pady=4)

        Label(
            row_meas,
            text="V:",
            bg=self.bg,
            fg="#b0b0b0",
            font=("Consolas", 11)
        ).pack(side=LEFT)

        Label(
            row_meas,
            textvariable=self.v_meas_var,
            bg=self.bg,
            fg="#7CFC00",          # ярко-зелёный как в MPPT
            font=("Consolas", 12, "bold"),
            width=7,
            anchor="w"
        ).pack(side=LEFT, padx=4)

        Label(
            row_meas,
            text="I:",
            bg=self.bg,
            fg="#b0b0b0",
            font=("Consolas", 11)
        ).pack(side=LEFT, padx=(12,0))

        Label(
            row_meas,
            textvariable=self.i_meas_var,
            bg=self.bg,
            fg="#7CFC00",         # такой же зелёный
            font=("Consolas", 12, "bold"),
            width=7,
            anchor="w"
        ).pack(side=LEFT, padx=4)


        # ----- Пресеты -----
        presets_frame = Frame(self, bg=self.bg)
        presets_frame.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        # Верх: выбор пресета + кнопки запуска
        top_p = Frame(presets_frame, bg=self.bg)
        top_p.pack(side=TOP, fill=X)

        Label(top_p, text="Preset:", bg=self.bg, fg=self.fg).pack(side=LEFT)

        self.preset_menu = OptionMenu(top_p, self.selected_preset_name, "")
        self.preset_menu.config(bg="#303134", fg=self.fg, highlightthickness=0)
        self.preset_menu["menu"].config(bg="#303134", fg=self.fg)
        self.preset_menu.pack(side=LEFT, padx=4, fill=X, expand=True)

        Button(
            top_p,
            text="Run ↑",
            command=lambda: self._run_ramp(direction="up"),
            bg="#303134",
            fg=self.fg,
            font=("Segoe UI", 11, "bold"),
            width=10,
            height=1,
            activebackground="#3c4043",
            activeforeground=self.fg,
        ).pack(side=LEFT, padx=2)
        self.btn_run_up = _last_button(top_p)

        Button(
            top_p,
            text="Run ↓",
            command=lambda: self._run_ramp(direction="down"),
            bg="#303134",
            fg=self.fg,
            font=("Segoe UI", 11, "bold"),
            width=10,
            height=1,
            activebackground="#3c4043",
            activeforeground=self.fg,
            state="disabled",
        ).pack(side=LEFT, padx=2)
        self.btn_run_down = _last_button(top_p)

        Button(
            top_p,
            text="Stop",
            command=self._stop_ramp,
            bg="#8a2d2d",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            width=10,
            height=1,
            activebackground="#b53939",
            activeforeground="white",
            state="disabled",
        ).pack(side=LEFT, padx=2)
        self.btn_stop_ramp = _last_button(top_p)

        # Низ: редактирование текущего пресета
        edit = Frame(presets_frame, bg=self.bg)
        edit.pack(side=TOP, fill=X, pady=4)

        _labeled_entry(edit, "I start (A):", self.p_i_start, self.bg, self.fg)
        _labeled_entry(edit, "I end (A):", self.p_i_end, self.bg, self.fg)
        _labeled_entry(edit, "Step (A):", self.p_step, self.bg, self.fg)
        _labeled_entry(edit, "Delay (s):", self.p_delay, self.bg, self.fg)

        name_row = Frame(edit, bg=self.bg)
        name_row.pack(side=TOP, fill=X, pady=1)

        Label(name_row, text="Name:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        self.preset_name_var = StringVar(value="")
        Entry(
            name_row,
            textvariable=self.preset_name_var,
            bg="#303134",
            fg=self.fg,
            width=12
        ).pack(side=LEFT, padx=4)

        Button(
            name_row,
            text="Rename",
            command=self._rename_preset,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        ).pack(side=LEFT, padx=4)

        Button(
            edit,
            text="Save preset",
            command=self._save_current_preset,
            bg="#303134",
            fg=self.fg,
            activebackground="#3c4043",
            activeforeground=self.fg,
        ).pack(side=BOTTOM, anchor="e", padx=2, pady=4)

        # инициализируем список пресетов в UI
        self._refresh_presets_menu()

    # =====================================================
    # Работа с пресетами
    # =====================================================

    def _load_presets(self):
        if PRESETS_FILE.is_file():
            try:
                data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            # пресеты по умолчанию
            data = {
                "Soft 0→2A": {
                    "i_start": 0.0,
                    "i_end": 2.0,
                    "step": 0.1,
                    "delay_s": 0.1,
                },
                "Soft 2→0A": {
                    "i_start": 2.0,
                    "i_end": 0.0,
                    "step": 0.1,
                    "delay_s": 0.1,
                },
            }

        self.presets.clear()
        for name, p in data.items():
            self.presets[name] = RigolPreset(
                name=name,
                i_start=float(p.get("i_start", 0.0)),
                i_end=float(p.get("i_end", 1.0)),
                step=float(p.get("step", 0.1)),
                delay_s=float(p.get("delay_s", 0.1)),
            )

        if not self.presets:
            # гарантируем хотя бы один
            self.presets["Default"] = RigolPreset(
                name="Default",
                i_start=0.0,
                i_end=1.0,
                step=0.1,
                delay_s=0.1,
            )

    def _save_presets_file(self):
        data = {}
        for name, p in self.presets.items():
            data[name] = {
                "i_start": p.i_start,
                "i_end": p.i_end,
                "step": p.step,
                "delay_s": p.delay_s,
            }
        PRESETS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _refresh_presets_menu(self):
        names: List[str] = list(self.presets.keys())
        if not names:
            names = ["<none>"]
        menu = self.preset_menu["menu"]
        menu.delete(0, "end")
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self._select_preset(v))
        self.preset_names_var.set(",".join(names))
        if not self.selected_preset_name.get() or self.selected_preset_name.get() not in names:
            self.selected_preset_name.set(names[0])
        self._apply_preset_to_edit(self.selected_preset_name.get())

    def _select_preset(self, name: str):
        self.selected_preset_name.set(name)
        self._apply_preset_to_edit(name)

    def _apply_preset_to_edit(self, name: str):
        p = self.presets.get(name)
        if not p:
            return
        self.p_i_start.set(p.i_start)
        self.p_i_end.set(p.i_end)
        self.p_step.set(p.step)
        self.p_delay.set(p.delay_s)

    def _save_current_preset(self):
        name = self.selected_preset_name.get().strip() or "Preset"
        p = RigolPreset(
            name=name,
            i_start=self.p_i_start.get(),
            i_end=self.p_i_end.get(),
            step=self.p_step.get(),
            delay_s=self.p_delay.get(),
        )
        self.presets[name] = p
        self._save_presets_file()
        self._refresh_presets_menu()
        self._set_status(f"Preset '{name}' сохранён", "cyan")

    # =====================================================
    # Подключение / отключение / опрос
    # =====================================================

    def _rescan_resources(self):
        resources = RigolDL3000.discover_usb_resources()
        # Обновим OptionMenu
        menu = self.resource_menu["menu"]
        menu.delete(0, "end")
        current_value = self.resource_var.get()
        if resources:
            for r in resources:
                menu.add_command(label=r, command=lambda v=r: self.resource_var.set(v))
            if current_value not in resources:
                self.resource_var.set(resources[0])
        else:
            self.resource_var.set("")
        self._set_status("Сканирование VISA ресурсов завершено", "cyan")

    def _toggle_connect(self):
        if self._rigol is None:
            self._connect()
        else:
            self._disconnect()

    def _connect(self):
        resource = self.resource_var.get().strip()
        if not resource:
            self._set_status("Нет выбранного VISA-ресурса", "red")
            return
        try:
            dev = RigolDL3000(resource)
            dev.open()
            idn = dev.read_identity()
        except Exception as e:
            self._set_status(f"Ошибка подключения: {e}", "red")
            return

        self._rigol = dev
        self.btn_connect.config(text="Disconnect", bg="#5f6368")
        self.btn_output.config(state="normal")
        self.btn_set_current.config(state="normal")
        self.btn_run_up.config(state="normal")
        self.btn_run_down.config(state="normal")
        self.btn_stop_ramp.config(state="normal")

        self._set_status(f"Rigol подключен: {idn}", "green")
        self.output_state_var.set("OFF")
        self.btn_output.config(text="OUT OFF", bg="#303134")

        # запускаем поток опроса
        self._start_polling()

    def _disconnect(self):
        self._stop_polling()
        self._stop_ramp()
        if self._rigol is not None:
            try:
                self._rigol.close()
            except Exception:
                pass
        self._rigol = None
        self.btn_connect.config(text="Connect", bg="#1a73e8")
        self.btn_output.config(state="disabled")
        self.btn_set_current.config(state="disabled")
        self.btn_run_up.config(state="disabled")
        self.btn_run_down.config(state="disabled")
        self.btn_stop_ramp.config(state="disabled")
        self._set_status("Rigol отключен", "yellow")

    # Опрос V/I в фоне

    def _start_polling(self):
        if self._polling:
            return
        self._polling = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop_polling(self):
        self._polling = False
        if self._poll_thread is not None:
            self._poll_thread = None

    def _poll_loop(self):
        while self._polling and self._rigol is not None:
            try:
                v = self._rigol.measure_voltage()
                i = self._rigol.measure_current()
                self.v_meas_var.set(round(v, 4))
                self.i_meas_var.set(round(i, 4))
            except Exception:
                # не заваливаем поток
                pass
            time.sleep(0.5)


    def _rename_preset(self):
        old = self.selected_preset_name.get()
        new = self.preset_name_var.get().strip()
        if not new:
            self._set_status("Имя пустое", "red")
            return
        if old not in self.presets:
            self._set_status("Нет выбранного пресета", "red")
            return
        p = self.presets.pop(old)
        p.name = new
        self.presets[new] = p
        self.selected_preset_name.set(new)
        self._save_presets_file()
        self._refresh_presets_menu()
        self._set_status(f"Имя изменено: {old} → {new}", "green")

    # =====================================================
    # Управление выходом / током
    # =====================================================

    def _toggle_output(self):
        if self._rigol is None:
            return
        try:
            state = self._rigol.get_output()
            new_state = not state
            self._rigol.set_output(new_state)
            self.output_state_var.set("ON" if new_state else "OFF")
            self.btn_output.config(
                text=f"OUT {'ON' if new_state else 'OFF'}",
                bg="#188038" if new_state else "#303134",
            )
            self._set_status(f"Выход Rigol: {'ON' if new_state else 'OFF'}", "green")
        except Exception as e:
            self._set_status(f"Ошибка OUT: {e}", "red")

    def _apply_current(self):
        if self._rigol is None:
            return
        try:
            current = float(self.i_set_var.get())
        except Exception:
            self._set_status("Некорректный ток", "red")
            return
        try:
            self._rigol.set_current(current)
            self._set_status(f"Iset = {current} A", "green")
        except Exception as e:
            self._set_status(f"Ошибка установки тока: {e}", "red")

    # =====================================================
    # Ramp (плавное изменение тока)
    # =====================================================

    def _run_ramp(self, direction: str):
        if self._rigol is None:
            self._set_status("Rigol не подключен", "red")
            return
        name = self.selected_preset_name.get()
        p = self.presets.get(name)
        if not p:
            self._set_status("Нет выбранного пресета", "red")
            return

        # останавливаем предыдущий ramp
        self._stop_ramp()

        self._ramp_stop_flag = False
        self._ramp_thread = threading.Thread(
            target=self._ramp_worker, args=(p, direction), daemon=True
        )
        self._ramp_thread.start()
        self._set_status(f"Ramp '{name}' ({direction}) запущен", "cyan")

    def _stop_ramp(self):
        self._ramp_stop_flag = True
        self._ramp_thread = None
        self._set_status("Ramp остановлен", "yellow")

    def _ramp_worker(self, preset: RigolPreset, direction: str):
        """
        Выполняет плавное изменение тока в отдельном потоке.
        direction: "up" или "down"
        """
        try:
            if direction == "up":
                i_start = preset.i_start
                i_end = preset.i_end
                step_sign = 1.0
            else:
                i_start = preset.i_end
                i_end = preset.i_start
                step_sign = -1.0

            # вычисляем количество шагов
            delta = abs(preset.i_end - preset.i_start)
            if delta == 0:
                steps = 1
            else:
                steps = max(1, int(delta / abs(preset.step)) + 1)

            step = abs(preset.step) * step_sign

            delay = max(0.0, preset.delay_s)

            current = i_start
            self._rigol.set_current(current)
            self.i_set_var.set(current)

            for _ in range(steps):
                if self._ramp_stop_flag or self._rigol is None:
                    break
                current += step
                # ограничим диапазоном [min(i_start, i_end), max(...)]
                low = min(i_start, i_end)
                high = max(i_start, i_end)
                if current < low:
                    current = low
                if current > high:
                    current = high

                self._rigol.set_current(current)
                self.i_set_var.set(current)
                time.sleep(delay)

                if (step_sign > 0 and current >= i_end) or (step_sign < 0 and current <= i_end):
                    break

            self._set_status(f"Ramp '{preset.name}' завершён", "green")
        except Exception as e:
            self._set_status(f"Ошибка ramp: {e}", "red")

    # =====================================================
    # Статус
    # =====================================================

    def _set_status(self, msg: str, color: str = "white"):
        self.status_var.set(msg)
        self.status_label.config(fg=color)


# ----------------------------------------------------------------------
# Вспомогательные функции для сборки UI
# ----------------------------------------------------------------------


def _labeled_entry(parent, label_text, var, bg, fg, is_int: bool = False):
    row = Frame(parent, bg=bg)
    row.pack(side=TOP, fill=X, pady=1)
    Label(row, text=label_text, bg=bg, fg=fg).pack(side=LEFT)
    width = 7
    e = Entry(row, textvariable=var, bg="#303134", fg=fg, width=width)
    e.pack(side=LEFT, padx=4)


def _last_button(parent):
    """Возвращает последний созданный Button в parent (хак для сохранения ссылки)."""
    children = parent.winfo_children()
    for w in reversed(children):
        if isinstance(w, Button):
            return w
    return None
