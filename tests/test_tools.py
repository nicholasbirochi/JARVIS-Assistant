import json

import pytest

from jarvis.assistant import tools
from jarvis.resume import store
from jarvis.resume.schema import Bilingual, PersonalInfo, Resume


@pytest.fixture
def seeded_resume_path(tmp_path, monkeypatch):
    path = tmp_path / "resume.json"
    resume = Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi", phone="+55 11 90000-0000"),
        summary=Bilingual(pt="Resumo.", en="Summary."),
    )
    monkeypatch.setattr(store, "RESUME_PATH", path)
    monkeypatch.setattr(store, "BACKUPS_DIR", tmp_path / "backups")
    store.save(resume)
    return path


def test_read_resume_returns_json(seeded_resume_path):
    result = json.loads(tools.read_resume())
    assert result["personal_info"]["full_name"] == "Nicholas Birochi"


def test_update_resume_field_persists_change(seeded_resume_path):
    message = tools.update_resume_field("personal_info.phone", "+55 11 91111-1111")
    assert "atualizado" in message.lower()

    reloaded = store.load()
    assert reloaded.personal_info.phone == "+55 11 91111-1111"


def test_update_resume_field_bad_path_reports_error_without_raising(seeded_resume_path):
    message = tools.update_resume_field("campo.que.nao.existe", "valor")
    assert "erro" in message.lower()


def test_list_supported_sites_includes_linkedin():
    result = tools.list_supported_sites()
    assert "LinkedIn" in result


def test_push_resume_to_site_unsupported_site():
    result = tools.push_resume_to_site("SiteInventado")
    assert "não está na lista" in result.lower() or "nao esta na lista" in result.lower()


def test_push_resume_to_site_supported_site_says_not_implemented():
    result = tools.push_resume_to_site("LinkedIn")
    assert "não foi implementada" in result.lower() or "nao foi implementada" in result.lower()


# ---- prepare_claude_prompt ----


def test_prepare_claude_prompt_copies_to_clipboard(monkeypatch):
    calls = []
    monkeypatch.setattr(tools.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    monkeypatch.setattr(tools, "_log_claude_prompt", lambda prompt: None)

    result = tools.prepare_claude_prompt("Troque a cor do HUD para verde.")

    assert calls[0][0] == ["pbcopy"]
    assert calls[0][1]["input"] == "Troque a cor do HUD para verde.".encode("utf-8")
    assert "copiado" in result.lower()


def test_prepare_claude_prompt_reports_error_without_raising_when_pbcopy_fails(monkeypatch):
    def raising_run(args, **kw):
        raise OSError("pbcopy indisponível")

    monkeypatch.setattr(tools.subprocess, "run", raising_run)

    result = tools.prepare_claude_prompt("qualquer coisa")

    assert "não consegui" in result.lower()


def test_prepare_claude_prompt_logs_even_though_it_still_reports_clipboard_success(monkeypatch, tmp_path):
    from jarvis import config

    monkeypatch.setattr(tools.subprocess, "run", lambda args, **kw: None)
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    result = tools.prepare_claude_prompt("Adicione um botão novo.")

    log_path = tmp_path / "claude_prompts.log"
    assert log_path.exists()
    assert "Adicione um botão novo." in log_path.read_text(encoding="utf-8")
    assert "copiado" in result.lower()


def test_prepare_claude_prompt_still_succeeds_if_logging_itself_fails(monkeypatch, tmp_path):
    # The clipboard copy is the actual guarantee the user asked for -- a
    # logging hiccup (durability net only) must never turn that into a
    # reported failure. Real failure mode, not a mock: LOCAL_STATE_DIR
    # pointed at a path that's a file, not a directory, so mkdir(parents=True)
    # inside _log_claude_prompt raises for real.
    from jarvis import config

    monkeypatch.setattr(tools.subprocess, "run", lambda args, **kw: None)
    not_a_directory = tmp_path / "not_a_directory"
    not_a_directory.write_text("")
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", not_a_directory)

    result = tools.prepare_claude_prompt("qualquer coisa")

    assert "copiado" in result.lower()
