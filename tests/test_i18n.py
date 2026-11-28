#!/usr/bin/env python3
"""Every string passed to tr() must have an English translation.

Run: python3 tests/test_i18n.py
"""
from __future__ import annotations

import ast
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402
import protontrek_core  # noqa: E402
import protonhook_tools  # noqa: E402

SOURCES = ["gtk_ui.py", "protonhook_tools.py", "protontrek_core.py"]


def literal_tr_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.append(node.args[0].value)
    return found


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def main() -> int:
    strings = []
    for name in SOURCES:
        strings += literal_tr_strings(ROOT / name)
    # Strings translated through variables.
    strings += [protontrek_core.NATIVE_LINUX_HINT, protontrek_core.EXPERIMENTAL_PROTON_HINT]
    strings += list(protonhook_tools.DOTNET_STATUS_TEXT.values())
    strings += [description for _label, description in protontrek_core.LAUNCH_MODES.values()]

    errors = []
    for text in sorted(set(strings)):
        if text not in i18n.EN:
            errors.append(f"missing translation: {text!r}")
        elif placeholders(text) != placeholders(i18n.EN[text]):
            errors.append(f"placeholder mismatch: {text!r}")
    for error in errors:
        print(error)
    print(f"checked {len(set(strings))} strings, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
