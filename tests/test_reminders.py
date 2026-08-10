import pytest

from jarvis import config, reminders


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)


def test_list_reminders_empty_when_none_added():
    assert reminders.list_reminders() == []


def test_add_reminder_returns_entry_with_text_and_timestamp():
    entry = reminders.add_reminder("Ligar para o dentista.")

    assert entry["text"] == "Ligar para o dentista."
    assert "created_at" in entry


def test_add_reminder_persists_and_is_listed_back():
    reminders.add_reminder("Primeiro lembrete.")
    reminders.add_reminder("Segundo lembrete.")

    items = reminders.list_reminders()

    assert [r["text"] for r in items] == ["Primeiro lembrete.", "Segundo lembrete."]


def test_list_reminders_survives_a_corrupt_file():
    path = config.DATA_DIR / "reminders.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")

    assert reminders.list_reminders() == []


def test_add_reminder_survives_and_overwrites_a_corrupt_file():
    path = config.DATA_DIR / "reminders.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")

    reminders.add_reminder("Novo lembrete depois de um arquivo corrompido.")

    assert [r["text"] for r in reminders.list_reminders()] == [
        "Novo lembrete depois de um arquivo corrompido."
    ]
