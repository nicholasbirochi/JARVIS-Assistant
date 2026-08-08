"""py2app config for JARVIS.app. Don't run `python setup.py py2app`
directly -- use `python scripts/build_app.py`, which drives this with the
right target directory and handles ad-hoc codesigning afterward.

Lives in its own packaging/ directory, deliberately NOT next to the
project's real pyproject.toml: when setup.py runs alongside a
pyproject.toml that declares static `[project.dependencies]`, setuptools
auto-merges those into `Distribution.install_requires` regardless of what
this file passes to `setup()` -- and py2app explicitly refuses to run at
all when that's set ("install_requires is no longer supported", a real
error hit while wiring this up, not a guess). Keeping this setup.py in its
own directory with no sibling pyproject.toml sidesteps the auto-merge
entirely.

Why py2app at all (a real bug, root-caused): see the long comment on the
`packaging` extra in pyproject.toml and the module docstring of
scripts/build_app.py. Short version -- Homebrew's python@3.12 is a macOS
"framework" build, and CPython's own compiled startup code silently
re-execs itself into .../Resources/Python.app/Contents/MacOS/Python
whenever it isn't already running as that exact binary. That swap changes
the running process's bundle identity to the generic org.python.python,
which broke NSStatusItem (the menu bar icon never appeared -- confirmed
live via Console.app: "AppKit:StatusBar] scene activation failed", every
real double-click launch). py2app's "alias" mode (`alias: True` below)
sidesteps this entirely: its own compiled stub embeds the Python
interpreter via the C API instead of exec-ing CPython's own executable, so
that re-exec path never runs -- while still running straight from this
project's live source/venv, no freezing, no bundling of dependencies.
"""

from pathlib import Path

from setuptools import setup

PROJECT_ROOT = Path(__file__).resolve().parent.parent

APP = [str(PROJECT_ROOT / "scripts" / "jarvis_app_main.py")]

OPTIONS = {
    "py2app": {
        "alias": True,
        "iconfile": str(PROJECT_ROOT / "jarvis" / "assets" / "AppIcon.icns"),
        "plist": {
            "CFBundleName": "JARVIS",
            "CFBundleDisplayName": "JARVIS",
            "CFBundleIdentifier": "com.nicholasbirochi.jarvis",
            "CFBundleVersion": "1.0",
            "CFBundleShortVersionString": "1.0",
            # No Dock icon/Cmd-Tab -- belt-and-suspenders alongside the
            # runtime NSApplicationActivationPolicyAccessory call in
            # jarvis/menubar.py itself.
            "LSUIElement": True,
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
        },
    }
}

setup(
    name="JARVIS",
    app=APP,
    options=OPTIONS,
)
