# ProtonHook

Небольшая GUI-утилита на Python для Linux:

- ищет запущенные Steam-игры под Proton;
- определяет их `appid` и Proton-префикс из `steamapps/compatdata/<appid>`;
- позволяет выбрать `trainer.exe`;
- запускает этот `trainer.exe` в выбранном Proton-префиксе.
- для запуска использует `proton runinprefix start /unix`, чтобы меньше конфликтовать с уже работающей игрой.
- позволяет выбрать режим запуска и задержку перед стартом трейнера.

## Запуск

```bash
python3 steam_trainer_launcher.py
```

Интерфейс — одно окно на GTK 3 (PyGObject, есть в Fedora/Bazzite из коробки). Если GTK недоступен, используется `tkinter`, а если нет и его — пошаговые диалоги `zenity`.

Если игра запущена как нативная Linux-версия (без Proton), утилита покажет предупреждение: Windows-трейнер к такой игре подключиться не может — включите Proton в свойствах игры в Steam.

После запуска `trainer.exe` программа пишет лог в `/tmp/protontrek-<game>-<appid>.log`.

## Как это работает

Программа:

1. Ищет стандартную директорию Steam.
2. Читает `libraryfolders.vdf` и `appmanifest_*.acf`.
3. Сканирует `/proc`, чтобы найти запущенные процессы игр.
4. Пытается вытащить `appid` из переменных окружения Steam/Proton или из путей процесса.
5. Использует путь `steamapps/compatdata/<appid>` как Proton-префикс.
6. Пытается использовать тот же Proton, которым запущена игра.
7. Даёт переключать режим запуска (`runinprefix start /unix`, `runinprefix`, `run`) и задавать задержку старта.

## Плагин для Decky Loader

Та же логика доступна как плагин для [Decky Loader](https://decky.xyz): можно выбрать игру и запустить `trainer.exe` прямо из Quick Access Menu на Steam Deck, не сворачивая игру.

Бэкенд плагина (`main.py`) и стандалон-скрипт (`steam_trainer_launcher.py`) используют общий модуль `protontrek_core.py` — вся логика поиска игр, префиксов и запуска не дублируется.

### Сборка фронтенда

Нужны Node.js 16.14+ и pnpm v9:

```bash
sudo npm i -g pnpm@9
pnpm install
pnpm run build
```

Команда соберёт `dist/index.js`. Питоновский бэкенд сборки не требует.

### Установка на Steam Deck

**Вручную:**
1. Собери плагин (см. выше).
2. Скопируй `plugin.json`, `package.json`, `main.py`, `protontrek_core.py` и папку `dist/` в `~/homebrew/plugins/ProtonHook` на Steam Deck (например, по SSH или через Konsole/Dolphin в Desktop Mode).
3. Перезапусти Decky Loader — в Quick Access Menu появится вкладка ProtonHook.

**Через "Install from ZIP":**
1. Включи Developer Mode в настройках Decky Loader.
2. Запакуй в zip файлы `plugin.json`, `package.json`, `main.py`, `protontrek_core.py` и папку `dist/` (без `node_modules`, `src`).
3. В Decky Loader выбери "Install Plugin from ZIP" и укажи архив.

### Особенности реализации

- В `plugin.json` намеренно нет флага `root` — бэкенд плагина работает от имени обычного пользователя `deck`, как и Steam с игрой. Чтение `/proc/<pid>/environ` запущенного процесса игры требует совпадения UID, так что запуск от root тут не нужен и не помогает.
- Выбор `trainer.exe` в UI плагина идёт через встроенный файловый пикер Decky Loader (`openFilePicker` из `@decky/api`), отдельный бэкенд для этого не нужен.

## Ограничения

- Утилита рассчитана на Linux и локальную установку Steam.
- Для GUI нужен либо `python3-tk`, либо установленный `zenity`.
- Для разбора проблем запуска смотри `/tmp/protontrek.log` и `/tmp/protontrek-<game>-<appid>.log`.
- Она лучше всего работает, когда игра уже запущена через Proton.
- Некоторые игры могут не выставлять достаточно информации в `/proc`, тогда игра может не определиться.
- Для запуска `trainer.exe` нужен доступный `proton` в установленном Steam.
