#!/usr/bin/env python3
"""Shared, GUI-independent logic for ProtonHook.

Used by both the standalone `steam_trainer_launcher.py` script (tkinter/zenity)
and the Decky Loader plugin backend (`main.py`).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from i18n import tr

LOG_PATH = Path("/tmp/protontrek.log")
__version__ = "0.0.0-dev"  # replaced by the release workflow


def restore_host_environment() -> None:
    """Undo library paths injected by a PyInstaller bundle.

    The frozen binary points LD_LIBRARY_PATH at its own bundled libraries;
    Proton, Wine, flatpak and protontricks started from it must not inherit
    that. The dynamic loader already read the value at startup, so changing
    os.environ here only affects child processes.
    """
    if not getattr(sys, "frozen", False):
        return
    for name in ("LD_LIBRARY_PATH",):
        original = os.environ.pop(name + "_ORIG", None)
        if original is not None:
            os.environ[name] = original
        else:
            os.environ.pop(name, None)

LAUNCH_MODES: dict[str, tuple[str, str]] = {
    "runinprefix_start": (
        "Proton runinprefix start /unix",
        "Мягкий запуск внутри префикса через start /unix",
    ),
    "runinprefix_direct": (
        "Proton runinprefix",
        "Прямой запуск через wine внутри того же префикса",
    ),
    "run": (
        "Proton run",
        "Обычный запуск через Proton run",
    ),
}

DEFAULT_LAUNCH_MODE = "runinprefix_start"
DEFAULT_DELAY_SECONDS = "0"


@dataclass
class SteamApp:
    app_id: str
    name: str
    install_dir: Path | None
    library_root: Path
    prefix_dir: Path


@dataclass
class RunningGame:
    app: SteamApp
    pid: int
    process_name: str
    command: str
    proton_path: Path | None
    source: str
    environ: dict[str, str]
    cwd: Path | None
    # True when the game runs without Proton (native Linux build in Steam
    # Linux Runtime). A Windows trainer cannot attach to such a process.
    native_linux: bool = False


NATIVE_LINUX_HINT = (
    "Игра запущена как нативная Linux-версия, без Proton. "
    "Windows-трейнер не сможет к ней подключиться.\n"
    "Включите Proton: Steam → Свойства игры → Совместимость → "
    "«Принудительно использовать инструмент совместимости» (лучше стабильный Proton, "
    "не Experimental), перезапустите игру и нажмите «Обновить»."
)

EXPERIMENTAL_PROTON_HINT = (
    "Игра запущена в Proton Experimental. В нём трейнеры часто не находят процесс игры "
    "или не показывают окно. Если трейнер пишет, что игра не найдена: Steam → Свойства "
    "игры → Совместимость → выберите стабильный Proton (например, Proton 9.0 или GE-Proton), "
    "перезапустите игру и нажмите «Обновить»."
)


def is_experimental_proton(path: Path | None) -> bool:
    return bool(path) and "experimental" in path.name.lower()


SOURCE_PRIORITY = {
    "env": 0,
    "cmdline": 1,
    "path": 2,
}


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def log_debug(message: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def unquote_vdf(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_simple_vdf(path: Path) -> dict[str, str]:
    text = read_text_safe(path)
    pairs: dict[str, str] = {}
    for key, value in re.findall(r'"([^"]+)"\s*"([^"]*)"', text):
        pairs[key] = value
    return pairs


def steam_root_candidates(home: Path) -> list[Path]:
    return [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]


def discover_steam_root(home: Path | None = None) -> Path | None:
    base = home or Path.home()
    for candidate in steam_root_candidates(base):
        if (candidate / "steamapps").exists():
            return candidate
    return None


def parse_libraryfolders(path: Path) -> list[Path]:
    libraries: list[Path] = []
    text = read_text_safe(path)
    if not text:
        return libraries

    for entry in re.finditer(r'"path"\s*"([^"]+)"', text):
        raw = entry.group(1).replace("\\\\", "\\")
        library_path = Path(raw).expanduser()
        if library_path.exists():
            libraries.append(library_path)

    return libraries


def discover_libraries(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    extra = parse_libraryfolders(steam_root / "steamapps" / "libraryfolders.vdf")
    for item in extra:
        if item not in libraries:
            libraries.append(item)
    return libraries


def load_installed_apps(steam_root: Path) -> dict[str, SteamApp]:
    apps: dict[str, SteamApp] = {}
    for library_root in discover_libraries(steam_root):
        steamapps_dir = library_root / "steamapps"
        common_dir = steamapps_dir / "common"
        compat_dir = steamapps_dir / "compatdata"
        if not steamapps_dir.exists():
            continue

        for manifest in steamapps_dir.glob("appmanifest_*.acf"):
            data = parse_simple_vdf(manifest)
            app_id = data.get("appid")
            name = data.get("name")
            installdir = data.get("installdir")
            if not app_id or not name:
                continue

            install_dir = common_dir / installdir if installdir else None
            prefix_dir = compat_dir / app_id
            apps[app_id] = SteamApp(
                app_id=app_id,
                name=name,
                install_dir=install_dir,
                library_root=library_root,
                prefix_dir=prefix_dir,
            )
    return apps


def read_proc_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def parse_null_delimited(raw: bytes) -> list[str]:
    parts = raw.split(b"\0")
    return [part.decode("utf-8", errors="ignore") for part in parts if part]


def parse_proc_environ(pid: int) -> dict[str, str]:
    environ_path = Path("/proc") / str(pid) / "environ"
    values: dict[str, str] = {}
    for item in parse_null_delimited(read_proc_bytes(environ_path)):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        values[key] = value
    return values


def parse_proc_cmdline(pid: int) -> list[str]:
    return parse_null_delimited(read_proc_bytes(Path("/proc") / str(pid) / "cmdline"))


def read_proc_name(pid: int) -> str:
    name = read_text_safe(Path("/proc") / str(pid) / "comm").strip()
    return name or f"pid {pid}"


def path_from_env(environ: dict[str, str], key: str) -> Path | None:
    value = environ.get(key)
    if not value:
        return None
    return Path(value).expanduser()


def app_id_from_text(items: Iterable[str]) -> str | None:
    for item in items:
        match = re.search(r"compatdata/(\d+)", item)
        if match:
            return match.group(1)
        match = re.search(r"\bSteamAppId=(\d+)\b", item)
        if match:
            return match.group(1)
    return None


def detect_app_id(
    pid: int,
    environ: dict[str, str],
    cmdline: list[str],
    installed_apps: dict[str, SteamApp],
) -> str | None:
    for key in ("SteamAppId", "STEAM_COMPAT_APP_ID", "STEAM_GAME_ID"):
        value = environ.get(key)
        if value and value.isdigit():
            return value

    from_path = path_from_env(environ, "STEAM_COMPAT_DATA_PATH")
    if from_path:
        match = re.search(r"/compatdata/(\d+)$", str(from_path))
        if match:
            return match.group(1)

    inferred = app_id_from_text(cmdline)
    if inferred:
        return inferred

    exe_path = Path("/proc") / str(pid) / "exe"
    cwd_path = Path("/proc") / str(pid) / "cwd"
    probe_paths = [readlink_safe(exe_path), readlink_safe(cwd_path)]
    for probe in probe_paths:
        if not probe:
            continue
        match = match_install_dir(probe, installed_apps)
        if match:
            return match.app_id
    return None


def readlink_safe(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def match_install_dir(path: Path, installed_apps: dict[str, SteamApp]) -> SteamApp | None:
    best: SteamApp | None = None
    best_len = -1
    for app in installed_apps.values():
        if not app.install_dir:
            continue
        try:
            path.relative_to(app.install_dir)
        except ValueError:
            continue
        current_len = len(str(app.install_dir))
        if current_len > best_len:
            best = app
            best_len = current_len
    return best


def is_proton_dir(path: Path | None) -> bool:
    """A real Proton install has an executable `proton` script inside.

    Steam also lists Steam Linux Runtime containers (SteamLinuxRuntime,
    SteamLinuxRuntime_soldier/sniper) in STEAM_COMPAT_TOOL_PATHS; those are
    not Proton and must be skipped.
    """
    return bool(path) and (path / "proton").is_file()


def read_parent_pid(pid: int) -> int | None:
    stat = read_text_safe(Path("/proc") / str(pid) / "stat")
    # Format: "pid (comm) state ppid ..." — comm may contain spaces/parens.
    _head, sep, tail = stat.rpartition(")")
    if not sep:
        return None
    fields = tail.split()
    if len(fields) < 2 or not fields[1].isdigit():
        return None
    return int(fields[1])


def proton_from_ancestors(pid: int, max_depth: int = 12) -> Path | None:
    """Find `<Proton dir>/proton` in the command line of the process or its parents."""
    current: int | None = pid
    for _ in range(max_depth):
        if not current or current <= 1:
            break
        for part in parse_proc_cmdline(current):
            if part.endswith("/proton"):
                candidate = Path(part).parent
                if is_proton_dir(candidate):
                    return candidate
        current = read_parent_pid(current)
    return None


def detect_game_proton(pid: int, environ: dict[str, str]) -> Path | None:
    """Proton actually used by the running game, or None if it runs natively."""
    explicit = path_from_env(environ, "STEAM_COMPAT_TOOL_PATH")
    if is_proton_dir(explicit):
        return explicit

    for part in environ.get("STEAM_COMPAT_TOOL_PATHS", "").split(":"):
        if part and is_proton_dir(Path(part).expanduser()):
            return Path(part).expanduser()

    return proton_from_ancestors(pid)


def proton_sort_key(path: Path) -> tuple[int, str]:
    # Stable Proton first: Experimental breaks WPF-based trainers.
    name = path.name.lower()
    penalty = 1 if "experimental" in name else 0
    return (penalty, name)


def fallback_proton(steam_root: Path) -> Path | None:
    candidates: list[Path] = []
    for library in discover_libraries(steam_root):
        common_dir = library / "steamapps" / "common"
        if common_dir.exists():
            candidates.extend(p for p in common_dir.glob("Proton*") if is_proton_dir(p))
    compat_tools_dir = steam_root / "compatibilitytools.d"
    if compat_tools_dir.exists():
        candidates.extend(p for p in compat_tools_dir.iterdir() if is_proton_dir(p))
    if not candidates:
        return None
    return sorted(candidates, key=proton_sort_key)[0]


def detect_proton_path(environ: dict[str, str], steam_root: Path, pid: int | None = None) -> Path | None:
    if pid is not None:
        found = detect_game_proton(pid, environ)
    else:
        found = detect_game_proton(0, environ)
    return found or fallback_proton(steam_root)


def find_running_games(steam_root: Path) -> list[RunningGame]:
    installed_apps = load_installed_apps(steam_root)
    running_by_app: dict[str, RunningGame] = {}

    for proc_entry in Path("/proc").iterdir():
        if not proc_entry.name.isdigit():
            continue
        pid = int(proc_entry.name)
        cmdline = parse_proc_cmdline(pid)
        if not cmdline:
            continue

        environ = parse_proc_environ(pid)
        app_id = detect_app_id(pid, environ, cmdline, installed_apps)
        if not app_id:
            continue

        app = installed_apps.get(app_id)
        if not app:
            continue

        has_proton_markers = (
            "STEAM_COMPAT_DATA_PATH" in environ
            or any("proton" in part.lower() for part in cmdline)
            or app.prefix_dir.exists()
        )
        if not has_proton_markers:
            continue

        game_proton = detect_game_proton(pid, environ)
        game = RunningGame(
            app=app,
            pid=pid,
            process_name=read_proc_name(pid),
            command=" ".join(shlex.quote(part) for part in cmdline),
            proton_path=game_proton or fallback_proton(steam_root),
            source=detect_source(environ, cmdline),
            environ=environ,
            cwd=readlink_safe(Path("/proc") / str(pid) / "cwd"),
            native_linux=game_proton is None,
        )
        current = running_by_app.get(app_id)
        if current is None or is_better_game_candidate(game, current):
            running_by_app[app_id] = game

    return sorted(running_by_app.values(), key=lambda item: (item.app.name.lower(), item.pid))


def is_better_game_candidate(candidate: RunningGame, current: RunningGame) -> bool:
    candidate_priority = SOURCE_PRIORITY.get(candidate.source, 99)
    current_priority = SOURCE_PRIORITY.get(current.source, 99)
    if candidate_priority != current_priority:
        return candidate_priority < current_priority

    candidate_name = candidate.process_name.lower()
    current_name = current.process_name.lower()
    candidate_game_name = candidate.app.name.lower()
    current_game_name = current.app.name.lower()

    candidate_matches = candidate_game_name in candidate_name
    current_matches = current_game_name in current_name
    if candidate_matches != current_matches:
        return candidate_matches

    candidate_is_wine = candidate_name.startswith(("wine", "wineserver", "steam"))
    current_is_wine = current_name.startswith(("wine", "wineserver", "steam"))
    if candidate_is_wine != current_is_wine:
        return not candidate_is_wine

    return candidate.pid < current.pid


def detect_source(environ: dict[str, str], cmdline: list[str]) -> str:
    if "SteamAppId" in environ or "STEAM_COMPAT_APP_ID" in environ:
        return "env"
    if any("compatdata" in part for part in cmdline):
        return "cmdline"
    return "path"


def trainer_default_cwd(game: RunningGame) -> Path:
    return game.cwd or game.app.install_dir or game.app.prefix_dir


def sanitize_game_environment(game: RunningGame) -> dict[str, str]:
    env = game.environ.copy()
    env.setdefault("PATH", os.environ.get("PATH", ""))
    env.setdefault("HOME", os.environ.get("HOME", str(Path.home())))
    env.setdefault("USER", os.environ.get("USER", ""))
    env.setdefault("DISPLAY", os.environ.get("DISPLAY", ""))
    env.setdefault("XAUTHORITY", os.environ.get("XAUTHORITY", ""))
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""))
    env.setdefault("WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", ""))
    env.setdefault("XDG_RUNTIME_DIR", os.environ.get("XDG_RUNTIME_DIR", ""))
    env.setdefault("PWD", str(trainer_default_cwd(game)))
    return env


def build_launch_env(game: RunningGame, trainer_path: Path, steam_root: Path | None = None) -> dict[str, str]:
    env = sanitize_game_environment(game)
    resolved_steam_root = steam_root or discover_steam_root() or game.app.library_root
    env["STEAM_COMPAT_DATA_PATH"] = str(game.app.prefix_dir)
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(resolved_steam_root)
    env["STEAM_COMPAT_APP_ID"] = game.app.app_id
    env["SteamAppId"] = game.app.app_id
    env["SteamGameId"] = game.app.app_id
    env["WINEPREFIX"] = str(game.app.prefix_dir / "pfx")
    env["PWD"] = str(trainer_path.parent)
    return env


def trainer_log_path(game: RunningGame) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", game.app.name).strip("_") or game.app.app_id
    return Path("/tmp") / f"protontrek-{safe_name}-{game.app.app_id}.log"


def parse_delay_seconds(value: str) -> int:
    raw = value.strip() or DEFAULT_DELAY_SECONDS
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise RuntimeError("Задержка должна быть целым числом секунд.") from exc
    if seconds < 0 or seconds > 600:
        raise RuntimeError("Задержка должна быть в диапазоне от 0 до 600 секунд.")
    return seconds


def launch_mode_label(mode: str) -> str:
    return LAUNCH_MODES.get(mode, (mode, ""))[0]


def mode_key_from_label(label: str) -> str | None:
    for key, (mode_label, _description) in LAUNCH_MODES.items():
        if mode_label == label:
            return key
    return None


def launch_modes_list() -> list[dict[str, str]]:
    return [
        {"key": key, "label": label, "description": description}
        for key, (label, description) in LAUNCH_MODES.items()
    ]


def game_to_dict(game: RunningGame) -> dict:
    return {
        "app_id": game.app.app_id,
        "name": game.app.name,
        "pid": game.pid,
        "process_name": game.process_name,
        "command": game.command,
        "source": game.source,
        "prefix": str(game.app.prefix_dir),
        "proton_path": str(game.proton_path) if game.proton_path else None,
        "install_dir": str(game.app.install_dir) if game.app.install_dir else None,
        "native_linux": game.native_linux,
    }


def build_launch_command(proton_script: Path, trainer_path: Path, mode: str) -> list[str]:
    if mode == "runinprefix_start":
        return [
            str(proton_script),
            "runinprefix",
            "start",
            "/unix",
            str(trainer_path),
        ]
    if mode == "runinprefix_direct":
        return [
            str(proton_script),
            "runinprefix",
            str(trainer_path),
        ]
    if mode == "run":
        return [
            str(proton_script),
            "run",
            str(trainer_path),
        ]
    raise RuntimeError(tr("Неизвестный режим запуска: {mode}", mode=mode))


def spawn_launch_process(
    launch_cmd: list[str],
    env: dict[str, str],
    cwd: Path,
    log_path: Path,
    delay_seconds: int,
) -> subprocess.Popen[bytes]:
    log_handle = log_path.open("ab")
    try:
        if delay_seconds <= 0:
            process = subprocess.Popen(
                launch_cmd,
                env=env,
                cwd=str(cwd),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        else:
            # Plain sh keeps this working inside a frozen (PyInstaller) build,
            # where sys.executable is ProtonHook itself, not a Python interpreter.
            delay_cmd = ["sh", "-c", 'sleep "$1"; shift; exec "$@"', "protonhook-delay",
                         str(delay_seconds), *launch_cmd]
            process = subprocess.Popen(
                delay_cmd,
                env=env,
                cwd=str(cwd),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    finally:
        log_handle.close()
    return process


def launch_trainer(
    game: RunningGame,
    trainer_path: Path,
    mode: str,
    delay_seconds: int,
    steam_root: Path | None = None,
) -> tuple[subprocess.Popen[bytes], Path]:
    if game.native_linux:
        raise RuntimeError(tr(NATIVE_LINUX_HINT))

    proton_dir = game.proton_path
    if not proton_dir:
        raise RuntimeError(tr("Не удалось определить путь к Proton для этой игры."))

    proton_script = proton_dir / "proton"
    if not proton_script.exists():
        raise RuntimeError(tr("Файл Proton не найден: {path}", path=proton_script))

    env = build_launch_env(game, trainer_path, steam_root)
    log_path = trainer_log_path(game)
    launch_cmd = build_launch_command(proton_script, trainer_path, mode)
    log_debug(f"launch trainer pid_target={game.pid} cmd={launch_cmd!r}")
    log_debug(
        f"launch env appid={game.app.app_id} proton={proton_dir} prefix={game.app.prefix_dir} "
        f"mode={mode} delay={delay_seconds}"
    )

    with log_path.open("ab") as log_handle:
        log_handle.write(
            (
                f"\n=== ProtonHook launch ===\n"
                f"ts={int(time.time())}\n"
                f"game={game.app.name}\n"
                f"appid={game.app.app_id}\n"
                f"game_pid={game.pid}\n"
                f"trainer={trainer_path}\n"
                f"proton={proton_dir}\n"
                f"prefix={game.app.prefix_dir}\n"
                f"cwd={trainer_path.parent}\n"
                f"mode={mode}\n"
                f"delay_seconds={delay_seconds}\n"
            ).encode("utf-8", errors="ignore")
        )
    process = spawn_launch_process(launch_cmd, env, trainer_path.parent, log_path, delay_seconds)
    return process, log_path
