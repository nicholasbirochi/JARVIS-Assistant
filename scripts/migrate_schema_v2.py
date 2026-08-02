"""One-off script: bump data/resume.json to schema_version "2.0" and
materialize the new v2 fields (evidence/conflicts/change_log/availability)
explicitly on disk, instead of relying on load-time pydantic defaults
forever. The old data already validates against the v2 schema as-is (every
new field has a default) -- this just makes the migration an explicit,
auditable, backed-up event.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.resume import store  # noqa: E402


def main() -> None:
    resume = store.load()
    if resume.meta.schema_version == "2.0":
        print("Currículo já está no schema_version 2.0 -- nada para migrar.")
        return

    resume.meta.schema_version = "2.0"
    store.save(resume)
    print("Migrado para schema_version 2.0 (backup do arquivo anterior criado em data/backups/).")


if __name__ == "__main__":
    main()
