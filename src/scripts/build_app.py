"""Builds JARVIS.app via py2app's "alias" mode -- a real, properly-owned
app bundle, but NOT a frozen/bundled standalone build: alias mode only
creates a small compiled stub + symlinks, and still runs straight from
this project's own source tree/venv. Full py2app/PyInstaller freezing is
still deliberately avoided: this project's dependency tree (torch,
playwright, PyObjC WebKit, ctranslate2) is large and includes native
extensions/dynamic loading that a full freeze can struggle with -- and
there's no real benefit to freezing it anyway, since this only ever needs
to run on this one machine.

Why py2app instead of a hand-rolled bash-script wrapper (what this file
used to do): a real, confirmed bug. Homebrew's python@3.12 is a macOS
"framework" build, and CPython's own compiled startup code silently
re-execs itself into .../Resources/Python.app/Contents/MacOS/Python
whenever it isn't already running as that exact binary (confirmed via
`strings` on the interpreter itself -- unconditional, compiled in, not
something an env var can disable). That swap changes the running
process's bundle identity from com.nicholasbirochi.jarvis to the generic
org.python.python, which was silently breaking NSStatusItem: the menu bar
icon never appeared, with the process alive and no Python-level exception
anywhere -- only visible via Console.app ("AppKit:StatusBar] scene
activation failed", repeating forever on every real double-click launch).
py2app's alias mode embeds the interpreter via the C API instead of
exec-ing CPython's own executable, so that re-exec path never runs. See
setup.py for the actual py2app config.

Run once (`python scripts/build_app.py`); safe to rerun any time (e.g.
after regenerating the icon, or if the project ever moves) -- rebuilds
from scratch rather than patching in place.

Ad-hoc signs the bundle after building (`codesign --sign -`) -- found
live that without ANY signature at all, Apple Silicon's Gatekeeper
rejects the app outright (`spctl --assess` returns "rejected", and a
Finder double-click does nothing visible, no error dialog). Ad-hoc
signing doesn't fully satisfy Gatekeeper on its own either (no Apple
Developer ID, no notarization -- `spctl --add` to force an override no
longer exists on current macOS, Apple removed it) -- the one remaining
manual step is real and unavoidable for a locally-built, unsigned app:
right-click (or Control-click) JARVIS.app -> "Abrir" -> confirm in the
dialog, once. After that first confirmed launch, plain double-clicks
work normally from then on.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGING_DIR = PROJECT_ROOT / "src" / "packaging"
APP_NAME = "JARVIS.app"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def build(target_dir: Path) -> Path:
    app_path = target_dir / APP_NAME
    if app_path.exists():
        shutil.rmtree(app_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    # py2app's own intermediate `build/` dir (already gitignored) --
    # cleared first so a stale alias build never lingers half-updated.
    build_dir = PACKAGING_DIR / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    subprocess.run(
        [
            str(VENV_PYTHON),
            "setup.py",
            "py2app",
            "--dist-dir",
            str(target_dir),
        ],
        cwd=PACKAGING_DIR,
        check=True,
    )

    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app_path)], check=True)

    return app_path


def main() -> None:
    check = subprocess.run([str(VENV_PYTHON), "-c", "import py2app"], capture_output=True)
    if check.returncode != 0:
        print(
            "py2app não está instalado no venv -- rode "
            "descomente a seção de empacotamento em requirements.txt e rode "
            "`.venv/bin/pip install -r requirements.txt` primeiro.",
            file=sys.stderr,
        )
        sys.exit(1)

    target_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("/Applications")
    try:
        app_path = build(target_dir)
    except PermissionError:
        target_dir = Path.home() / "Applications"
        app_path = build(target_dir)
    print(f"JARVIS.app criado em: {app_path}")
    print(
        'Primeira vez: clique com o botão direito (ou Control-clique) no JARVIS.app -> '
        '"Abrir" -> confirme no aviso -- é a única vez que precisa disso. '
        "Depois disso, dois cliques normais funcionam."
    )


if __name__ == "__main__":
    main()
