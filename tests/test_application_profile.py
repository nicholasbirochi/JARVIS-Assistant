from jarvis import config
from jarvis.sites.application_profile import (
    ensure_profile_template,
    load_application_profile,
    profile_path,
)


def test_profile_path_lives_under_local_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert profile_path() == tmp_path / "application_profile.env"


def test_load_application_profile_returns_all_none_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    profile = load_application_profile()

    assert profile == {"rg": None, "cpf": None, "salary_expectation": None, "marital_status": None}


def test_load_application_profile_reads_real_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text(
        "\n".join(
            [
                "# comentário deve ser ignorado",
                "",
                "JARVIS_APPLICATION_RG=12.345.678-9",
                "JARVIS_APPLICATION_CPF=123.456.789-00",
                "JARVIS_APPLICATION_SALARY_EXPECTATION=R$ 4.500,00",
                "JARVIS_APPLICATION_MARITAL_STATUS=Solteiro",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_application_profile()

    assert profile == {
        "rg": "12.345.678-9",
        "cpf": "123.456.789-00",
        "salary_expectation": "R$ 4.500,00",
        "marital_status": "Solteiro",
    }


def test_load_application_profile_treats_blank_value_as_none(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("JARVIS_APPLICATION_RG=\n", encoding="utf-8")

    profile = load_application_profile()

    assert profile["rg"] is None


def test_load_application_profile_ignores_unknown_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("SOME_OTHER_KEY=valor\n", encoding="utf-8")

    profile = load_application_profile()

    assert all(v is None for v in profile.values())


def test_ensure_profile_template_creates_a_real_editable_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    path = ensure_profile_template()

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "JARVIS_APPLICATION_RG=" in content
    assert "JARVIS_APPLICATION_CPF=" in content
    assert "JARVIS_APPLICATION_SALARY_EXPECTATION=" in content
    assert "JARVIS_APPLICATION_MARITAL_STATUS=" in content


def test_ensure_profile_template_never_overwrites_existing_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("JARVIS_APPLICATION_RG=12.345.678-9\n", encoding="utf-8")

    ensure_profile_template()

    content = (tmp_path / "application_profile.env").read_text(encoding="utf-8")
    assert "12.345.678-9" in content
