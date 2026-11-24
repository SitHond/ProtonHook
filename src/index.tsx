import {
  ButtonItem,
  Dropdown,
  DropdownOption,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  staticClasses,
} from "@decky/ui";
import {
  callable,
  definePlugin,
  FileSelectionType,
  openFilePicker,
  toaster,
} from "@decky/api";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";

interface GameInfo {
  app_id: string;
  name: string;
  pid: number;
  process_name: string;
  command: string;
  source: string;
  prefix: string;
  proton_path: string | null;
  install_dir: string | null;
}

interface ListGamesResult {
  steam_root: string | null;
  games: GameInfo[];
}

interface LaunchModeInfo {
  key: string;
  label: string;
  description: string;
}

interface LaunchResult {
  ok: boolean;
  log_path?: string;
  error?: string;
}

const listGames = callable<[], ListGamesResult>("list_games");
const getLaunchModes = callable<[], LaunchModeInfo[]>("get_launch_modes");
const launchTrainer = callable<
  [appId: string, trainerPath: string, mode: string, delaySeconds: number],
  LaunchResult
>("launch_trainer");

function Content() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [modes, setModes] = useState<LaunchModeInfo[]>([]);
  const [mode, setMode] = useState<string>("");
  const [trainerPath, setTrainerPath] = useState<string>("");
  const [delaySeconds, setDelaySeconds] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>("Поиск Steam...");

  const refresh = async () => {
    setLoading(true);
    try {
      const result = await listGames();
      setGames(result.games);
      if (result.games.length > 0) {
        setSelectedAppId((prev) =>
          prev && result.games.some((g) => g.app_id === prev) ? prev : result.games[0].app_id
        );
        setStatus(`Найдено игр: ${result.games.length}`);
      } else if (!result.steam_root) {
        setStatus("Steam не найден.");
      } else {
        setStatus("Активные Steam-игры под Proton не найдены.");
      }
    } catch (e) {
      setStatus(`Ошибка: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      const modeList = await getLaunchModes();
      setModes(modeList);
      if (modeList.length > 0) {
        setMode(modeList[0].key);
      }
      await refresh();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedGame = games.find((g) => g.app_id === selectedAppId) ?? null;

  const pickTrainer = async () => {
    const startPath = selectedGame?.install_dir || selectedGame?.prefix || "/home/deck";
    try {
      const res = await openFilePicker(
        FileSelectionType.FILE,
        startPath,
        true,
        true,
        undefined,
        ["exe"],
        false,
        true
      );
      setTrainerPath(res.realpath);
    } catch {
      // user cancelled the picker
    }
  };

  const runTrainer = async () => {
    if (!selectedGame) {
      setStatus("Сначала выберите игру.");
      return;
    }
    if (!trainerPath) {
      setStatus("Сначала выберите trainer.exe.");
      return;
    }
    setLoading(true);
    try {
      const result = await launchTrainer(selectedGame.app_id, trainerPath, mode, delaySeconds);
      if (result.ok) {
        setStatus(`Запущено. Лог: ${result.log_path}`);
        toaster.toast({
          title: "ProtonHook",
          body: `Trainer запущен для ${selectedGame.name}`,
        });
      } else {
        setStatus(`Ошибка: ${result.error}`);
        toaster.toast({
          title: "ProtonHook: ошибка",
          body: result.error ?? "неизвестная ошибка",
        });
      }
    } catch (e) {
      setStatus(`Ошибка: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  const gameOptions: DropdownOption[] = games.map((g) => ({
    data: g.app_id,
    label: `${g.name} [${g.app_id}]`,
  }));

  const modeOptions: DropdownOption[] = modes.map((m) => ({
    data: m.key,
    label: m.label,
  }));

  return (
    <PanelSection title="ProtonHook">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={refresh} disabled={loading}>
          Обновить список игр
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field
          label="Игра"
          description={selectedGame ? `PID ${selectedGame.pid} · источник: ${selectedGame.source}` : undefined}
        >
          <Dropdown
            rgOptions={gameOptions}
            selectedOption={selectedAppId}
            strDefaultLabel="Нет активных игр"
            onChange={(o) => setSelectedAppId(o.data)}
          />
        </Field>
      </PanelSectionRow>

      {selectedGame && (
        <PanelSectionRow>
          <Field label="Proton" description={selectedGame.proton_path ?? "Не определён"} />
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <Field label="Trainer" description={trainerPath || "Не выбран"}>
          <ButtonItem layout="below" onClick={pickTrainer}>
            Выбрать trainer.exe
          </ButtonItem>
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field label="Режим запуска">
          <Dropdown rgOptions={modeOptions} selectedOption={mode} onChange={(o) => setMode(o.data)} />
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <SliderField
          label="Задержка, сек"
          value={delaySeconds}
          min={0}
          max={600}
          step={5}
          showValue
          editableValue
          onChange={setDelaySeconds}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={runTrainer}
          disabled={loading || !selectedGame || !trainerPath}
        >
          Запустить в префиксе
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field label="Статус" description={status} />
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => {
  return {
    name: "ProtonHook",
    titleView: <div className={staticClasses.Title}>ProtonHook</div>,
    content: <Content />,
    icon: <FaGamepad />,
    // Keeps our component mounted while the Quick Access Menu is hidden (e.g. while
    // the file picker modal is open), otherwise its state - including the trainer
    // path just picked - is lost when the panel remounts.
    alwaysRender: true,
  };
});
