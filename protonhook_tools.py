#!/usr/bin/env python3
"""Troubleshooting helpers for ProtonHook (GUI-independent).

Everything here is something the user would otherwise have to do by hand:
diagnose a game's Proton prefix, back it up, install .NET Framework 4.8 via
protontricks (with workarounds for known failures), move Unity saves between
the native Linux and Windows builds, and close stale trainer instances.
"""
from __future__ import annotations

import os
import shutil
import signal
import struct
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from protontrek_core import (
    SteamApp,
    is_experimental_proton,
    is_proton_dir,
    load_installed_apps,
    log_debug,
    parse_null_delimited,
    read_proc_bytes,
    read_text_safe,
)
from i18n import get_language, tr

Log = Callable[[str], None]

BACKUP_ROOT = Path.home() / "ProtonHook-backups"
PROTONTRICKS_FLATPAK = "com.github.Matoking.protontricks"

# Files Unity writes next to saves that must not be copied between builds.
SAVE_SKIP_NAMES = {"Player.log", "Player-prev.log", "steam_autocloud.vdf", "prefs"}


# ---------------------------------------------------------------- prefixes


@dataclass
class PrefixGame:
    """An installed Steam game that has a Proton prefix (running or not)."""

    app: SteamApp
    proton_path: Path | None

    @property
    def pfx(self) -> Path:
        return self.app.prefix_dir / "pfx"


def proton_from_config_info(prefix_dir: Path) -> Path | None:
    """Proton writes the paths of the Proton build it used into config_info."""
    for line in read_text_safe(prefix_dir / "config_info").splitlines():
        if "/files/" in line:
            candidate = Path(line.split("/files/", 1)[0])
            if is_proton_dir(candidate):
                return candidate
    return None


def installed_prefix_games(steam_root: Path) -> list[PrefixGame]:
    games = []
    for app in load_installed_apps(steam_root).values():
        # Proton and Steam Runtime themselves show up as apps with a prefix.
        if app.name.startswith(("Proton", "Steam Linux Runtime", "Steamworks Common")):
            continue
        if (app.prefix_dir / "pfx").is_dir():
            games.append(PrefixGame(app=app, proton_path=proton_from_config_info(app.prefix_dir)))
    return sorted(games, key=lambda g: g.app.name.lower())


def prefix_in_use(prefix_dir: Path) -> bool:
    """True if any process (game, trainer, wineserver) still uses the prefix."""
    target = str(prefix_dir).rstrip("/")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        raw = read_proc_bytes(entry / "environ")
        if not raw:
            continue
        for item in parse_null_delimited(raw):
            if item.startswith(("STEAM_COMPAT_DATA_PATH=", "WINEPREFIX=")):
                value = item.split("=", 1)[1].rstrip("/")
                if value == target or value == target + "/pfx":
                    return True
    return False


# ---------------------------------------------------------------- .NET


DOTNET_REAL = "dotnet"
DOTNET_MONO = "mono"
DOTNET_NONE = "none"


def prefix_dotnet_status(pfx: Path) -> str:
    """Which .NET runtime a 64-bit .NET program will get in this prefix."""
    framework = pfx / "drive_c/windows/Microsoft.NET"
    if (framework / "Framework64/v4.0.30319/clr.dll").is_file() or (
        framework / "Framework/v4.0.30319/clr.dll"
    ).is_file():
        return DOTNET_REAL
    # winetricks removes wine-mono before installing .NET; if that install
    # then failed, the prefix is left with no .NET runtime at all.
    if "remove_mono" in read_text_safe(pfx / "winetricks.log"):
        return DOTNET_NONE
    return DOTNET_MONO


DOTNET_STATUS_TEXT = {
    DOTNET_REAL: "установлен настоящий .NET Framework 4.x",
    DOTNET_MONO: "только wine-mono (замена .NET, совместима не со всеми трейнерами)",
    DOTNET_NONE: "нет .NET: wine-mono удалён, а .NET не установился",
}


