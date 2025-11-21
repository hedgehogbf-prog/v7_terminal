# psu/gui.py
"""
GUI управления OWON SPE6103 (через owon-psu).
"""

import json
import os
from tkinter import (
    Frame, Label, Button, Entry, StringVar,
    LEFT, RIGHT, TOP, BOTTOM, X, Y, BOTH,
    Toplevel, Listbox, SINGLE, END
)
from tkinter import font as tkfont
from tkinter import ttk

from serial.tools import list_ports
from psu.owon import OwonPSU

DEFAULT_PRESETS_PATH = os.path.join(
    os.path.expanduser("~"),
    "Documents", "v7", "lbp_presets.json"
)

DEFAULT_PRESETS = {
    "0V 0A": {"U": 0.0, "I": 0.0},
    "5V 1A": {"U": 5.0, "I": 1.0},
    "12V 3A": {"U": 12.0, "I": 3.0},
}


class PSUControlPanel(Frame):
    POLL_INTERVAL_MS = 200

    def __init__(self, master, bg="#202124", fg="#e8eaed", **kw):
        super().__init__(master, bg=bg, **kw)
        self.bg = bg
        self.fg = fg

        self.psu = OwonPSU()
        self.port_var = StringVar()

        self.u_meas_var = StringVar(value="0.00 V")
        self.i_meas_var = StringVar(value="0.000 A")

        self.u_set_var = StringVar(value="0.0")
        self.i_set_var = StringVar(value="0.0")

        # пресеты
        self.presets_path = DEFAULT_PRESETS_PATH
        self.presets = {}
        self._load_presets()

        # шрифты
        self.font_big = tkfont.Font(size=28, weight="bold")
        self.font_small = tkfont.Font(size=12)

        self._build_ui()

        # запуск опроса ЛБП
        self.after(self.POLL_INTERVAL_MS, self._poll_psu)

    # ============================================================
    #   BUILD UI
    # ============================================================

    def _build_ui(self):
        # Верхняя панель – выбор порта
        top = Frame(self, bg=self.bg)
        top.pack(side=TOP, fill=X, padx=4, pady=4)

        Label(top, text="ЛБП:", bg=self.bg, fg=self.fg).pack(side=LEFT)

        self.combo_port = ttk.Combobox(top, textvariable=self.port_var, width=10)
        self.combo_port.pack(side=LEFT, padx=4)
        self._refresh_ports()

        Button(
            top, text="Обновить", command=self._refresh_ports,
            bg="#303134", fg=self.fg
        ).pack(side=LEFT, padx=2)

        self.btn_connect = Button(
            top, text="Подключить",
            command=self._toggle_connect,
            bg="#303134", fg=self.fg
        )
        self.btn_connect.pack(side=LEFT, padx=2)

        Button(
            top, text="Reset COM",
            command=self._reset_com,
            bg="#303134", fg=self.fg
        ).pack(side=LEFT, padx=2)

        # ---------------------------
        # Статусбар (перенесён)
        # ---------------------------
        self.status_label = Label(
            self, text="Не подключено",
            bg=self.bg, fg=self.fg,
            anchor="w"
        )
        self.status_label.pack(side=TOP, fill=X, padx=4)

        # ---------------------------
        # Центральная часть
        # ---------------------------
        center = Frame(self, bg=self.bg)
        center.pack(side=TOP, fill=X, padx=4, pady=4)

        # Блок измеренных значений
        left = Frame(center, bg=self.bg)
        left.pack(side=LEFT, fill=BOTH, expand=True)

        Label(left, text="Измерено", bg=self.bg, fg=self.fg).pack(anchor="w")

        Label(left, textvariable=self.u_meas_var,
              bg=self.bg, fg="#3aff3a", font=self.font_big).pack(anchor="w")

        Label(left, textvariable=self.i_meas_var,
              bg=self.bg, fg="#3aff3a", font=self.font_big).pack(anchor="w")

        # Блок установок
        right = Frame(center, bg=self.bg)
        right.pack(side=RIGHT, fill=Y)

        Label(right, text="Установлено", bg=self.bg, fg=self.fg).pack(anchor="w")

        row_u = Frame(right, bg=self.bg); row_u.pack(fill=X, pady=2)
        Label(row_u, text="U, В:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(row_u, textvariable=self.u_set_var,
              bg="#303134", fg=self.fg, insertbackground=self.fg, width=8).pack(side=LEFT, padx=2)

        row_i = Frame(right, bg=self.bg); row_i.pack(fill=X, pady=2)
        Label(row_i, text="I, А:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(row_i, textvariable=self.i_set_var,
              bg="#303134", fg=self.fg, insertbackground=self.fg, width=8).pack(side=LEFT, padx=2)

        Button(
            right, text="Применить",
            command=self._apply_setpoints,
            bg="#303134", fg=self.fg
        ).pack(fill=X, pady=4)

        self.btn_output = Button(
            right, text="Выход: OFF",
            command=self._toggle_output,
            bg="#303134", fg=self.fg
        )
        self.btn_output.pack(fill=X)

        # ---------------------------
        # Пресеты
        # ---------------------------
        presets_frame = Frame(self, bg=self.bg)
        presets_frame.pack(side=TOP, fill=BOTH, expand=True, padx=4, pady=4)

        Label(presets_frame, text="Пресеты", bg=self.bg, fg=self.fg).pack(anchor="w")

        Button(
            presets_frame, text="Редактировать",
            command=self._open_presets_editor,
            bg="#303134", fg=self.fg
        ).pack(anchor="e")

        self.container_presets = Frame(presets_frame, bg=self.bg)
        self.container_presets.pack(fill=BOTH, expand=True)

        self._rebuild_presets()

    # ============================================================
    #   PORTS
    # ============================================================

    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.combo_port["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        if self.psu.connected:
            self.psu.disconnect()
            self.btn_connect.config(text="Подключить")
            self.status_label.config(text="Отключено")
            return

        port = self.port_var.get()
        if not port:
            self.status_label.config(text="Порт не выбран", fg="#ff5555")
            return

        ok = self.psu.connect(port)
        if not ok:
            self.status_label.config(text="Ошибка подключения", fg="#ff5555")
            return

        ident = self.psu.identify() or f"Подключено к {port}"
        self.status_label.config(text=ident, fg=self.fg)
        self.btn_connect.config(text="Отключить")

    def _reset_com(self):
        if not self.psu.port:
            self.status_label.config(text="Reset: порт не выбран", fg="#ff5555")
            return
        ok = self.psu.reset_com()
        self.status_label.config(
            text="Сброс успешен" if ok else "Ошибка reset COM",
            fg=self.fg if ok else "#ff5555"
        )

    # ============================================================
    #   PSU POLLING
    # ============================================================

    def _poll_psu(self):
        if self.psu.connected:
            u, i = self.psu.read_measurements()
            if u is not None:
                self.u_meas_var.set(f"{u:6.3f} V")
            else:
                self.u_meas_var.set("--.-- V")

            if i is not None:
                self.i_meas_var.set(f"{i:6.3f} A")
            else:
                self.i_meas_var.set("--.-- A")

        self.after(self.POLL_INTERVAL_MS, self._poll_psu)

    # ============================================================
    #   SETTINGS / OUTPUT
    # ============================================================

    def _apply_setpoints(self):
        try:
            u = float(self.u_set_var.get().replace(",", "."))
            i = float(self.i_set_var.get().replace(",", "."))
        except ValueError:
            self.status_label.config(text="Неверный формат", fg="#ff5555")
            return

        if not self.psu.connected:
            self.status_label.config(text="ЛБП не подключен", fg="#ff5555")
            return

        self.psu.set_voltage_current(u, i)
        self.status_label.config(text="Установлено", fg=self.fg)

    def _toggle_output(self):
        if not self.psu.connected:
            self.status_label.config(text="ЛБП не подключен", fg="#ff5555")
            return

        new_state = not self.psu.device.output_state
        self.psu.set_output(new_state)
        self.btn_output.config(text=f"Выход: {'ON' if new_state else 'OFF'}")

    # ============================================================
    #   PRESETS
    # ============================================================

    def _load_presets(self):
        try:
            if os.path.exists(self.presets_path):
                with open(self.presets_path, "r", encoding="utf-8") as f:
                    presets = json.load(f)
                    if isinstance(presets, dict):
                        self.presets = presets
                        return
        except Exception:
            pass

        self.presets = DEFAULT_PRESETS.copy()
        self._save_presets()

    def _save_presets(self):
        os.makedirs(os.path.dirname(self.presets_path), exist_ok=True)
        with open(self.presets_path, "w", encoding="utf-8") as f:
            json.dump(self.presets, f, indent=2, ensure_ascii=False)

    def _rebuild_presets(self):
        for w in self.container_presets.winfo_children():
            w.destroy()

        for name, cfg in self.presets.items():
            u, i = cfg["U"], cfg["I"]
            btn = Button(
                self.container_presets,
                text=f"{name}\nU={u}В  I={i}A",
                justify="left", anchor="w",
                bg="#303134", fg=self.fg,
                wraplength=200,
                command=lambda u=u, i=i: self._apply_preset(u, i),
            )
            btn.pack(fill=X, pady=2)

    def _apply_preset(self, u, i):
        self.u_set_var.set(u)
        self.i_set_var.set(i)
        if self.psu.connected:
            self._apply_setpoints()

    # ============================================================
    #   PRESET EDITOR
    # ============================================================

    def _open_presets_editor(self):
        PresetsEditor(self, self.presets, self.presets_path, self._on_presets_changed)


class PresetsEditor(Toplevel):
    def __init__(self, master: PSUControlPanel, presets, path, on_change):
        super().__init__(master)
        self.master = master
        self.bg = master.bg
        self.fg = master.fg
        self.presets = dict(presets)
        self.path = path
        self.on_change = on_change

        self.name_var = StringVar()
        self.u_var = StringVar()
        self.i_var = StringVar()

        self._build_ui()
        self._reload_list()
        self.grab_set()

    def _build_ui(self):
        self.configure(bg=self.bg)
        self.title("Редактирование пресетов")

        top = Frame(self, bg=self.bg)
        top.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.listbox = Listbox(top, bg="#303134", fg=self.fg, selectmode=SINGLE)
        self.listbox.pack(side=LEFT, fill=Y)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        right = Frame(top, bg=self.bg); right.pack(side=RIGHT, fill=BOTH, expand=True)

        row1 = Frame(right, bg=self.bg); row1.pack(fill=X)
        Label(row1, text="Имя:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(row1, textvariable=self.name_var, bg="#303134", fg=self.fg,
              insertbackground=self.fg).pack(side=LEFT, fill=X, expand=True)

        row2 = Frame(right, bg=self.bg); row2.pack(fill=X)
        Label(row2, text="U:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(row2, textvariable=self.u_var, width=8,
              bg="#303134", fg=self.fg).pack(side=LEFT)

        row3 = Frame(right, bg=self.bg); row3.pack(fill=X)
        Label(row3, text="I:", bg=self.bg, fg=self.fg).pack(side=LEFT)
        Entry(row3, textvariable=self.i_var, width=8,
              bg="#303134", fg=self.fg).pack(side=LEFT)

        Button(right, text="Добавить/обновить", command=self._apply,
               bg="#303134", fg=self.fg).pack(fill=X, pady=4)
        Button(right, text="Удалить", command=self._delete,
               bg="#303134", fg=self.fg).pack(fill=X, pady=4)
        Button(right, text="Закрыть", command=self._close,
               bg="#303134", fg=self.fg).pack(fill=X, pady=4)

    def _reload_list(self):
        self.listbox.delete(0, END)
        for key in self.presets.keys():
            self.listbox.insert(END, key)

    def _on_select(self, *_):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        u = self.presets[name]["U"]
        i = self.presets[name]["I"]
        self.name_var.set(name)
        self.u_var.set(str(u))
        self.i_var.set(str(i))

    def _apply(self):
        try:
            name = self.name_var.get().strip()
            if not name:
                return
            u = float(self.u_var.get().replace(",", "."))
            i = float(self.i_var.get().replace(",", "."))
            self.presets[name] = {"U": u, "I": i}
            self._reload_list()
        except:
            pass

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        key = self.listbox.get(sel[0])
        if key in self.presets:
            del self.presets[key]
        self._reload_list()

    def _close(self):
        self.on_change(self.presets)
        self.destroy()
