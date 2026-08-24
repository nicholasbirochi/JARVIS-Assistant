import pytest
import pypdf

from indexing import extract


class FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


def _install_fake_pdf_reader(monkeypatch, pages_text: list[str | None]):
    class FakePdfReader:
        def __init__(self, path):
            self.pages = [FakePage(t) for t in pages_text]

    monkeypatch.setattr(pypdf, "PdfReader", FakePdfReader)


def test_extract_text_txt_and_md(tmp_path):
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("algumas notas", encoding="utf-8")
    md_path = tmp_path / "notes.md"
    md_path.write_text("# título\nconteúdo", encoding="utf-8")

    assert extract.extract_text(txt_path) == "algumas notas"
    assert "conteúdo" in extract.extract_text(md_path)


def test_extract_text_unsupported_extension_returns_none(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\x00\x01")
    assert extract.extract_text(path) is None


def test_extract_text_empty_file_returns_none(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    assert extract.extract_text(path) is None


def test_extract_text_pdf_with_text_layer(tmp_path, monkeypatch):
    path = tmp_path / "cert.pdf"
    path.write_bytes(b"%PDF-fake")
    _install_fake_pdf_reader(monkeypatch, ["conteúdo do certificado"])

    assert extract.extract_text(path) == "conteúdo do certificado"


def test_extract_text_pdf_without_text_layer_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "scanned.pdf"
    path.write_bytes(b"%PDF-fake")
    _install_fake_pdf_reader(monkeypatch, [None, None])

    assert extract.extract_text(path) is None


def test_extract_text_docx_reuses_docx_extract(tmp_path, monkeypatch):
    import resume.docx_extract as docx_extract

    path = tmp_path / "resume.docx"
    path.write_bytes(b"not a real docx")
    monkeypatch.setattr(docx_extract, "extract_text", lambda p: "conteúdo do docx")

    assert extract.extract_text(path) == "conteúdo do docx"


def test_extract_text_corrupt_docx_returns_none_instead_of_raising(tmp_path):
    path = tmp_path / "corrupt.docx"
    path.write_bytes(b"not a real docx at all")
    assert extract.extract_text(path) is None


def test_extract_text_propagates_oserror_instead_of_treating_as_no_text(tmp_path, monkeypatch):
    # A file that can't be *read at all* (e.g. a OneDrive online-only
    # placeholder timing out because the sync app isn't running) is a
    # different situation than "read fine, no text layer" -- the caller
    # needs to tell them apart to know whether to retry later or give up.
    # Swallowing this into a plain None would silently relabel a transient
    # I/O failure as "this file has no text", which is wrong and not
    # retried on a later run.
    path = tmp_path / "notes.txt"
    path.write_text("conteúdo", encoding="utf-8")

    from pathlib import Path as PathClass

    def failing_read_text(self, *args, **kwargs):
        raise TimeoutError(60, "Operation timed out")

    monkeypatch.setattr(PathClass, "read_text", failing_read_text)

    with pytest.raises(OSError):
        extract.extract_text(path)
