"""Text extraction dispatch for the indexer. Returns None for anything
genuinely unreadable (unsupported extension, corrupt file, a scanned-image
PDF with no text layer) so the caller can flag it for manual review instead
of crashing a whole indexing run over one bad file. OSError is the one
exception NOT swallowed here -- it means the file itself couldn't be
accessed (e.g. a OneDrive "online-only" placeholder that timed out because
the sync app wasn't running), which is a transient I/O problem, not a
verdict about the file's content. The caller (runner.py) retries those
instead of recording a permanent "no text" result."""

from __future__ import annotations

from pathlib import Path


def extract_text(path: Path) -> str | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            from resume.docx_extract import extract_text as extract_docx_text

            text = extract_docx_text(path)
        elif suffix == ".pdf":
            text = _extract_pdf_text(path)
        elif suffix in (".txt", ".md"):
            text = path.read_text(encoding="utf-8", errors="ignore")
        else:
            return None
    except OSError:
        raise
    except Exception:
        return None

    text = (text or "").strip()
    return text or None


def _extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)
