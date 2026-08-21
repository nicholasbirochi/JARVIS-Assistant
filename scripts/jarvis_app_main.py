"""Real entry-point script for the packaged JARVIS.app (see setup.py +
scripts/build_app.py). py2app's alias-mode stub runs this file directly as
its own compiled loader's embedded Python -- kept as a tiny separate file
(rather than pointing py2app at jarvis/menubar.py itself) so this can add
the project root to sys.path first, since alias mode doesn't otherwise
guarantee the `jarvis` package is importable from wherever py2app's stub
ends up running from.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from menubar import main  # noqa: E402

if __name__ == "__main__":
    main()