@dataclass
class ExeInfo:
    is_64bit: bool
    is_dotnet: bool


CLR_HOSTING_MARKERS = (b"CLRCreateInstance", b"CorBindToRuntime")


def read_exe_info(path: Path) -> ExeInfo | None:
    """Parse the PE header: bitness and whether the program needs .NET.

    Covers both plain .NET assemblies and native loaders that host the CLR
    themselves (e.g. FLiNG trainers unpack a .NET payload and start it via
    CLRCreateInstance from mscoree.dll).
    """
    try:
        with path.open("rb") as handle:
            whole = handle.read(64 * 1024 * 1024)
    except OSError:
        return None
    data = whole[:4096]
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 24 > len(data) or data[pe : pe + 4] != b"PE\0\0":
        return None
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    is_64 = magic == 0x20B
    # Data directory 14 = CLR runtime header (present only in .NET assemblies).
    dirs_offset = optional + (112 if is_64 else 96)
    clr_entry = dirs_offset + 14 * 8
    is_dotnet = False
    if clr_entry + 8 <= len(data):
        rva, size = struct.unpack_from("<II", data, clr_entry)
        is_dotnet = rva != 0 and size != 0
    if not is_dotnet:
        is_dotnet = any(marker in whole for marker in CLR_HOSTING_MARKERS)
    return ExeInfo(is_64bit=is_64, is_dotnet=is_dotnet)


# ---------------------------------------------------------------- trainers


def find_trainer_pids(trainer_path: Path) -> list[int]:
    """Running Wine processes of this trainer (matched by exe file name)."""
    name = trainer_path.name.lower()
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        cmdline = parse_null_delimited(read_proc_bytes(entry / "cmdline"))
        if not cmdline:
            continue
        first = cmdline[0].replace("\\", "/").lower()
        if first.endswith("/" + name) or first == name:
            pids.append(int(entry.name))
    return pids


def close_trainer_instances(trainer_path: Path) -> int:
    pids = find_trainer_pids(trainer_path)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    if pids:
        time.sleep(1.5)
        for pid in pids:
            if Path(f"/proc/{pid}").exists():
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    return len(pids)


# ---------------------------------------------------------------- backups


