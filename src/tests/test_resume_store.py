import pytest
from pydantic import ValidationError

from resume import store
from resume.schema import Bilingual, Conflict, Experience, PersonalInfo, Resume


def make_resume() -> Resume:
    return Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi"),
        summary=Bilingual(pt="Resumo em português.", en="Summary in English."),
        experience=[
            Experience(
                id="exp-volkswagen-2025",
                title=Bilingual(pt="Estagiário", en="Intern"),
                company="Volkswagen",
                is_current=True,
                bullets_pt=["Analisou dados de vendas."],
            )
        ],
    )


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "resume.json"
    resume = make_resume()

    store.save(resume, path=path)
    loaded = store.load(path=path)

    assert loaded.personal_info.full_name == "Nicholas Birochi"
    assert loaded.experience[0].company == "Volkswagen"
    assert loaded.meta.last_updated is not None


def test_save_creates_backup_on_second_write(tmp_path, monkeypatch):
    backups_dir = tmp_path / "backups"
    monkeypatch.setattr(store, "BACKUPS_DIR", backups_dir)

    path = tmp_path / "resume.json"
    resume = make_resume()

    store.save(resume, path=path)
    assert not backups_dir.exists()  # no prior file to back up yet

    store.save(resume, path=path)
    backups = list(backups_dir.glob("resume.*.json"))
    assert len(backups) == 1


def test_get_field_simple_and_nested_path():
    resume = make_resume()
    assert store.get_field(resume, "personal_info.full_name") == "Nicholas Birochi"
    assert store.get_field(resume, "experience.0.company") == "Volkswagen"
    assert store.get_field(resume, "experience.0.title.pt") == "Estagiário"


def test_get_field_bad_path_raises():
    resume = make_resume()
    with pytest.raises(store.FieldPathError):
        store.get_field(resume, "experience.99.company")
    with pytest.raises(store.FieldPathError):
        store.get_field(resume, "not_a_real_field")


def test_update_field_returns_new_validated_resume():
    resume = make_resume()
    updated = store.update_field(resume, "personal_info.phone", "+55 11 90000-0000")

    assert updated.personal_info.phone == "+55 11 90000-0000"
    assert resume.personal_info.phone is None  # original untouched


def test_update_field_list_index():
    resume = make_resume()
    updated = store.update_field(resume, "experience.0.is_current", False)
    assert updated.experience[0].is_current is False


def test_update_field_invalid_value_raises():
    resume = make_resume()
    with pytest.raises(ValidationError):
        store.update_field(resume, "experience.0.is_current", "not-a-bool-and-not-parseable")


def test_update_field_records_change_log_entry():
    resume = make_resume()
    updated = store.update_field(
        resume, "personal_info.phone", "+55 11 90000-0000", source="voice", note="pediu por voz"
    )

    assert len(updated.change_log) == 1
    record = updated.change_log[0]
    assert record.field_path == "personal_info.phone"
    assert record.old_value is None
    assert record.new_value == "+55 11 90000-0000"
    assert record.source == "voice"
    assert record.note == "pediu por voz"
    assert resume.change_log == []  # original untouched


def test_append_item_adds_new_certification_and_change_record():
    resume = make_resume()
    item = {"name": "Curso X", "status": "completed"}

    updated = store.append_item(resume, "certifications", item, source="proposal_review")

    assert len(updated.certifications) == 1
    assert updated.certifications[0].name == "Curso X"
    assert len(updated.change_log) == 1
    assert updated.change_log[0].field_path == "certifications.0"
    assert updated.change_log[0].source == "proposal_review"
    assert resume.certifications == []  # original untouched


def test_append_item_rejects_non_list_path():
    resume = make_resume()
    with pytest.raises(store.FieldPathError):
        store.append_item(resume, "personal_info", {"x": 1})


def test_register_conflict_appends_to_conflicts_list():
    resume = make_resume()
    conflict = Conflict(
        id="c1",
        field_path="personal_info.phone",
        existing_value="A",
        proposed_value="B",
        detected_at="2026-01-01T00:00:00Z",
    )

    updated = store.register_conflict(resume, conflict)

    assert len(updated.conflicts) == 1
    assert updated.conflicts[0].id == "c1"
    assert resume.conflicts == []  # original untouched
