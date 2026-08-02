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
