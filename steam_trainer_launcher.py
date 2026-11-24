#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ModuleNotFoundError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

from protontrek_core import (
    DEFAULT_DELAY_SECONDS,
    DEFAULT_LAUNCH_MODE,
    LAUNCH_MODES,
    RunningGame,
    discover_steam_root,
    find_running_games,
    launch_mode_label,
    launch_trainer,
    log_debug,
    mode_key_from_label,
    parse_delay_seconds,
)


class TrainerLauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ProtonHook")
        self.root.geometry("960x560")
        self.root.minsize(820, 480)

        self.steam_root = discover_steam_root()
        self.games: list[RunningGame] = []
        self.selected_trainer = tk.StringVar()
        self.selected_mode = tk.StringVar(value=DEFAULT_LAUNCH_MODE)
        self.delay_seconds = tk.StringVar(value=DEFAULT_DELAY_SECONDS)
        self.status_text = tk.StringVar(value="Поиск Steam...")

        self._build_ui()
        self.refresh_games()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(
            header,
            text="Запущенные Steam-игры и их Proton-префиксы",
            font=("TkDefaultFont", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Обновить", command=self.refresh_games).grid(row=0, column=2, sticky="e")
        ttk.Label(header, textvariable=self.status_text).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        left = ttk.Frame(body, padding=8)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Игры").grid(row=0, column=0, sticky="w")

        self.game_list = tk.Listbox(left, exportselection=False)
        self.game_list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.game_list.bind("<<ListboxSelect>>", self.on_game_selected)

        body.add(left, weight=1)

        right = ttk.Frame(body, padding=8)
        right.columnconfigure(1, weight=1)

        ttk.Label(right, text="Префикс").grid(row=0, column=0, sticky="nw")
        self.prefix_value = tk.Text(right, height=4, wrap="word")
        self.prefix_value.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.prefix_value.configure(state="disabled")

        ttk.Label(right, text="Proton").grid(row=1, column=0, sticky="nw")
        self.proton_value = tk.Text(right, height=3, wrap="word")
        self.proton_value.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self.proton_value.configure(state="disabled")

        ttk.Label(right, text="Процесс").grid(row=2, column=0, sticky="nw")
        self.process_value = tk.Text(right, height=6, wrap="word")
        self.process_value.grid(row=2, column=1, sticky="ew", pady=(0, 8))
        self.process_value.configure(state="disabled")

        ttk.Label(right, text="Trainer").grid(row=3, column=0, sticky="w")
        trainer_entry = ttk.Entry(right, textvariable=self.selected_trainer)
        trainer_entry.grid(row=3, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(right, text="Режим запуска").grid(row=4, column=0, sticky="w")
        mode_values = [label for label, _desc in LAUNCH_MODES.values()]
        self.mode_combo = ttk.Combobox(
            right,
            state="readonly",
            values=mode_values,
        )
        self.mode_combo.grid(row=4, column=1, sticky="ew", pady=(0, 8))
        self.mode_combo.set(launch_mode_label(DEFAULT_LAUNCH_MODE))

        ttk.Label(right, text="Задержка, сек").grid(row=5, column=0, sticky="w")
        delay_entry = ttk.Entry(right, textvariable=self.delay_seconds)
        delay_entry.grid(row=5, column=1, sticky="ew", pady=(0, 8))

        buttons = ttk.Frame(right)
        buttons.grid(row=6, column=1, sticky="w", pady=(0, 8))
        ttk.Button(buttons, text="Выбрать trainer.exe", command=self.pick_trainer).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Запустить в префиксе", command=self.run_trainer).pack(side=tk.LEFT, padx=(8, 0))

        help_text = (
            "Утилита ищет процессы Steam/Proton через /proc, определяет appid, "
            "compatdata-префикс и даёт выбрать режим запуска и задержку перед стартом trainer.exe."
        )
        ttk.Label(right, text=help_text, wraplength=420, justify=tk.LEFT).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="w",
        )

        body.add(right, weight=2)

    def set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def refresh_games(self) -> None:
        self.game_list.delete(0, tk.END)
        self.games.clear()

        if not self.steam_root:
            self.status_text.set("Steam не найден. Проверьте стандартный путь установки.")
            return

        self.games = find_running_games(self.steam_root)
        for game in self.games:
            label = f"{game.app.name}  [appid {game.app.app_id}]  pid {game.pid}"
            self.game_list.insert(tk.END, label)

        if self.games:
            self.status_text.set(f"Найдено игр: {len(self.games)}")
            self.game_list.selection_set(0)
            self.on_game_selected()
        else:
            self.status_text.set("Активные Steam-игры под Proton не найдены.")
            self.clear_details()

    def clear_details(self) -> None:
        self.set_text(self.prefix_value, "")
        self.set_text(self.proton_value, "")
        self.set_text(self.process_value, "")

    def current_game(self) -> RunningGame | None:
        selection = self.game_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.games):
            return None
        return self.games[index]

    def on_game_selected(self, _event: object | None = None) -> None:
        game = self.current_game()
        if not game:
            self.clear_details()
            return

        self.set_text(self.prefix_value, str(game.app.prefix_dir))
        self.set_text(self.proton_value, str(game.proton_path) if game.proton_path else "Не определён")
        process_text = (
            f"PID: {game.pid}\n"
            f"Имя: {game.process_name}\n"
            f"Источник appid: {game.source}\n"
            f"Команда:\n{game.command}"
        )
        self.set_text(self.process_value, process_text)

    def pick_trainer(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите trainer.exe",
            filetypes=[("Windows executables", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.selected_trainer.set(path)

    def run_trainer(self) -> None:
        game = self.current_game()
        if not game:
            messagebox.showerror("Нет игры", "Сначала выберите игру из списка.")
            return

        trainer_raw = self.selected_trainer.get().strip()
        if not trainer_raw:
            messagebox.showerror("Нет trainer.exe", "Сначала выберите trainer.exe.")
            return

        trainer_path = Path(trainer_raw).expanduser()
        if not trainer_path.exists():
            messagebox.showerror("Файл не найден", f"Не найден файл:\n{trainer_path}")
            return

        mode = mode_key_from_label(self.mode_combo.get())
        if not mode:
            messagebox.showerror("Нет режима", "Выберите корректный режим запуска.")
            return

        try:
            delay_seconds = parse_delay_seconds(self.delay_seconds.get())
        except RuntimeError as exc:
            messagebox.showerror("Некорректная задержка", str(exc))
            return

        try:
            _process, log_path = launch_trainer(game, trainer_path, mode, delay_seconds)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ошибка запуска", str(exc))
            return

        start_text = "сразу" if delay_seconds == 0 else f"через {delay_seconds} сек"
        messagebox.showinfo(
            "Запущено",
            f"Trainer будет запущен для игры:\n{game.app.name}\n"
            f"Режим: {launch_mode_label(mode)}\n"
            f"Старт: {start_text}\n\nЛог:\n{log_path}",
        )


def zenity_available() -> bool:
    return shutil_which("zenity") is not None


def shutil_which(binary: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(":"):
        candidate = Path(directory) / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run_zenity(args: list[str]) -> subprocess.CompletedProcess[str]:
    log_debug("zenity " + " ".join(args))
    result = subprocess.run(
        ["zenity", *args],
        check=False,
        text=True,
        capture_output=True,
    )
    log_debug(
        f"zenity exit={result.returncode} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
    )
    return result


def zenity_info(text: str) -> None:
    run_zenity(["--info", "--width=520", f"--text={text}"])


def zenity_error(text: str) -> None:
    run_zenity(["--error", "--width=560", f"--text={text}"])


def zenity_pick_game(games: list[RunningGame]) -> RunningGame | None:
    cmd = [
        "--list",
        "--title=ProtonHook",
        "--width=1100",
        "--height=500",
        "--text=Выберите запущенную Steam-игру",
        "--separator=|",
        "--print-column=1",
        "--column=appid",
        "--column=Игра",
        "--column=PID",
        "--column=Префикс",
        "--column=Proton",
    ]
    for game in games:
        cmd.extend(
            [
                game.app.app_id,
                game.app.name,
                str(game.pid),
                str(game.app.prefix_dir),
                str(game.proton_path) if game.proton_path else "Не определён",
            ]
        )

    result = run_zenity(cmd)
    if result.returncode != 0:
        return None

    app_id = result.stdout.strip()
    if not app_id:
        return None

    for game in games:
        if game.app.app_id == app_id:
            return game
    return None


def zenity_pick_trainer() -> Path | None:
    result = run_zenity(
        [
            "--file-selection",
            "--title=Выберите trainer.exe",
            "--filename=" + str(Path.home()) + "/",
        ]
    )
    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    if not value:
        return None
    return Path(value).expanduser()


def zenity_pick_launch_options() -> tuple[str, int] | None:
    mode_rows: list[str] = []
    for key, (label, description) in LAUNCH_MODES.items():
        mode_rows.extend([key, label, description])

    mode_result = run_zenity(
        [
            "--list",
            "--radiolist",
            "--title=Режим запуска",
            "--width=900",
            "--height=320",
            "--text=Выберите режим запуска trainer.exe",
            "--column=Выбор",
            "--column=Ключ",
            "--column=Режим",
            "--column=Описание",
            "TRUE",
            DEFAULT_LAUNCH_MODE,
            launch_mode_label(DEFAULT_LAUNCH_MODE),
            LAUNCH_MODES[DEFAULT_LAUNCH_MODE][1],
            "FALSE",
            "runinprefix_direct",
            launch_mode_label("runinprefix_direct"),
            LAUNCH_MODES["runinprefix_direct"][1],
            "FALSE",
            "run",
            launch_mode_label("run"),
            LAUNCH_MODES["run"][1],
        ]
    )
    if mode_result.returncode != 0:
        return None

    mode = mode_result.stdout.strip()
    if mode not in LAUNCH_MODES:
        return None

    delay_result = run_zenity(
        [
            "--entry",
            "--title=Задержка запуска",
            "--width=420",
            "--text=Введите задержку перед стартом trainer.exe в секундах (0-600)",
            f"--entry-text={DEFAULT_DELAY_SECONDS}",
        ]
    )
    if delay_result.returncode != 0:
        return None

    try:
        delay_seconds = parse_delay_seconds(delay_result.stdout.strip())
    except RuntimeError as exc:
        zenity_error(str(exc))
        return None

    return mode, delay_seconds


def zenity_confirm_launch(game: RunningGame, trainer_path: Path, mode: str, delay_seconds: int) -> bool:
    proton_text = str(game.proton_path) if game.proton_path else "Не определён"
    start_text = "сразу" if delay_seconds == 0 else f"через {delay_seconds} сек"
    text = (
        f"Игра: {game.app.name}\n"
        f"AppID: {game.app.app_id}\n"
        f"PID: {game.pid}\n"
        f"Префикс: {game.app.prefix_dir}\n"
        f"Proton: {proton_text}\n"
        f"Режим: {launch_mode_label(mode)}\n"
        f"Старт: {start_text}\n"
        f"Trainer: {trainer_path}\n\n"
        "Запустить?"
    )
    result = run_zenity(["--question", "--width=700", f"--text={text}"])
    return result.returncode == 0


def run_zenity_flow() -> int:
    log_debug("starting zenity flow")
    steam_root = discover_steam_root()
    if not steam_root:
        zenity_error("Steam не найден. Проверьте стандартный путь установки.")
        return 1

    games = find_running_games(steam_root)
    log_debug(f"games found={len(games)}")
    if not games:
        zenity_error("Активные Steam-игры под Proton не найдены.")
        return 1

    game = zenity_pick_game(games)
    if not game:
        zenity_info("Игра не выбрана. Запуск отменён.")
        return 1

    zenity_info(
        "Игра выбрана.\n\n"
        "Следующим окном откроется выбор trainer.exe.\n"
        "Если окно не появилось, проверь терминал и /tmp/protontrek.log."
    )
    trainer_path = zenity_pick_trainer()
    if not trainer_path:
        zenity_info("Файл trainer.exe не выбран. Запуск отменён.")
        return 1

    if not trainer_path.exists():
        zenity_error(f"Не найден файл:\n{trainer_path}")
        return 1

    launch_options = zenity_pick_launch_options()
    if not launch_options:
        zenity_info("Параметры запуска не выбраны. Запуск отменён.")
        return 1

    mode, delay_seconds = launch_options

    if not zenity_confirm_launch(game, trainer_path, mode, delay_seconds):
        return 1

    try:
        _process, log_path = launch_trainer(game, trainer_path, mode, delay_seconds)
    except Exception as exc:  # noqa: BLE001
        zenity_error(str(exc))
        return 1

    start_text = "сразу" if delay_seconds == 0 else f"через {delay_seconds} сек"
    zenity_info(
        f"Trainer будет запущен для игры:\n{game.app.name}\n"
        f"Режим: {launch_mode_label(mode)}\n"
        f"Старт: {start_text}\n\nЛог:\n{log_path}"
    )
    return 0


def main() -> int:
    if sys.platform != "linux":
        print("Эта утилита рассчитана на Linux с Steam/Proton.", file=sys.stderr)
        return 1

    try:
        import gtk_ui
    except (ImportError, ValueError) as exc:
        log_debug(f"GTK UI unavailable: {exc!r}")
    else:
        return gtk_ui.run()

    if tk is not None:
        root = tk.Tk()
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        TrainerLauncherApp(root)
        root.mainloop()
        return 0

    if zenity_available():
        return run_zenity_flow()

    print(
        "Не найден tkinter, и в системе нет zenity для графического интерфейса.",
        file=sys.stderr,
    )
    print("Установите python3-tk или zenity.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
