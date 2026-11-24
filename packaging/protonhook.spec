# PyInstaller spec for the single-file ProtonHook Linux binary.
# Used by packaging/build.sh; PROTONHOOK_SRC points at the staged sources.
import os

src = os.environ["PROTONHOOK_SRC"]

a = Analysis(
    [os.path.join(src, "steam_trainer_launcher.py")],
    pathex=[src],
    hiddenimports=[
        "gtk_ui",
        "protonhook_tools",
        "gi.repository.Gtk",
        "gi.repository.GLib",
        "gi.repository.Pango",
    ],
    hooksconfig={
        "gi": {
            # The UI is written for GTK 3; without this PyInstaller may pick GTK 4.
            "module-versions": {"Gtk": "3.0", "Gdk": "3.0"},
            "icons": ["Adwaita"],
            "themes": ["Adwaita"],
            "languages": ["ru", "en"],
        }
    },
    # GTK is the primary UI and zenity is the fallback; Tk only adds weight.
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="protonhook",
    console=True,
    strip=False,
    upx=False,
)
