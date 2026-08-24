"""Plain-text extraction from the source .docx résumés.

Only handles the linear "ATS" résumé variants (no tables, no headers/footers) --
that's a deliberate scope limit, not an oversight: the styled non-ATS pair is a
presentation duplicate of the same content and isn't needed as a data source.
"""

from __future__ import annotations

from pathlib import Path

import docx


def extract_text(path: Path) -> str:
    document = docx.Document(str(path))
    lines = [p.text for p in document.paragraphs]
    return "\n".join(line for line in lines if line.strip())
