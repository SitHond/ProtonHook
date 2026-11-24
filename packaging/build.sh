#!/usr/bin/env bash
# Build release artifacts:
#   protonhook      – single-file Linux binary (PyInstaller, GTK bundled)
#   protonhook.pyz  – small zipapp, needs system python3 + PyGObject (GTK 3)
#
# Usage: packaging/build.sh [version]
#   PYINSTALLER=/path/to/pyinstaller  override the pyinstaller command
#   OUT=/path/to/dir                  output directory (default: dist-release)
set -euo pipefail

VERSION="${1:-0.0.0-dev}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${OUT:-$ROOT/dist-release}"
PYINSTALLER="${PYINSTALLER:-pyinstaller}"
SOURCES=(steam_trainer_launcher.py protontrek_core.py protonhook_tools.py gtk_ui.py)

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/src" "$OUT"
for file in "${SOURCES[@]}"; do
    cp "$ROOT/$file" "$STAGE/src/"
done
sed -i "s/^__version__ = .*/__version__ = \"${VERSION}\"/" "$STAGE/src/protontrek_core.py"

echo "==> Building protonhook ${VERSION} (single-file binary)"
PROTONHOOK_SRC="$STAGE/src" "$PYINSTALLER" --noconfirm --clean \
    --distpath "$OUT" --workpath "$STAGE/work" \
    "$ROOT/packaging/protonhook.spec"

echo "==> Building protonhook.pyz (zipapp)"
python3 -m zipapp "$STAGE/src" -m "steam_trainer_launcher:main" \
    -p "/usr/bin/env python3" -o "$OUT/protonhook.pyz"
chmod +x "$OUT/protonhook" "$OUT/protonhook.pyz"

(cd "$OUT" && sha256sum protonhook protonhook.pyz > SHA256SUMS)
echo "==> Done:"
ls -lh "$OUT"
