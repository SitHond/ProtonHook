import os
import sys
from pathlib import Path

# Make the sibling `protontrek_core.py` importable regardless of decky-loader's cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import decky
import protontrek_core as core


def _steam_root() -> Path | None:
    # decky.DECKY_USER_HOME always points at the deck user's home, whether or not
    # this plugin runs with the "root" flag (it doesn't - see plugin.json).
    return core.discover_steam_root(Path(decky.DECKY_USER_HOME))


class Plugin:
    async def list_games(self) -> dict:
        steam_root = _steam_root()
        if not steam_root:
            return {"steam_root": None, "games": []}
        games = core.find_running_games(steam_root)
        return {
            "steam_root": str(steam_root),
            "games": [core.game_to_dict(game) for game in games],
        }

    async def get_launch_modes(self) -> list:
        return core.launch_modes_list()

    async def launch_trainer(
        self,
        app_id: str,
        trainer_path: str,
        mode: str,
        delay_seconds: int,
    ) -> dict:
        try:
            steam_root = _steam_root()
            if not steam_root:
                raise RuntimeError("Steam не найден.")

            games = core.find_running_games(steam_root)
            game = next((g for g in games if g.app.app_id == app_id), None)
            if not game:
                raise RuntimeError("Игра больше не активна. Обновите список.")

            trainer = Path(trainer_path).expanduser()
            if not trainer.exists():
                raise RuntimeError(f"Не найден файл: {trainer}")

            seconds = core.parse_delay_seconds(str(int(delay_seconds)))
            _process, log_path = core.launch_trainer(game, trainer, mode, seconds, steam_root)
            decky.logger.info(
                "launched trainer=%s for appid=%s mode=%s delay=%s",
                trainer, app_id, mode, seconds,
            )
            return {"ok": True, "log_path": str(log_path)}
        except Exception as exc:  # noqa: BLE001
            decky.logger.exception("launch_trainer failed")
            return {"ok": False, "error": str(exc)}

    async def _main(self):
        decky.logger.info("ProtonHook plugin loaded")

    async def _unload(self):
        decky.logger.info("ProtonHook plugin unloaded")

    async def _uninstall(self):
        pass
