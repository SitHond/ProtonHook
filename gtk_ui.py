#!/usr/bin/env python3
"""Single-window GTK 3 interface for ProtonHook.

Everything (game list, details, trainer choice, launch mode, delay and
messages) lives in one window; messages are shown inline in an info bar
instead of separate popup dialogs. Only the file chooser opens on top.
"""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from protontrek_core import (  # noqa: E402
    DEFAULT_LAUNCH_MODE,
    DEFAULT_DELAY_SECONDS,
    LAUNCH_MODES,
    NATIVE_LINUX_HINT,
    RunningGame,
    discover_steam_root,
    find_running_games,
    launch_mode_label,
    launch_trainer,
)


class ProtonHookWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="ProtonHook")
        self.set_default_size(1000, 600)

        self.steam_root = discover_steam_root()
        self.games: list[RunningGame] = []

        self._build_ui()
        GLib.idle_add(self.refresh_games)

    # ---------- UI ----------

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar(title="ProtonHook", subtitle="Trainer в Proton-префиксе игры")
        header.set_show_close_button(True)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_btn.set_tooltip_text("Обновить список игр")
        refresh_btn.connect("clicked", lambda _b: self.refresh_games())
        header.pack_start(refresh_btn)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        # Inline messages instead of popup dialogs.
        self.info_bar = Gtk.InfoBar()
        self.info_bar.set_show_close_button(True)
        self.info_bar.connect("response", lambda bar, _r: bar.set_revealed(False))
        self.info_label = Gtk.Label(xalign=0)
        self.info_label.set_line_wrap(True)
        self.info_label.set_selectable(True)
        self.info_bar.get_content_area().add(self.info_label)
        self.info_bar.set_revealed(False)
        root.pack_start(self.info_bar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(340)
        root.pack_start(paned, True, True, 0)

        # Left: game list
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Запущенные игры</b>")
        left.pack_start(title, False, False, 0)
        self.status_label = Gtk.Label(xalign=0, label="Поиск Steam...")
        self.status_label.get_style_context().add_class("dim-label")
        left.pack_start(self.status_label, False, False, 0)

        self.game_list = Gtk.ListBox()
        self.game_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.game_list.connect("row-selected", self.on_game_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.game_list)
        left.pack_start(scroller, True, True, 0)
        paned.pack1(left, resize=False, shrink=False)

        # Right: details + launch settings
        right = Gtk.Grid(column_spacing=12, row_spacing=10, margin=12)
        right.set_hexpand(True)
        row = 0

        def add_row(caption: str, widget: Gtk.Widget, expand: bool = False) -> None:
            nonlocal row
            label = Gtk.Label(label=caption, xalign=1, yalign=0)
            label.get_style_context().add_class("dim-label")
            right.attach(label, 0, row, 1, 1)
            widget.set_hexpand(True)
            if expand:
                widget.set_vexpand(True)
            right.attach(widget, 1, row, 1, 1)
            row += 1

        self.prefix_value = self._value_label()
        add_row("Префикс", self.prefix_value)
        self.proton_value = self._value_label()
        add_row("Proton", self.proton_value)

        self.process_view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.process_view.set_monospace(True)
        process_scroller = Gtk.ScrolledWindow()
        process_scroller.set_shadow_type(Gtk.ShadowType.IN)
        process_scroller.set_min_content_height(90)
        process_scroller.add(self.process_view)
        add_row("Процесс", process_scroller, expand=True)

        trainer_box = Gtk.Box(spacing=6)
        self.trainer_entry = Gtk.Entry(placeholder_text="Путь к trainer.exe")
        trainer_box.pack_start(self.trainer_entry, True, True, 0)
        pick_btn = Gtk.Button(label="Выбрать…")
        pick_btn.connect("clicked", self.on_pick_trainer)
        trainer_box.pack_start(pick_btn, False, False, 0)
        add_row("Trainer", trainer_box)

        self.mode_combo = Gtk.ComboBoxText()
        for key, (label, description) in LAUNCH_MODES.items():
            self.mode_combo.append(key, f"{label} — {description}")
        self.mode_combo.set_active_id(DEFAULT_LAUNCH_MODE)
        add_row("Режим запуска", self.mode_combo)

        self.delay_spin = Gtk.SpinButton.new_with_range(0, 600, 1)
        self.delay_spin.set_value(int(DEFAULT_DELAY_SECONDS))
        self.delay_spin.set_halign(Gtk.Align.START)
        add_row("Задержка, сек", self.delay_spin)

        self.launch_btn = Gtk.Button(label="Запустить в префиксе")
        self.launch_btn.get_style_context().add_class("suggested-action")
        self.launch_btn.set_halign(Gtk.Align.END)
        self.launch_btn.connect("clicked", self.on_launch)
        right.attach(self.launch_btn, 1, row, 1, 1)

        paned.pack2(right, resize=True, shrink=False)

    @staticmethod
    def _value_label() -> Gtk.Label:
        label = Gtk.Label(xalign=0, yalign=0)
        label.set_selectable(True)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.CHAR)
        return label

    def show_message(self, text: str, kind: Gtk.MessageType = Gtk.MessageType.INFO) -> None:
        self.info_bar.set_message_type(kind)
        self.info_label.set_text(text)
        self.info_bar.set_revealed(True)

    def hide_message(self) -> None:
        self.info_bar.set_revealed(False)

    # ---------- Logic ----------

    def refresh_games(self) -> bool:
        for child in self.game_list.get_children():
            self.game_list.remove(child)
        self.games.clear()
        self.hide_message()

        if not self.steam_root:
            self.status_label.set_text("Steam не найден")
            self.show_message("Steam не найден. Проверьте стандартный путь установки.", Gtk.MessageType.ERROR)
            self.clear_details()
            return False

        self.games = find_running_games(self.steam_root)
        for game in self.games:
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8)
            name = Gtk.Label(xalign=0)
            name.set_markup(f"<b>{GLib.markup_escape_text(game.app.name)}</b>")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            meta_text = f"appid {game.app.app_id} · pid {game.pid}"
            if game.native_linux:
                meta_text += " · без Proton"
            meta = Gtk.Label(xalign=0, label=meta_text)
            meta.get_style_context().add_class("dim-label")
            row_box.pack_start(name, False, False, 0)
            row_box.pack_start(meta, False, False, 0)
            self.game_list.add(row_box)
        self.game_list.show_all()

        if self.games:
            self.status_label.set_text(f"Найдено игр: {len(self.games)}")
            self.game_list.select_row(self.game_list.get_row_at_index(0))
        else:
            self.status_label.set_text("Игры не найдены")
            self.show_message(
                "Активные Steam-игры под Proton не найдены. Запустите игру и нажмите «Обновить».",
                Gtk.MessageType.WARNING,
            )
            self.clear_details()
        return False

    def clear_details(self) -> None:
        self.prefix_value.set_text("")
        self.proton_value.set_text("")
        self.process_view.get_buffer().set_text("")
        self.launch_btn.set_sensitive(False)

    def current_game(self) -> RunningGame | None:
        row = self.game_list.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        return self.games[index] if 0 <= index < len(self.games) else None

    def on_game_selected(self, _listbox: Gtk.ListBox, _row: Gtk.ListBoxRow | None) -> None:
        game = self.current_game()
        if not game:
            self.clear_details()
            return

        self.prefix_value.set_text(str(game.app.prefix_dir))
        if game.native_linux:
            self.proton_value.set_text("Не используется (нативная Linux-версия)")
            self.show_message(NATIVE_LINUX_HINT, Gtk.MessageType.WARNING)
        else:
            self.proton_value.set_text(str(game.proton_path) if game.proton_path else "Не определён")
            self.hide_message()
        self.process_view.get_buffer().set_text(
            f"PID: {game.pid}\n"
            f"Имя: {game.process_name}\n"
            f"Источник appid: {game.source}\n"
            f"Команда:\n{game.command}"
        )
        self.launch_btn.set_sensitive(not game.native_linux)

    def on_pick_trainer(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative(
            title="Выберите trainer.exe",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Выбрать",
            cancel_label="Отмена",
        )
        exe_filter = Gtk.FileFilter()
        exe_filter.set_name("Windows executables (*.exe)")
        exe_filter.add_pattern("*.exe")
        exe_filter.add_pattern("*.EXE")
        dialog.add_filter(exe_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("Все файлы")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)

        current = self.trainer_entry.get_text().strip()
        if current and Path(current).expanduser().parent.is_dir():
            dialog.set_current_folder(str(Path(current).expanduser().parent))

        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
            if filename:
                self.trainer_entry.set_text(filename)
        dialog.destroy()

    def on_launch(self, _button: Gtk.Button) -> None:
        game = self.current_game()
        if not game:
            self.show_message("Сначала выберите игру из списка.", Gtk.MessageType.ERROR)
            return

        trainer_raw = self.trainer_entry.get_text().strip()
        if not trainer_raw:
            self.show_message("Сначала выберите trainer.exe.", Gtk.MessageType.ERROR)
            return
        trainer_path = Path(trainer_raw).expanduser()
        if not trainer_path.is_file():
            self.show_message(f"Не найден файл: {trainer_path}", Gtk.MessageType.ERROR)
            return

        mode = self.mode_combo.get_active_id() or DEFAULT_LAUNCH_MODE
        delay_seconds = int(self.delay_spin.get_value())

        try:
            _process, log_path = launch_trainer(game, trainer_path, mode, delay_seconds, self.steam_root)
        except Exception as exc:  # noqa: BLE001
            self.show_message(f"Ошибка запуска: {exc}", Gtk.MessageType.ERROR)
            return

        start_text = "сразу" if delay_seconds == 0 else f"через {delay_seconds} сек"
        self.show_message(
            f"Trainer запускается для «{game.app.name}» ({launch_mode_label(mode)}, {start_text}).\n"
            f"Лог: {log_path}",
            Gtk.MessageType.INFO,
        )


def run() -> int:
    app = Gtk.Application(application_id="io.github.protonhook.ProtonHook")

    def on_activate(application: Gtk.Application) -> None:
        # A second launch just raises the existing window.
        window = application.get_active_window()
        if window is None:
            window = ProtonHookWindow(application)
            window.show_all()
            window.info_bar.set_revealed(False)
        window.present()

    app.connect("activate", on_activate)
    return app.run(None)
