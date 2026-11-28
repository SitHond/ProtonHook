#!/usr/bin/env python3
"""Single-window GTK 3 interface for ProtonHook.

Tabs: «Запуск» (launch a trainer into a running game's prefix),
«Диагностика» (automatic checks + one-click fixes) and «Справка» (what to
do in common failure cases). Messages are shown inline in an info bar;
long operations run in a background thread with their output in a log view.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from protontrek_core import (  # noqa: E402
    DEFAULT_DELAY_SECONDS,
    DEFAULT_LAUNCH_MODE,
    EXPERIMENTAL_PROTON_HINT,
    LAUNCH_MODES,
    NATIVE_LINUX_HINT,
    RunningGame,
    discover_steam_root,
    find_running_games,
    is_experimental_proton,
    launch_mode_label,
    launch_trainer,
)
from protonhook_tools import (  # noqa: E402
    BACKUP_ROOT,
    DOTNET_REAL,
    PrefixGame,
    close_trainer_instances,
    copy_saves,
    diagnose,
    find_unity_saves,
    install_dotnet48,
    installed_prefix_games,
    backup_prefix,
    prefix_dotnet_status,
    prefix_in_use,
    read_exe_info,
    help_text,
    restore_prefix,
)
from i18n import LANGUAGES, detect_language, get_language, set_language, tr  # noqa: E402

SETTINGS_PATH = Path.home() / ".config/protonhook/settings.json"
TRAINER_SEARCH_DIRS = [Path.home() / "trainers", Path.home() / "Trainers", Path.home() / "Downloads",
                       Path.home() / "Загрузки"]


@dataclass
class GameEntry:
    prefix: PrefixGame
    running: RunningGame | None


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def guess_trainer(game_name: str) -> Path | None:
    """Look for a trainer .exe whose path mentions the game name."""
    key = normalize(game_name)
    if not key:
        return None
    for directory in TRAINER_SEARCH_DIRS:
        if not directory.is_dir():
            continue
        for exe in sorted(directory.rglob("*.exe")):
            rel = normalize(str(exe.relative_to(directory)))
            if key in rel and "trainer" in rel:
                return exe
    return None


class ProtonHookWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="ProtonHook")
        self.set_default_size(1100, 680)

        self.steam_root = discover_steam_root()
        self.entries: list[GameEntry] = []
        self.settings = load_settings()
        self.busy = False
        self._info_action: Callable[[], None] | None = None

        self._build_ui()
        GLib.idle_add(self.refresh_games)

    # ================================================================ UI

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar(title="ProtonHook", subtitle=tr("Трейнеры для игр в Proton"))
        header.set_show_close_button(True)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_btn.set_tooltip_text(tr("Обновить список игр"))
        refresh_btn.connect("clicked", lambda _b: self.refresh_games())
        header.pack_start(refresh_btn)
        self.language_combo = Gtk.ComboBoxText()
        for code, name in LANGUAGES.items():
            self.language_combo.append(code, name)
        self.language_combo.set_active_id(get_language())
        self.language_combo.set_tooltip_text(tr("Язык интерфейса"))
        self.language_combo.set_valign(Gtk.Align.CENTER)
        self.language_combo.connect("changed", self.on_language_changed)
        header.pack_end(self.language_combo)
        self.spinner = Gtk.Spinner()
        header.pack_end(self.spinner)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        self.info_bar = Gtk.InfoBar()
        self.info_bar.set_show_close_button(True)
        self.info_action_btn = self.info_bar.add_button("", 1)
        self.info_bar.connect("response", self._on_info_response)
        self.info_label = Gtk.Label(xalign=0)
        self.info_label.set_line_wrap(True)
        self.info_label.set_selectable(True)
        self.info_bar.get_content_area().add(self.info_label)
        root.pack_start(self.info_bar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(330)
        root.pack_start(paned, True, True, 0)

        # ---- left: games
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>" + tr("Игры с Proton-префиксом") + "</b>")
        left.pack_start(title, False, False, 0)
        self.status_label = Gtk.Label(xalign=0, label=tr("Поиск Steam..."))
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

        # ---- right: tabs
        self.notebook = Gtk.Notebook()
        self.notebook.append_page(self._build_launch_tab(), Gtk.Label(label=tr("Запуск")))
        self.notebook.append_page(self._build_diag_tab(), Gtk.Label(label=tr("Диагностика")))
        self.notebook.append_page(self._build_help_tab(), Gtk.Label(label=tr("Справка")))
        paned.pack2(self.notebook, resize=True, shrink=False)

    def _build_launch_tab(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, margin=12)
        grid.set_hexpand(True)
        row = 0

        def add_row(caption: str, widget: Gtk.Widget, expand: bool = False) -> None:
            nonlocal row
            label = Gtk.Label(label=caption, xalign=1, yalign=0)
            label.get_style_context().add_class("dim-label")
            grid.attach(label, 0, row, 1, 1)
            widget.set_hexpand(True)
            if expand:
                widget.set_vexpand(True)
            grid.attach(widget, 1, row, 1, 1)
            row += 1

        self.state_value = self._value_label()
        add_row(tr("Состояние"), self.state_value)
        self.prefix_value = self._value_label()
        add_row(tr("Префикс"), self.prefix_value)
        self.proton_value = self._value_label()
        add_row("Proton", self.proton_value)

        self.process_view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.process_view.set_monospace(True)
        process_scroller = Gtk.ScrolledWindow()
        process_scroller.set_shadow_type(Gtk.ShadowType.IN)
        process_scroller.set_min_content_height(80)
        process_scroller.add(self.process_view)
        add_row(tr("Процесс"), process_scroller, expand=True)

        trainer_box = Gtk.Box(spacing=6)
        self.trainer_entry = Gtk.Entry(placeholder_text=tr("Путь к trainer.exe"))
        self.trainer_entry.connect("changed", lambda _e: self._remember_trainer())
        trainer_box.pack_start(self.trainer_entry, True, True, 0)
        pick_btn = Gtk.Button(label=tr("Выбрать…"))
        pick_btn.connect("clicked", self.on_pick_trainer)
        trainer_box.pack_start(pick_btn, False, False, 0)
        add_row(tr("Трейнер"), trainer_box)

        self.mode_combo = Gtk.ComboBoxText()
        for key, (label, description) in LAUNCH_MODES.items():
            self.mode_combo.append(key, f"{label} — {tr(description)}")
        self.mode_combo.set_active_id(DEFAULT_LAUNCH_MODE)
        add_row(tr("Режим запуска"), self.mode_combo)

        self.delay_spin = Gtk.SpinButton.new_with_range(0, 600, 1)
        self.delay_spin.set_value(int(DEFAULT_DELAY_SECONDS))
        self.delay_spin.set_halign(Gtk.Align.START)
        add_row(tr("Задержка, сек"), self.delay_spin)

        self.launch_btn = Gtk.Button(label=tr("Запустить в префиксе"))
        self.launch_btn.get_style_context().add_class("suggested-action")
        self.launch_btn.set_halign(Gtk.Align.END)
        self.launch_btn.connect("clicked", self.on_launch)
        grid.attach(self.launch_btn, 1, row, 1, 1)
        return grid

    def _build_diag_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)

        self.checks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.checks_box, False, False, 0)

        actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                              column_spacing=6, row_spacing=6, homogeneous=True)
        self.action_buttons: list[Gtk.Button] = []

        def add_action(label: str, tooltip: str, handler: Callable[[], None]) -> Gtk.Button:
            button = Gtk.Button(label=label)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", lambda _b: handler())
            actions.add(button)
            self.action_buttons.append(button)
            return button

        self.dotnet_btn = add_action(tr("Установить .NET 4.8"), tr("Нужно для большинства .NET-трейнеров (FLiNG и др.). Игра должна быть закрыта. "
                                     "Сначала делается резервная копия префикса."),
                                     self.on_install_dotnet)
        add_action(tr("Резервная копия префикса"), tr("Архив префикса в {path}", path=BACKUP_ROOT), self.on_backup_prefix)
        add_action(tr("Восстановить префикс…"), tr("Вернуть префикс из резервной копии"), self.on_restore_prefix)
        self.save_l2w_btn = add_action(tr("Сейв Linux → Windows"), tr("Перенести сейв Unity-игры из нативной версии в Proton"),
                                       lambda: self.on_copy_saves(to_windows=True))
        self.save_w2l_btn = add_action(tr("Сейв Windows → Linux"), tr("Перенести сейв Unity-игры из Proton в нативную версию"),
                                       lambda: self.on_copy_saves(to_windows=False))
        add_action(tr("Перепроверить"), tr("Заново выполнить проверки"), self.update_diagnostics)
        box.pack_start(actions, False, False, 0)

        log_title = Gtk.Label(xalign=0)
        log_title.set_markup("<b>" + tr("Журнал действий") + "</b>")
        box.pack_start(log_title, False, False, 0)
        self.log_view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_monospace(True)
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_shadow_type(Gtk.ShadowType.IN)
        log_scroller.add(self.log_view)
        box.pack_start(log_scroller, True, True, 0)
        return box

    def _build_help_tab(self) -> Gtk.Widget:
        label = Gtk.Label(xalign=0, yalign=0, margin=16)
        label.set_markup(help_text())
        label.set_line_wrap(True)
        label.set_selectable(True)
        scroller = Gtk.ScrolledWindow()
        scroller.add(label)
        return scroller

    @staticmethod
    def _value_label() -> Gtk.Label:
        label = Gtk.Label(xalign=0, yalign=0)
        label.set_selectable(True)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.CHAR)
        return label

    def on_language_changed(self, combo: Gtk.ComboBoxText) -> None:
        code = combo.get_active_id()
        if not code or code == get_language():
            return
        if self.busy:
            combo.set_active_id(get_language())
            self.show_message(tr("Уже выполняется другое действие — дождитесь окончания."), Gtk.MessageType.WARNING)
            return
        set_language(code)
        self.settings["language"] = code
        save_settings(self.settings)
        # Rebuild the window so every label is created in the new language.
        open_window(self.get_application())
        self.destroy()

    # ================================================================ messages

    def show_message(
        self,
        text: str,
        kind: Gtk.MessageType = Gtk.MessageType.INFO,
        action: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        self.info_bar.set_message_type(kind)
        self.info_label.set_text(text)
        if action:
            self.info_action_btn.set_label(action[0])
            self.info_action_btn.show()
            self._info_action = action[1]
        else:
            self.info_action_btn.hide()
            self._info_action = None
        self.info_bar.set_revealed(True)

    def hide_message(self) -> None:
        self.info_bar.set_revealed(False)

    def _on_info_response(self, bar: Gtk.InfoBar, response: int) -> None:
        if response == 1 and self._info_action:
            self._info_action()
        bar.set_revealed(False)

    def log(self, text: str) -> None:
        """Thread-safe append to the action log."""
        def append() -> bool:
            buffer = self.log_view.get_buffer()
            buffer.insert(buffer.get_end_iter(), time.strftime("[%H:%M:%S] ") + text + "\n")
            self.log_view.scroll_to_iter(buffer.get_end_iter(), 0, False, 0, 0)
            return False
        GLib.idle_add(append)

    # ================================================================ games

    def refresh_games(self) -> bool:
        current = self.current_entry()
        selected_id = current.prefix.app.app_id if current else self.settings.get("last_app_id")
        for child in self.game_list.get_children():
            self.game_list.remove(child)
        self.entries.clear()
        self.hide_message()

        if not self.steam_root:
            self.status_label.set_text(tr("Steam не найден"))
            self.show_message(tr("Steam не найден. Проверьте стандартный путь установки."), Gtk.MessageType.ERROR)
            self.clear_details()
            return False

        running = {game.app.app_id: game for game in find_running_games(self.steam_root)}
        if current is None and running:
            selected_id = None  # a running game (sorted first) wins on startup
        prefix_games = {g.app.app_id: g for g in installed_prefix_games(self.steam_root)}
        for app_id, game in running.items():
            prefix = prefix_games.get(app_id) or PrefixGame(app=game.app, proton_path=None)
            # The Proton the game is actually running with beats config_info.
            if game.proton_path and not game.native_linux:
                prefix.proton_path = game.proton_path
            prefix_games[app_id] = prefix
        ordered = sorted(prefix_games.values(), key=lambda g: (g.app.app_id not in running, g.app.name.lower()))
        self.entries = [GameEntry(prefix=g, running=running.get(g.app.app_id)) for g in ordered]

        for entry in self.entries:
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8)
            name = Gtk.Label(xalign=0)
            marker = "● " if entry.running else ""
            name.set_markup(f"<b>{marker}{GLib.markup_escape_text(entry.prefix.app.name)}</b>")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            meta_text = f"appid {entry.prefix.app.app_id}"
            if entry.running:
                meta_text += " · " + tr("запущена") + (tr(" без Proton") if entry.running.native_linux else "")
            meta = Gtk.Label(xalign=0, label=meta_text)
            meta.get_style_context().add_class("dim-label")
            row_box.pack_start(name, False, False, 0)
            row_box.pack_start(meta, False, False, 0)
            self.game_list.add(row_box)
        self.game_list.show_all()

        self.status_label.set_text(tr("Запущено: {running} · всего: {total}", running=len(running), total=len(self.entries)))
        if not self.entries:
            self.show_message(tr("Игры с Proton-префиксом не найдены."), Gtk.MessageType.WARNING)
            self.clear_details()
            return False

        index = 0
        for i, entry in enumerate(self.entries):
            if entry.prefix.app.app_id == selected_id:
                index = i
                break
        selected_row = self.game_list.get_row_at_index(index)
        self.game_list.select_row(selected_row)
        # Scroll the selection into view once the list has been allocated.
        GLib.idle_add(lambda: (selected_row.grab_focus(), False)[1])
        if not running:
            self.show_message(tr("Запущенных игр нет. Запустите игру через Steam и нажмите «Обновить». "
                                 "Диагностика и исправления доступны и для закрытых игр."),
                              Gtk.MessageType.INFO)
        return False

    def clear_details(self) -> None:
        for label in (self.state_value, self.prefix_value, self.proton_value):
            label.set_text("")
        self.process_view.get_buffer().set_text("")
        self.launch_btn.set_sensitive(False)

    def current_entry(self) -> GameEntry | None:
        row = self.game_list.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        return self.entries[index] if 0 <= index < len(self.entries) else None

    def current_trainer(self) -> Path | None:
        raw = self.trainer_entry.get_text().strip()
        return Path(raw).expanduser() if raw else None

    def _remember_trainer(self) -> None:
        entry = self.current_entry()
        trainer = self.current_trainer()
        if entry and trainer and trainer.is_file():
            self.settings.setdefault("trainers", {})[entry.prefix.app.app_id] = str(trainer)
            save_settings(self.settings)

    def on_game_selected(self, _listbox: Gtk.ListBox, _row: Gtk.ListBoxRow | None) -> None:
        entry = self.current_entry()
        if not entry:
            self.clear_details()
            return
        game = entry.running
        prefix = entry.prefix
        if self.settings.get("last_app_id") != prefix.app.app_id:
            self.settings["last_app_id"] = prefix.app.app_id
            save_settings(self.settings)

        remembered = self.settings.get("trainers", {}).get(prefix.app.app_id)
        trainer = Path(remembered) if remembered and Path(remembered).is_file() else guess_trainer(prefix.app.name)
        self.trainer_entry.set_text(str(trainer) if trainer else "")

        self.prefix_value.set_text(str(prefix.app.prefix_dir))
        if game is None:
            self.state_value.set_text(tr("Не запущена — запустите игру через Steam"))
            self.proton_value.set_text(str(prefix.proton_path) if prefix.proton_path else tr("Не определён"))
            self.process_view.get_buffer().set_text("")
            self.launch_btn.set_sensitive(False)
        else:
            self.state_value.set_text(tr("Запущена без Proton (нативная Linux-версия)") if game.native_linux
                                      else tr("Запущена через Proton"))
            self.proton_value.set_text(tr("Не используется") if game.native_linux else str(game.proton_path))
            self.process_view.get_buffer().set_text(
                tr("PID: {pid}\nИмя: {name}\nИсточник appid: {source}\nКоманда:\n{command}",
                   pid=game.pid, name=game.process_name, source=game.source, command=game.command)
            )
            self.launch_btn.set_sensitive(not game.native_linux and not self.busy)

        self.update_diagnostics()
        if game and game.native_linux:
            self.show_message(tr(NATIVE_LINUX_HINT), Gtk.MessageType.WARNING)
        elif is_experimental_proton(prefix.proton_path):
            self.show_message(tr(EXPERIMENTAL_PROTON_HINT), Gtk.MessageType.WARNING)
        elif game is not None:
            self.hide_message()

    # ================================================================ diagnostics

    def update_diagnostics(self) -> None:
        for child in self.checks_box.get_children():
            self.checks_box.remove(child)
        entry = self.current_entry()
        if not entry:
            return
        running_native = entry.running.native_linux if entry.running else None
        for check in diagnose(entry.prefix, running_native, self.current_trainer()):
            icon = {True: "emblem-ok-symbolic", False: "dialog-warning-symbolic"}.get(
                check.ok, "dialog-information-symbolic")
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            text = Gtk.Label(xalign=0)
            detail = f"\n<small>{GLib.markup_escape_text(check.detail)}</small>" if check.detail else ""
            text.set_markup(f"<b>{GLib.markup_escape_text(check.title)}</b>{detail}")
            text.set_line_wrap(True)
            text.set_selectable(True)
            row.pack_start(text, True, True, 0)
            self.checks_box.pack_start(row, False, False, 0)
        saves = find_unity_saves(entry.prefix)
        self.save_l2w_btn.set_sensitive(bool(saves) and not self.busy)
        self.save_w2l_btn.set_sensitive(bool(saves) and not self.busy)
        self.dotnet_btn.set_sensitive(prefix_dotnet_status(entry.prefix.pfx) != DOTNET_REAL and not self.busy)
        self.checks_box.show_all()

    def run_task(self, title: str, func: Callable[[], object]) -> None:
        """Run a long operation in a thread; the UI stays responsive."""
        if self.busy:
            self.show_message(tr("Уже выполняется другое действие — дождитесь окончания."), Gtk.MessageType.WARNING)
            return
        self.busy = True
        for button in self.action_buttons:
            button.set_sensitive(False)
        self.launch_btn.set_sensitive(False)
        self.spinner.start()
        self.notebook.set_current_page(1)
        self.log(f"=== {title} ===")
        self.show_message(tr("{title}… Ход выполнения — на вкладке «Диагностика».", title=title), Gtk.MessageType.INFO)

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001
                self.log(tr("✖ Ошибка: {error}", error=exc))
                result = False
            GLib.idle_add(finish, result)

        def finish(result: object) -> bool:
            self.busy = False
            self.spinner.stop()
            for button in self.action_buttons:
                button.set_sensitive(True)
            ok = result is not False
            self.show_message(tr("{title}: {result}.", title=title, result=tr("готово") if ok else tr("не удалось — см. журнал")),
                              Gtk.MessageType.INFO if ok else Gtk.MessageType.ERROR)
            self.refresh_games()
            return False

        threading.Thread(target=worker, daemon=True).start()

    def _closed_entry(self) -> GameEntry | None:
        entry = self.current_entry()
        if not entry:
            self.show_message(tr("Сначала выберите игру."), Gtk.MessageType.ERROR)
            return None
        if entry.running or prefix_in_use(entry.prefix.app.prefix_dir):
            self.show_message(tr("Закройте игру и трейнер — это действие нельзя выполнять, пока префикс используется."),
                              Gtk.MessageType.WARNING)
            return None
        return entry

    def on_install_dotnet(self) -> None:
        entry = self._closed_entry()
        if entry:
            self.run_task(tr("Установка .NET 4.8 для «{name}»", name=entry.prefix.app.name),
                          lambda: install_dotnet48(entry.prefix, self.log))

    def on_backup_prefix(self) -> None:
        entry = self._closed_entry()
        if entry:
            self.run_task(tr("Резервная копия префикса"), lambda: backup_prefix(entry.prefix, self.log))

    def on_restore_prefix(self) -> None:
        entry = self._closed_entry()
        if not entry:
            return
        dialog = Gtk.FileChooserNative(title=tr("Выберите резервную копию префикса"), transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN, accept_label=tr("Восстановить"),
                                       cancel_label=tr("Отмена"))
        archive_filter = Gtk.FileFilter()
        archive_filter.set_name(tr("Архивы префикса (*.tar.gz)"))
        archive_filter.add_pattern("*.tar.gz")
        dialog.add_filter(archive_filter)
        if BACKUP_ROOT.is_dir():
            dialog.set_current_folder(str(BACKUP_ROOT))
        archive = dialog.get_filename() if dialog.run() == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        if archive:
            self.run_task(tr("Восстановление префикса"), lambda: restore_prefix(entry.prefix, Path(archive), self.log))

    def on_copy_saves(self, to_windows: bool) -> None:
        entry = self._closed_entry()
        if not entry:
            return
        saves = find_unity_saves(entry.prefix)
        if not saves:
            self.show_message(tr("Не удалось найти сейвы: перенос работает для Unity-игр."), Gtk.MessageType.WARNING)
            return
        source, target = (saves.linux_dir, saves.windows_dir) if to_windows else (saves.windows_dir, saves.linux_dir)
        label = f"{entry.prefix.app.app_id}-{'l2w' if to_windows else 'w2l'}"
        self.run_task(tr("Перенос сейва Linux → Windows") if to_windows else tr("Перенос сейва Windows → Linux"),
                      lambda: copy_saves(source, target, label, self.log))

    # ================================================================ launch

    def on_pick_trainer(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative(title=tr("Выберите trainer.exe"), transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN, accept_label=tr("Выбрать"),
                                       cancel_label=tr("Отмена"))
        exe_filter = Gtk.FileFilter()
        exe_filter.set_name(tr("Windows-программы (*.exe)"))
        exe_filter.add_pattern("*.exe")
        exe_filter.add_pattern("*.EXE")
        dialog.add_filter(exe_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name(tr("Все файлы"))
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)
        current = self.current_trainer()
        if current and current.parent.is_dir():
            dialog.set_current_folder(str(current.parent))
        if dialog.run() == Gtk.ResponseType.ACCEPT and dialog.get_filename():
            self.trainer_entry.set_text(dialog.get_filename())
            self.update_diagnostics()
        dialog.destroy()

    def on_launch(self, _button: Gtk.Button) -> None:
        entry = self.current_entry()
        game = entry.running if entry else None
        if not entry or not game:
            self.show_message(tr("Сначала запустите игру и выберите её в списке."), Gtk.MessageType.ERROR)
            return
        trainer_path = self.current_trainer()
        if not trainer_path:
            self.show_message(tr("Сначала выберите trainer.exe."), Gtk.MessageType.ERROR)
            return
        if not trainer_path.is_file():
            self.show_message(tr("Не найден файл: {path}", path=trainer_path), Gtk.MessageType.ERROR)
            return

        closed = close_trainer_instances(trainer_path)
        mode = self.mode_combo.get_active_id() or DEFAULT_LAUNCH_MODE
        delay_seconds = int(self.delay_spin.get_value())
        try:
            _process, log_path = launch_trainer(game, trainer_path, mode, delay_seconds, self.steam_root)
        except Exception as exc:  # noqa: BLE001
            self.show_message(tr("Ошибка запуска: {error}", error=exc), Gtk.MessageType.ERROR)
            return
        self._remember_trainer()

        start_text = tr("сразу") if delay_seconds == 0 else tr("через {n} сек", n=delay_seconds)
        text = tr("Трейнер запускается для «{name}» ({mode}, {start}).\nЛог: {log}",
                  name=game.app.name, mode=launch_mode_label(mode), start=start_text, log=log_path)
        if closed:
            text += tr("\nЗакрыто старых копий трейнера: {n}.", n=closed)

        info = read_exe_info(trainer_path)
        if info and info.is_dotnet and prefix_dotnet_status(entry.prefix.pfx) != DOTNET_REAL:
            text += tr("\n\nТрейнер написан на .NET, а в префиксе нет настоящего .NET Framework. "
                       "Если трейнер не увидит игру — закройте игру и установите .NET 4.8.")
            self.show_message(text, Gtk.MessageType.WARNING,
                              action=(tr("Открыть диагностику"), lambda: self.notebook.set_current_page(1)))
        else:
            self.show_message(text, Gtk.MessageType.INFO)
        self.update_diagnostics()


def open_window(app: Gtk.Application) -> ProtonHookWindow:
    window = ProtonHookWindow(app)
    window.show_all()
    window.info_bar.set_revealed(False)
    window.info_action_btn.hide()
    window.present()
    return window


def run() -> int:
    set_language(load_settings().get("language") or detect_language())
    app = Gtk.Application(application_id="io.github.protonhook.ProtonHook")

    def on_activate(application: Gtk.Application) -> None:
        # A second launch just raises the existing window.
        window = application.get_active_window()
        if window is None:
            open_window(application)
        else:
            window.present()

    app.connect("activate", on_activate)
    return app.run(None)
