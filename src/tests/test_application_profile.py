import json

import config
from sites.application_profile import (
    ensure_profile_template,
    load_application_profile,
    load_referral_contacts,
    profile_path,
    referral_contacts_path,
)


def test_profile_path_lives_under_local_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert profile_path() == tmp_path / "application_profile.env"


def test_load_application_profile_returns_all_none_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    profile = load_application_profile()

    assert profile == {
        "rg": None,
        "rg_orgao_estado": None,
        "cpf": None,
        "nome_mae": None,
        "nome_pai": None,
        "naturalidade": None,
        "raca_cor": None,
        "pcd": None,
        "salary_estagio": None,
        "salary_junior": None,
        "salary_pleno": None,
        "marital_status": None,
        "cargo_atual": None,
        "parentes_na_empresa": None,
        "semestre_formatura": None,
        "cnh": None,
        "cnh_categoria": None,
        "disponibilidade_viagem": None,
        "disponibilidade_fds": None,
        "disponibilidade_hibrido": None,
        "escolaridade": None,
        "altura": None,
        "tamanho_uniforme": None,
    }


def test_load_application_profile_reads_real_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text(
        "\n".join(
            [
                "# comentário deve ser ignorado",
                "",
                "JARVIS_APPLICATION_RG=12.345.678-9",
                "JARVIS_APPLICATION_RG_ORGAO_ESTADO=SSP-SP",
                "JARVIS_APPLICATION_CPF=123.456.789-00",
                "JARVIS_APPLICATION_NOME_MAE=Maria da Silva",
                "JARVIS_APPLICATION_NOME_PAI=João da Silva",
                "JARVIS_APPLICATION_NATURALIDADE=São Paulo - SP",
                "JARVIS_APPLICATION_RACA_COR=Branco",
                "JARVIS_APPLICATION_PCD=Não",
                "JARVIS_APPLICATION_SALARY_ESTAGIO=R$ 3.000,00",
                "JARVIS_APPLICATION_SALARY_JUNIOR=R$ 4.500,00",
                "JARVIS_APPLICATION_SALARY_PLENO=R$ 6.500,00",
                "JARVIS_APPLICATION_MARITAL_STATUS=Solteiro",
                "JARVIS_APPLICATION_CNH=Sim, categoria B",
                "JARVIS_APPLICATION_CNH_CATEGORIA=B",
                "JARVIS_APPLICATION_DISPONIBILIDADE_VIAGEM=Sim",
                "JARVIS_APPLICATION_DISPONIBILIDADE_FDS=Não",
                "JARVIS_APPLICATION_DISPONIBILIDADE_HIBRIDO=Sim",
                "JARVIS_APPLICATION_ESCOLARIDADE=Ensino superior incompleto (cursando)",
                "JARVIS_APPLICATION_CARGO_ATUAL=Não estou empregado no momento",
                "JARVIS_APPLICATION_PARENTES_NA_EMPRESA=Não",
                "JARVIS_APPLICATION_SEMESTRE_FORMATURA=2º semestre de 2027",
                "JARVIS_APPLICATION_ALTURA=1,75 m",
                "JARVIS_APPLICATION_TAMANHO_UNIFORME=G",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_application_profile()

    assert profile == {
        "rg": "12.345.678-9",
        "rg_orgao_estado": "SSP-SP",
        "cpf": "123.456.789-00",
        "nome_mae": "Maria da Silva",
        "nome_pai": "João da Silva",
        "naturalidade": "São Paulo - SP",
        "raca_cor": "Branco",
        "pcd": "Não",
        "salary_estagio": "R$ 3.000,00",
        "salary_junior": "R$ 4.500,00",
        "salary_pleno": "R$ 6.500,00",
        "marital_status": "Solteiro",
        "cnh": "Sim, categoria B",
        "cnh_categoria": "B",
        "disponibilidade_viagem": "Sim",
        "disponibilidade_fds": "Não",
        "disponibilidade_hibrido": "Sim",
        "escolaridade": "Ensino superior incompleto (cursando)",
        "cargo_atual": "Não estou empregado no momento",
        "parentes_na_empresa": "Não",
        "semestre_formatura": "2º semestre de 2027",
        "altura": "1,75 m",
        "tamanho_uniforme": "G",
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
    assert "JARVIS_APPLICATION_RG_ORGAO_ESTADO=" in content
    assert "JARVIS_APPLICATION_CPF=" in content
    assert "JARVIS_APPLICATION_NOME_MAE=" in content
    assert "JARVIS_APPLICATION_NOME_PAI=" in content
    assert "JARVIS_APPLICATION_NATURALIDADE=" in content
    assert "JARVIS_APPLICATION_SALARY_ESTAGIO=" in content
    assert "JARVIS_APPLICATION_SALARY_JUNIOR=" in content
    assert "JARVIS_APPLICATION_SALARY_PLENO=" in content
    assert "JARVIS_APPLICATION_MARITAL_STATUS=" in content


def test_ensure_profile_template_never_overwrites_existing_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("JARVIS_APPLICATION_RG=12.345.678-9\n", encoding="utf-8")

    ensure_profile_template()

    content = (tmp_path / "application_profile.env").read_text(encoding="utf-8")
    assert "12.345.678-9" in content


def test_referral_contacts_path_lives_under_local_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert referral_contacts_path() == tmp_path / "referral_contacts.json"


def test_load_referral_contacts_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert load_referral_contacts() == {}


def test_load_referral_contacts_reads_real_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    data = {"itau": {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}}
    (tmp_path / "referral_contacts.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert load_referral_contacts() == data


def test_load_referral_contacts_returns_empty_on_malformed_json(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "referral_contacts.json").write_text("not valid json{{{", encoding="utf-8")

    assert load_referral_contacts() == {}