def backup_prefix(game: PrefixGame, log: Log) -> Path:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = BACKUP_ROOT / f"prefix-{game.app.app_id}-{stamp}.tar.gz"
    log(tr("Резервная копия префикса → {path}", path=target))
    with tarfile.open(target, "w:gz") as tar:
        tar.add(game.app.prefix_dir, arcname=game.app.app_id)
    log(tr("Готово, {mb} МБ", mb=target.stat().st_size // (1024 * 1024)))
    return target


# ---------------------------------------------------------------- protontricks


def protontricks_base() -> tuple[list[str], bool] | None:
    """Command prefix for protontricks and whether it is the Flatpak build."""
    flatpak = shutil.which("flatpak")
    if flatpak:
        result = subprocess.run(
            [flatpak, "info", PROTONTRICKS_FLATPAK], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return [flatpak, "run", PROTONTRICKS_FLATPAK], True
    native = shutil.which("protontricks")
    if native:
        return [native], False
    return None


def ensure_flatpak_access(paths: list[Path], log: Log) -> None:
    """The protontricks Flatpak only sees ~/.local/share/Steam by default;
    Steam libraries on other drives must be granted explicitly."""
    home = Path.home()
    needed = []
    for path in paths:
        try:
            path.relative_to(home)
            continue
        except ValueError:
            pass
        needed.append(path)
    if not needed:
        return
    current = subprocess.run(
        ["flatpak", "override", "--user", "--show", PROTONTRICKS_FLATPAK],
        capture_output=True, text=True, check=False,
    ).stdout
    for path in needed:
        if str(path) in current:
            continue
        log(tr("Выдаю protontricks доступ к {path}", path=path))
        subprocess.run(
            ["flatpak", "override", "--user", f"--filesystem={path}", PROTONTRICKS_FLATPAK],
            check=False,
        )


def run_streaming(cmd: list[str], env: dict[str, str], log: Log) -> int:
    log("$ " + " ".join(cmd))
    process = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        # Wine debug spam is not useful to the user.
        if not line or "ld.so" in line or ":fixme:" in line or ":warn:" in line:
            continue
        log(line)
    return process.wait()


def install_dotnet48(game: PrefixGame, log: Log) -> bool:
    """Install .NET Framework 4.8 into the game's prefix, as automatically as possible."""
    if prefix_in_use(game.app.prefix_dir):
        log(tr("Префикс занят: закройте игру и трейнер, затем повторите."))
        return False
    if not game.proton_path:
        log(tr("Не удалось определить Proton этой игры. Запустите игру через Steam хотя бы раз."))
        return False
    base = protontricks_base()
    if not base:
        log(tr("protontricks не найден. Установите его: {cmd}", cmd="flatpak install flathub " + PROTONTRICKS_FLATPAK))
        return False
    cmd_base, is_flatpak = base

    backup = backup_prefix(game, log)
    if is_flatpak:
        ensure_flatpak_access([game.app.library_root, game.proton_path.parent], log)

    if _install_dotnet48_steps(game, cmd_base, is_flatpak, log):
        return True
    # A failed install leaves the prefix without wine-mono and without .NET,
    # which is worse than before. Roll back automatically.
    log(tr("Откатываю префикс к состоянию до установки…"))
    restore_prefix(game, backup, log, make_backup=False)
    log(tr("Префикс возвращён как был (с wine-mono). .NET 4.8 в этом Proton установить не удалось — см. «Справка»."))
    return False


def _install_dotnet48_steps(game: PrefixGame, cmd_base: list[str], is_flatpak: bool, log: Log) -> bool:
    assert game.proton_path is not None

    env = os.environ.copy()
    # Skips protontricks' own Proton detection, which crashes on newer Steam
    # appinfo.vdf formats; the Proton name is the folder Steam installed it in.
    env["PROTON_VERSION"] = game.proton_path.name
    app_id = game.app.app_id

    log(tr("Шаг 1/2: protontricks dotnet48 (может занять 10–20 минут)…"))
    rc = run_streaming([*cmd_base, app_id, "-q", "dotnet48"], env, log)
    if rc == 0 and prefix_dotnet_status(game.pfx) == DOTNET_REAL:
        log(tr("✔ .NET Framework 4.8 установлен."))
        return True

    # Known failure: the dotnet40 prerequisite installer exits with code 67.
    # Retry with the .NET 4.8 installer alone on a win7 prefix (on some
    # Proton builds this fails too, with MSI error 1603).
    log(tr("Стандартная установка не удалась — пробую установить .NET 4.8 напрямую."))
    installer = find_cached_ndp48(is_flatpak)
    if not installer:
        log(tr("Установщик .NET 4.8 не найден в кэше winetricks."))
        return False
    rc = run_streaming([*cmd_base, app_id, "-q", "win7"], env, log)
    log(tr("Шаг 2/2: запуск установщика .NET 4.8…"))
    rc = run_streaming(
        [*cmd_base, "-c", f'wine "{installer}" /q /norestart', app_id], env, log
    )
    if prefix_dotnet_status(game.pfx) == DOTNET_REAL:
        log(tr("✔ .NET Framework 4.8 установлен."))
        return True
    log(tr("✖ Установщик .NET 4.8 завершился с кодом {rc}.", rc=rc))
    return False


def find_cached_ndp48(is_flatpak: bool) -> Path | None:
    caches = [Path.home() / ".cache/winetricks/dotnet48"]
    if is_flatpak:
        caches.insert(0, Path.home() / f".var/app/{PROTONTRICKS_FLATPAK}/cache/winetricks/dotnet48")
    for cache in caches:
        candidate = cache / "ndp48-x86-x64-allos-enu.exe"
        if candidate.is_file():
            return candidate
    return None


def restore_prefix(game: PrefixGame, archive: Path, log: Log, make_backup: bool = True) -> bool:
    if prefix_in_use(game.app.prefix_dir):
        log(tr("Префикс занят: закройте игру и трейнер, затем повторите."))
        return False
    prefix = game.app.prefix_dir
    staging = prefix.parent / f".protonhook-restore-{game.app.app_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    log(tr("Распаковываю {path}", path=archive))
    with tarfile.open(archive, "r:gz") as tar:
        try:
            tar.extractall(staging, filter="tar")
        except TypeError:  # Python < 3.10.12 has no extraction filters
            tar.extractall(staging)
    restored = staging / game.app.app_id
    if not (restored / "pfx").is_dir():
        shutil.rmtree(staging)
        log(tr("✖ В архиве нет префикса для appid {appid}.", appid=game.app.app_id))
        return False

    if make_backup:
        backup_prefix(game, log)
    old = prefix.parent / f".protonhook-old-{game.app.app_id}"
    if old.exists():
        shutil.rmtree(old)
    prefix.rename(old)
    restored.rename(prefix)
    shutil.rmtree(old)
    shutil.rmtree(staging)
    log(tr("✔ Префикс восстановлен."))
    return True


def prefix_backups(game: PrefixGame) -> list[Path]:
    if not BACKUP_ROOT.is_dir():
        return []
    return sorted(BACKUP_ROOT.glob(f"prefix-{game.app.app_id}-*.tar.gz"), reverse=True)


# ---------------------------------------------------------------- Unity saves


@dataclass
class UnitySaves:
    linux_dir: Path
    windows_dir: Path

    @staticmethod
    def _newest(directory: Path) -> float | None:
        times = [
            p.stat().st_mtime
            for p in directory.rglob("*")
            if p.is_file() and p.name not in SAVE_SKIP_NAMES
        ] if directory.is_dir() else []
        return max(times) if times else None

    @property
    def linux_mtime(self) -> float | None:
        return self._newest(self.linux_dir)

    @property
    def windows_mtime(self) -> float | None:
        return self._newest(self.windows_dir)


def unity_company_product(install_dir: Path | None) -> tuple[str, str] | None:
    if not install_dir or not install_dir.is_dir():
        return None
    for app_info in install_dir.glob("*_Data/app.info"):
        lines = [line.strip() for line in read_text_safe(app_info).splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    return None


def find_unity_saves(game: PrefixGame) -> UnitySaves | None:
    names = unity_company_product(game.app.install_dir)
    if not names:
        return None
    company, product = names
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    linux_dir = config_home / "unity3d" / company / product
    windows_dir = game.pfx / "drive_c/users/steamuser/AppData/LocalLow" / company / product
    return UnitySaves(linux_dir=linux_dir, windows_dir=windows_dir)


def copy_saves(source: Path, target: Path, label: str, log: Log) -> bool:
    if not source.is_dir():
        log(tr("Нет папки с сейвами: {path}", path=source))
        return False
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name, directory in (("source", source), ("target", target)):
        if directory.is_dir():
            dest = BACKUP_ROOT / f"saves-{label}-{stamp}-{name}"
            shutil.copytree(directory, dest)
            log(tr("Резервная копия {src} → {dest}", src=directory, dest=dest))
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in source.rglob("*"):
        if path.is_dir() or path.name in SAVE_SKIP_NAMES:
            continue
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
    log(tr("✔ Скопировано файлов: {n} → {path}", n=copied, path=target))
    log(tr("Если Steam при запуске спросит о конфликте облачных сохранений — выберите локальные файлы."))
    log_debug(f"saves copied {source} -> {target} files={copied}")
    return True


# ---------------------------------------------------------------- diagnostics


@dataclass
class Check:
    ok: bool | None  # None = informational / unknown
    title: str
    detail: str


def diagnose(
    game: PrefixGame,
    running_native: bool | None,
    trainer_path: Path | None,
) -> list[Check]:
    checks: list[Check] = []

    if running_native is True:
        checks.append(Check(False, tr("Игра запущена без Proton"),
                            tr("Нативная Linux-версия: Windows-трейнер к ней не подключится. "
                               "Включите Proton в Steam → Свойства → Совместимость.")))
    elif running_native is False:
        checks.append(Check(True, tr("Игра запущена через Proton"), ""))
    else:
        checks.append(Check(None, tr("Игра не запущена"), tr("Для запуска трейнера игру нужно запустить.")))

    if game.proton_path is None:
        checks.append(Check(None, "Proton", tr("Не определён (игра ещё ни разу не запускалась через Proton?)")))
    elif is_experimental_proton(game.proton_path):
        checks.append(Check(False, f"Proton: {game.proton_path.name}",
                            tr("Experimental часто ломает трейнеры. Выберите стабильный Proton в свойствах игры.")))
    else:
        checks.append(Check(True, f"Proton: {game.proton_path.name}", ""))

    status = prefix_dotnet_status(game.pfx)
    status_text = tr(DOTNET_STATUS_TEXT[status])
    info = read_exe_info(trainer_path) if trainer_path and trainer_path.is_file() else None
    needs_dotnet = bool(info and info.is_dotnet)
    if status == DOTNET_REAL:
        checks.append(Check(True, tr(".NET в префиксе"), status_text))
    elif status == DOTNET_NONE:
        checks.append(Check(False, tr(".NET в префиксе"), status_text +
                            tr(". Нажмите «Установить .NET 4.8» или восстановите префикс из копии.")))
    else:
        checks.append(Check(False if needs_dotnet else None, tr(".NET в префиксе"),
                            status_text +
                            (tr(". Трейнер написан на .NET — если он не видит игру, установите .NET 4.8.")
                             if needs_dotnet else "")))

    if info:
        kind = ".NET" if info.is_dotnet else tr("нативный")
        bits = tr("64-бит") if info.is_64bit else tr("32-бит")
        checks.append(Check(None, tr("Трейнер: {kind}, {bits}", kind=kind, bits=bits), str(trainer_path)))
        running = find_trainer_pids(trainer_path) if trainer_path else []
        if len(running) > 0:
            checks.append(Check(None, tr("Трейнер уже запущен ({n} шт.)", n=len(running)),
                                tr("Перед новым запуском ProtonHook закроет старые копии.")))
    elif trainer_path:
        checks.append(Check(False, tr("Трейнер"), tr("Файл не найден или не является .exe: {path}", path=trainer_path)))

    saves = find_unity_saves(game)
    if saves:
        lm, wm = saves.linux_mtime, saves.windows_mtime
        if lm and (not wm or lm > wm + 60):
            checks.append(Check(False, tr("Сейв Linux-версии новее Windows-сейва"),
                                tr("Linux: {linux}, Windows: {windows}. Перенесите сейв кнопкой «Linux → Windows».",
                                   linux=fmt_time(lm), windows=fmt_time(wm))))
        elif lm or wm:
            checks.append(Check(True, tr("Сейвы Unity"), f"Linux: {fmt_time(lm)}, Windows: {fmt_time(wm)}"))
    return checks


def fmt_time(ts: float | None) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else tr("нет")


HELP_TEXT_RU = """\
<b>Как пользоваться</b>
1. Запустите игру через Steam.
2. Нажмите «Обновить», выберите игру слева.
3. Выберите trainer.exe и нажмите «Запустить в префиксе».
ProtonHook сам возьмёт тот же Proton и префикс, что у игры, и закроет старые копии трейнера.

<b>«Игра запущена без Proton»</b>
Steam запустил нативную Linux-версию. Windows-трейнер к ней не подключится.
Steam → Свойства игры → Совместимость → «Принудительно использовать инструмент совместимости» → стабильный Proton. Перезапустите игру.
Сейвы Linux- и Windows-версий хранятся в разных местах — перенесите их на вкладке «Диагностика» (кнопка «Linux → Windows», работает для Unity-игр).

<b>Окно трейнера не появляется</b>
Чаще всего виноват Proton Experimental. Выберите стабильный Proton (например, Proton 9/10/11 или GE-Proton) и перезапустите игру.

<b>Трейнер открылся, но не видит игру (пустой Process ID)</b>
1. Проверьте, что версия трейнера совпадает с версией игры.
2. Если трейнер написан на .NET (см. «Диагностика»), а в префиксе только wine-mono — нажмите «Установить .NET 4.8». Игра должна быть закрыта. ProtonHook сначала сделает резервную копию префикса.
3. Попробуйте другой режим запуска или задержку 10–20 секунд.

<b>Установка .NET не удалась</b>
ProtonHook сам пробует обходной путь (прямой установщик .NET 4.8), а если и он не сработал — автоматически возвращает префикс в состояние до установки.
В новых версиях Proton (10, 11) установщик .NET Framework часто падает с ошибкой MSI 1603. В этом случае трейнер работает на wine-mono; если он не видит игру — попробуйте другую версию трейнера или другой режим запуска.
Вручную вернуть префикс можно кнопкой «Восстановить префикс…».

<b>Steam спрашивает о конфликте облачных сохранений</b>
После переноса сейва выберите локальные файлы, иначе Steam вернёт старый сейв из облака.

<b>Онлайн-игры и античит</b>
Трейнеры в играх с античитом (EAC, BattlEye и др.) могут привести к бану. Используйте их только в одиночных играх.

<b>Логи</b>
Общий: /tmp/protontrek.log, по игре: /tmp/protontrek-&lt;игра&gt;-&lt;appid&gt;.log
Резервные копии: ~/ProtonHook-backups
"""


HELP_TEXT_EN = """\
<b>How to use</b>
1. Start the game from Steam.
2. Press Refresh and select the game on the left.
3. Choose trainer.exe and press “Launch in prefix”.
ProtonHook uses the same Proton and prefix as the game and closes old trainer instances.

<b>“The game is running without Proton”</b>
Steam started the native Linux build. A Windows trainer cannot attach to it.
Steam → game Properties → Compatibility → “Force the use of a specific Steam Play compatibility tool” → a stable Proton. Restart the game.
Linux and Windows builds keep saves in different places — copy them on the Diagnostics tab (“Save Linux → Windows”, works for Unity games).

<b>The trainer window doesn't appear</b>
Usually caused by Proton Experimental. Choose a stable Proton (e.g. Proton 9/10/11 or GE-Proton) and restart the game.

<b>The trainer opens but can't see the game (empty Process ID)</b>
1. Make sure the trainer version matches the game version.
2. If the trainer is built on .NET (see Diagnostics) and the prefix only has wine-mono, press “Install .NET 4.8”. The game must be closed. ProtonHook backs up the prefix first.
3. Try another launch mode or a 10–20 second delay.

<b>.NET installation failed</b>
ProtonHook tries a workaround (the .NET 4.8 installer directly) and, if that fails too, automatically rolls the prefix back.
On newer Proton versions (10, 11) the .NET Framework installer often fails with MSI error 1603. The trainer then runs on wine-mono; if it can't see the game, try another trainer version or launch mode.
You can restore the prefix manually with “Restore prefix…”.

<b>Steam asks about a cloud save conflict</b>
After copying a save, choose the local files, otherwise Steam restores the old save from the cloud.

<b>Online games and anti-cheat</b>
Trainers in games with anti-cheat (EAC, BattlEye, etc.) can get you banned. Use them in single-player games only.

<b>Logs</b>
General: /tmp/protontrek.log, per game: /tmp/protontrek-&lt;game&gt;-&lt;appid&gt;.log
Backups: ~/ProtonHook-backups
"""


def help_text() -> str:
    return HELP_TEXT_EN if get_language() == "en" else HELP_TEXT_RU
