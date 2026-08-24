"""Ensures src/ itself is on sys.path during test collection, so this
project's flat modules (config, sites, resume, ...) are importable as
plain top-level names -- there's no installed package anymore (see
requirements.txt/readme.md's "Rodando sem instalar" section, replacing
the old pyproject.toml editable install). pytest auto-discovers
conftest.py files by walking up from each test file regardless of the
directory pytest was actually invoked from, which is why this works no
matter where `pytest`/`python -m pytest` is run from."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
