#!/usr/bin/env python3
"""Tiny gettext-style localisation for ProtonHook (Russian / English).

Source strings in the code stay Russian; `tr()` returns the English
translation from `EN` when English is active. Placeholders use
str.format syntax: tr("Найдено игр: {n}", n=3).
"""
from __future__ import annotations

import os

LANGUAGES = {"ru": "Русский", "en": "English"}
_current = "ru"


def detect_language() -> str:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return "ru" if value.lower().startswith("ru") else "en"
    return "en"


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else "en"


def get_language() -> str:
    return _current


def tr(text: str, **kwargs: object) -> str:
    result = EN.get(text, text) if _current == "en" else text
    return result.format(**kwargs) if kwargs else result


EN: dict[str, str] = {
    # ---- window / header
    "Трейнеры для игр в Proton": "Trainers for Proton games",
    "Обновить список игр": "Refresh game list",
    "Язык интерфейса": "Interface language",
    "Игры с Proton-префиксом": "Games with a Proton prefix",
    "Поиск Steam...": "Looking for Steam...",
    "Запуск": "Launch",
    "Диагностика": "Diagnostics",
    "Справка": "Help",
    # ---- launch tab
    "Состояние": "Status",
    "Префикс": "Prefix",
    "Процесс": "Process",
    "Трейнер": "Trainer",
    "Путь к trainer.exe": "Path to trainer.exe",
    "Выбрать…": "Browse…",
    "Выбрать": "Select",
    "Режим запуска": "Launch mode",
    "Задержка, сек": "Delay, sec",
    "Запустить в префиксе": "Launch in prefix",
    "Не запущена — запустите игру через Steam": "Not running — start the game from Steam",
    "Запущена через Proton": "Running through Proton",
    "Запущена без Proton (нативная Linux-версия)": "Running without Proton (native Linux build)",
    "Не используется": "Not used",
    "Не определён": "Unknown",
    "PID: {pid}\nИмя: {name}\nИсточник appid: {source}\nКоманда:\n{command}":
        "PID: {pid}\nName: {name}\nappid source: {source}\nCommand:\n{command}",
    "запущена": "running",
    " без Proton": " without Proton",
    "Запущено: {running} · всего: {total}": "Running: {running} · total: {total}",
    # ---- launch modes (descriptions)
    "Мягкий запуск внутри префикса через start /unix": "Gentle start inside the prefix via start /unix",
    "Прямой запуск через wine внутри того же префикса": "Direct start via wine inside the same prefix",
    "Обычный запуск через Proton run": "Regular start via Proton run",
    # ---- diagnostics tab
    "Установить .NET 4.8": "Install .NET 4.8",
    "Нужно для большинства .NET-трейнеров (FLiNG и др.). Игра должна быть закрыта. "
    "Сначала делается резервная копия префикса.":
        "Required by most .NET trainers (FLiNG etc.). The game must be closed. "
        "The prefix is backed up first.",
    "Резервная копия префикса": "Back up prefix",
    "Архив префикса в {path}": "Prefix archive in {path}",
    "Восстановить префикс…": "Restore prefix…",
    "Вернуть префикс из резервной копии": "Restore the prefix from a backup",
    "Сейв Linux → Windows": "Save Linux → Windows",
    "Сейв Windows → Linux": "Save Windows → Linux",
    "Перенести сейв Unity-игры из нативной версии в Proton":
        "Copy a Unity game's save from the native build to Proton",
    "Перенести сейв Unity-игры из Proton в нативную версию":
        "Copy a Unity game's save from Proton to the native build",
    "Перепроверить": "Re-check",
    "Заново выполнить проверки": "Run the checks again",
    "Журнал действий": "Action log",
    # ---- messages
    "Steam не найден": "Steam not found",
    "Steam не найден. Проверьте стандартный путь установки.":
        "Steam was not found. Check the default install location.",
    "Игры с Proton-префиксом не найдены.": "No games with a Proton prefix found.",
    "Запущенных игр нет. Запустите игру через Steam и нажмите «Обновить». "
    "Диагностика и исправления доступны и для закрытых игр.":
        "No games are running. Start a game from Steam and press Refresh. "
        "Diagnostics and fixes also work for closed games.",
    "Уже выполняется другое действие — дождитесь окончания.":
        "Another action is already running — please wait for it to finish.",
    "{title}… Ход выполнения — на вкладке «Диагностика».": "{title}… Progress is shown on the Diagnostics tab.",
    "готово": "done",
    "не удалось — см. журнал": "failed — see the log",
    "{title}: {result}.": "{title}: {result}.",
    "✖ Ошибка: {error}": "✖ Error: {error}",
    "Сначала выберите игру.": "Select a game first.",
    "Закройте игру и трейнер — это действие нельзя выполнять, пока префикс используется.":
        "Close the game and the trainer — this cannot be done while the prefix is in use.",
    "Установка .NET 4.8 для «{name}»": "Installing .NET 4.8 for “{name}”",
    "Выберите резервную копию префикса": "Choose a prefix backup",
    "Восстановить": "Restore",
    "Отмена": "Cancel",
    "Архивы префикса (*.tar.gz)": "Prefix archives (*.tar.gz)",
    "Восстановление префикса": "Restoring prefix",
    "Не удалось найти сейвы: перенос работает для Unity-игр.":
        "No saves found: save transfer works for Unity games.",
    "Перенос сейва Linux → Windows": "Copying save Linux → Windows",
    "Перенос сейва Windows → Linux": "Copying save Windows → Linux",
    "Выберите trainer.exe": "Choose trainer.exe",
    "Windows-программы (*.exe)": "Windows executables (*.exe)",
    "Все файлы": "All files",
    "Сначала запустите игру и выберите её в списке.": "Start the game and select it in the list first.",
    "Сначала выберите trainer.exe.": "Choose trainer.exe first.",
    "Не найден файл: {path}": "File not found: {path}",
    "Ошибка запуска: {error}": "Launch failed: {error}",
    "сразу": "immediately",
    "через {n} сек": "in {n} s",
    "Трейнер запускается для «{name}» ({mode}, {start}).\nЛог: {log}":
        "Starting the trainer for “{name}” ({mode}, {start}).\nLog: {log}",
    "\nЗакрыто старых копий трейнера: {n}.": "\nClosed old trainer instances: {n}.",
    "\n\nТрейнер написан на .NET, а в префиксе нет настоящего .NET Framework. "
    "Если трейнер не увидит игру — закройте игру и установите .NET 4.8.":
        "\n\nThe trainer is built on .NET, but the prefix has no real .NET Framework. "
        "If the trainer can't see the game, close the game and install .NET 4.8.",
    "Открыть диагностику": "Open diagnostics",
    # ---- core hints / errors
    "Игра запущена как нативная Linux-версия, без Proton. "
    "Windows-трейнер не сможет к ней подключиться.\n"
    "Включите Proton: Steam → Свойства игры → Совместимость → "
    "«Принудительно использовать инструмент совместимости» (лучше стабильный Proton, "
    "не Experimental), перезапустите игру и нажмите «Обновить».":
        "The game is running as the native Linux build, without Proton. "
        "A Windows trainer cannot attach to it.\n"
        "Enable Proton: Steam → game Properties → Compatibility → "
        "“Force the use of a specific Steam Play compatibility tool” (preferably a stable Proton, "
        "not Experimental), restart the game and press Refresh.",
    "Игра запущена в Proton Experimental. В нём трейнеры часто не находят процесс игры "
    "или не показывают окно. Если трейнер пишет, что игра не найдена: Steam → Свойства "
    "игры → Совместимость → выберите стабильный Proton (например, Proton 9.0 или GE-Proton), "
    "перезапустите игру и нажмите «Обновить».":
        "The game is running in Proton Experimental, where trainers often can't find the game "
        "process or don't show a window. If the trainer says the game is not found: Steam → game "
        "Properties → Compatibility → choose a stable Proton (e.g. Proton 9.0 or GE-Proton), "
        "restart the game and press Refresh.",
    "Не удалось определить путь к Proton для этой игры.": "Could not determine the Proton path for this game.",
    "Файл Proton не найден: {path}": "Proton script not found: {path}",
    "Неизвестный режим запуска: {mode}": "Unknown launch mode: {mode}",
    # ---- tools: log
    "Резервная копия префикса → {path}": "Prefix backup → {path}",
    "Готово, {mb} МБ": "Done, {mb} MB",
    "Выдаю protontricks доступ к {path}": "Granting protontricks access to {path}",
    "Префикс занят: закройте игру и трейнер, затем повторите.":
        "The prefix is in use: close the game and the trainer, then try again.",
    "Не удалось определить Proton этой игры. Запустите игру через Steam хотя бы раз.":
        "Could not determine this game's Proton. Start the game from Steam at least once.",
    "protontricks не найден. Установите его: {cmd}": "protontricks not found. Install it: {cmd}",
    "Откатываю префикс к состоянию до установки…": "Rolling the prefix back to its pre-install state…",
    "Префикс возвращён как был (с wine-mono). .NET 4.8 в этом Proton установить не удалось — см. «Справка».":
        "The prefix is back as it was (with wine-mono). .NET 4.8 could not be installed with this Proton — "
        "see Help.",
    "Шаг 1/2: protontricks dotnet48 (может занять 10–20 минут)…":
        "Step 1/2: protontricks dotnet48 (may take 10–20 minutes)…",
    "✔ .NET Framework 4.8 установлен.": "✔ .NET Framework 4.8 installed.",
    "Стандартная установка не удалась — пробую установить .NET 4.8 напрямую.":
        "The standard install failed — trying to install .NET 4.8 directly.",
    "Установщик .NET 4.8 не найден в кэше winetricks.": "The .NET 4.8 installer was not found in the winetricks cache.",
    "Шаг 2/2: запуск установщика .NET 4.8…": "Step 2/2: running the .NET 4.8 installer…",
    "✖ Установщик .NET 4.8 завершился с кодом {rc}.": "✖ The .NET 4.8 installer exited with code {rc}.",
    "Распаковываю {path}": "Extracting {path}",
    "✖ В архиве нет префикса для appid {appid}.": "✖ The archive has no prefix for appid {appid}.",
    "✔ Префикс восстановлен.": "✔ Prefix restored.",
    "Нет папки с сейвами: {path}": "No save folder: {path}",
    "Резервная копия {src} → {dest}": "Backup {src} → {dest}",
    "✔ Скопировано файлов: {n} → {path}": "✔ Files copied: {n} → {path}",
    "Если Steam при запуске спросит о конфликте облачных сохранений — выберите локальные файлы.":
        "If Steam asks about a cloud save conflict on launch, choose the local files.",
    # ---- tools: diagnostics
    "установлен настоящий .NET Framework 4.x": "real .NET Framework 4.x is installed",
    "только wine-mono (замена .NET, совместима не со всеми трейнерами)":
        "wine-mono only (a .NET replacement, not compatible with every trainer)",
    "нет .NET: wine-mono удалён, а .NET не установился": "no .NET: wine-mono was removed and .NET failed to install",
    "Игра запущена без Proton": "The game is running without Proton",
    "Нативная Linux-версия: Windows-трейнер к ней не подключится. "
    "Включите Proton в Steam → Свойства → Совместимость.":
        "Native Linux build: a Windows trainer won't attach to it. "
        "Enable Proton in Steam → Properties → Compatibility.",
    "Игра запущена через Proton": "The game is running through Proton",
    "Игра не запущена": "The game is not running",
    "Для запуска трейнера игру нужно запустить.": "Start the game to launch a trainer.",
    "Не определён (игра ещё ни разу не запускалась через Proton?)":
        "Unknown (has the game never been started with Proton?)",
    "Experimental часто ломает трейнеры. Выберите стабильный Proton в свойствах игры.":
        "Experimental often breaks trainers. Choose a stable Proton in the game's properties.",
    ".NET в префиксе": ".NET in the prefix",
    ". Нажмите «Установить .NET 4.8» или восстановите префикс из копии.":
        ". Press “Install .NET 4.8” or restore the prefix from a backup.",
    ". Трейнер написан на .NET — если он не видит игру, установите .NET 4.8.":
        ". The trainer is built on .NET — if it can't see the game, install .NET 4.8.",
    "нативный": "native",
    "Трейнер: {kind}, {bits}": "Trainer: {kind}, {bits}",
    "64-бит": "64-bit",
    "32-бит": "32-bit",
    "Трейнер уже запущен ({n} шт.)": "Trainer already running ({n})",
    "Перед новым запуском ProtonHook закроет старые копии.": "ProtonHook will close the old instances before launching.",
    "Файл не найден или не является .exe: {path}": "File not found or not an .exe: {path}",
    "Сейв Linux-версии новее Windows-сейва": "The Linux save is newer than the Windows save",
    "Linux: {linux}, Windows: {windows}. Перенесите сейв кнопкой «Linux → Windows».":
        "Linux: {linux}, Windows: {windows}. Copy it with “Save Linux → Windows”.",
    "Сейвы Unity": "Unity saves",
    "нет": "none",
}
