import pytest

from jarvis.sites.base import (
    ChangePreview,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
    classify_question_field,
    detect_level,
    find_referral_contact,
    is_hard_pii_question,
    question_requires_stop,
)


def test_site_adapter_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        SiteAdapter()  # abstract methods unimplemented


def test_full_implementation_can_be_instantiated():
    class FakeAdapter(SiteAdapter):
        site_name = "fake"

        def check_session(self) -> SessionStatus:
            return SessionStatus.AUTHENTICATED

        def inspect_current_profile(self) -> SiteProfileSnapshot:
            return SiteProfileSnapshot(site_name="fake")

        def build_update_plan(self, resume, current) -> UpdatePlan:
            return UpdatePlan(site_name="fake")

        def preview_changes(self, plan) -> ChangePreview:
            return ChangePreview(site_name="fake", plan=plan, summary_text="")

        def apply_changes(self, plan, confirmed) -> UpdateResult:
            if not confirmed:
                return UpdateResult(site_name="fake", applied=False, error="not confirmed")
            return UpdateResult(site_name="fake", applied=True)

    adapter = FakeAdapter()
    assert adapter.check_session() == SessionStatus.AUTHENTICATED

    plan = adapter.build_update_plan(resume=None, current=adapter.inspect_current_profile())
    preview = adapter.preview_changes(plan)
    assert preview.site_name == "fake"

    refused = adapter.apply_changes(plan, confirmed=False)
    assert refused.applied is False

    applied = adapter.apply_changes(plan, confirmed=True)
    assert applied.applied is True


def test_question_requires_stop_true_for_the_real_itau_questions():
    # Real, confirmed live 2026-08-12: Itaú's own Gupy screening
    # questions asked for exactly these two things.
    assert question_requires_stop("Qual é o seu RG? (Informe somente números e letras)")
    assert question_requires_stop("Qual a sua remuneração atual?")


def test_question_requires_stop_true_for_other_pii_and_financial_terms():
    assert question_requires_stop("Informe seu CPF completo")
    assert question_requires_stop("Qual sua pretensão salarial?")
    assert question_requires_stop("Qual sua data de nascimento?")
    assert question_requires_stop("Qual seu estado civil?")


def test_question_requires_stop_false_for_an_unrelated_question():
    assert not question_requires_stop("Você tem disponibilidade para trabalho híbrido?")
    assert not question_requires_stop("Você já trabalhou com Python antes?")


def test_question_requires_stop_case_insensitive():
    assert question_requires_stop("QUAL O SEU RG?")
    assert question_requires_stop("qual sua remuneração?")


def test_is_hard_pii_question_true_only_for_government_id_and_birth_date():
    # Real, confirmed live 2026-08-13: BIP Brasil's own "pretensão
    # salarial" question is sensitive but NOT a government-ID question --
    # it must be classified differently from Itaú's real RG question.
    assert is_hard_pii_question("Qual é o seu RG?")
    assert is_hard_pii_question("Informe seu CPF completo")
    assert is_hard_pii_question("Qual sua data de nascimento?")
    assert not is_hard_pii_question("Qual sua pretensão salarial atual?")
    assert not is_hard_pii_question("Qual seu estado civil?")


def test_is_hard_pii_question_false_for_an_unrelated_question():
    assert not is_hard_pii_question("Você tem disponibilidade para trabalho híbrido?")


def test_classify_question_field_recognizes_each_known_field():
    assert classify_question_field("Qual é o seu RG?") == "rg"
    assert classify_question_field("Informe seu CPF completo") == "cpf"
    assert classify_question_field("Qual sua pretensão salarial atual?") == "salary_expectation"
    assert classify_question_field("Qual seu estado civil?") == "marital_status"


def test_classify_question_field_none_for_birth_date_and_unrelated_questions():
    # Birth date is recognized as a hard stop (is_hard_pii_question),
    # but deliberately has no fillable field at all -- see base.py's
    # module comment for why.
    # (2026-08-21: this test previously used "disponibilidade para
    # viajar" as its example of an unrelated question -- it became a
    # real, classified field the same day, which would have silently
    # flipped this assertion. Using a genuinely subjective/unclassified
    # question instead so a future field addition can't do that again.)
    assert classify_question_field("Qual sua data de nascimento?") is None
    assert classify_question_field("Como você avalia seu nível de inglês?") is None


def test_is_hard_pii_question_true_for_birth_date_with_no_fillable_field():
    assert is_hard_pii_question("Qual sua data de nascimento?")
    assert classify_question_field("Qual sua data de nascimento?") is None


def test_classify_question_field_recognizes_the_new_identity_fields():
    # 2026-08-17, real Gupy screenshot from Nicholas.
    assert classify_question_field("Órgão e Estado de emissão do RG") == "rg_orgao_estado"
    assert classify_question_field("Nome da mãe") == "nome_mae"
    assert classify_question_field("Nome do pai") == "nome_pai"
    assert classify_question_field("Naturalidade (cidade e estado de nascimento)") == "naturalidade"


def test_classify_question_field_recognizes_the_recurring_generic_fields():
    # 2026-08-21: compiled from real company-question text seen live
    # across several listings, per Nicholas's explicit request ("me
    # mande as perguntas mais genéricas e que sempre aparecem").
    assert classify_question_field("Por favor, compartilhe com a gente o link do seu LinkedIn:") == "linkedin"
    assert classify_question_field("Você tem CNH?") == "cnh"
    assert classify_question_field("Você é ex-colaborador? (exceto estagiários)") == "ja_trabalhou_aqui"
    assert classify_question_field("Você já trabalhou nesta empresa?") == "ja_trabalhou_aqui"
    # Real miss found live (Cogna): "do grupo" phrasing is the same
    # question, worded differently.
    assert classify_question_field("Já trabalhou em alguma empresa do grupo?") == "ja_trabalhou_aqui"
    assert classify_question_field("Você tem disponibilidade para viajar?") == "disponibilidade_viagem"
    assert (
        classify_question_field("Em casos pontuais, você possui disponibilidade para trabalhar aos sábados?")
        == "disponibilidade_fds"
    )
    assert classify_question_field("Você possui ensino superior completo?") == "escolaridade"
    assert classify_question_field("Possui graduação completa ou em andamento na área de TI?") == "escolaridade"


def test_classify_question_field_recognizes_round_2_of_the_recurring_generic_fields():
    # 2026-08-21, round 2 -- found live during the one-at-a-time apply
    # batch (FGC/PagSeguro/Stefanini).
    assert (
        classify_question_field("Possui disponibilidade para início imediato, caso seja aprovado?")
        == "disponibilidade_inicio_imediato"
    )
    assert classify_question_field("Qual é o seu cargo atual?") == "cargo_atual"
    assert (
        classify_question_field(
            "Possui parentes que trabalham ou estejam em fase de seleção ou admissão na empresa?"
        )
        == "parentes_na_empresa"
    )
    assert (
        classify_question_field("Informe o semestre e o ano previstos para a conclusão do curso")
        == "semestre_formatura"
    )


def test_classify_question_field_distinguishes_rg_orgao_estado_from_bare_rg():
    # Real risk: "Órgão e Estado de emissão do RG" contains "RG" as its
    # own whole word too -- checking bare "rg" first would misclassify
    # this and try to fill the RG NUMBER selector with an issuing-
    # authority value.
    assert classify_question_field("Órgão e Estado de emissão do RG") == "rg_orgao_estado"
    assert classify_question_field("Qual é o seu RG?") == "rg"


def test_new_identity_fields_are_hard_pii():
    assert is_hard_pii_question("Órgão e Estado de emissão do RG")
    assert is_hard_pii_question("Nome da mãe")
    assert is_hard_pii_question("Nome do pai")
    assert is_hard_pii_question("Naturalidade")


def test_detect_level_recognizes_estagio():
    assert detect_level("Estágio em Análise de Dados") == "estagio"
    assert detect_level("Estagiário de BI") == "estagio"


def test_detect_level_recognizes_pleno_including_the_abbreviation():
    # Real listing found live 2026-08-17: "Engenheiro de Dados Pl."
    # reached the apply flow despite job_matching.py's senior-exclusion
    # only checking the spelled-out "pleno".
    assert detect_level("Analista de Dados Pleno") == "pleno"
    assert detect_level("Engenheiro de Dados Pl.") == "pleno"


def test_detect_level_defaults_to_junior():
    assert detect_level("Analista de Dados Júnior") == "junior"
    assert detect_level("Analista de Dados") == "junior"


def test_detect_level_does_not_false_positive_on_unrelated_words():
    # "pl" as a bare substring inside other words must not trigger.
    assert detect_level("Desenvolvedor de Aplicativo") == "junior"
    assert detect_level("Analista de Exemplo") == "junior"


def test_find_referral_contact_matches_a_known_company():
    # Real bug caught live: the unaccented key "itau" must still match the
    # real, accented "Itaú Unibanco" company name from Gupy's own gate
    # text -- "itaú" and "itau" aren't the same substring at all, so this
    # requires the accent-stripping in find_referral_contact, not just
    # whole-word matching.
    contacts = {"itau": {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}}

    assert find_referral_contact("Itaú Unibanco", contacts) == contacts["itau"]


def test_find_referral_contact_none_for_an_unknown_company():
    contacts = {"itau": {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}}

    assert find_referral_contact("Empresa Qualquer", contacts) is None


def test_find_referral_contact_none_for_missing_company_or_empty_contacts():
    assert find_referral_contact(None, {"itau": {}}) is None
    assert find_referral_contact("Itaú", {}) is None


def test_find_referral_contact_whole_word_match_not_bare_substring():
    # "xp" as a short key -- must not false-positive on unrelated words
    # that happen to contain "xp" as a substring.
    contacts = {"xp": {"name": "Rafael Tavares Lima", "email": "rafael.tavares@xpi.com.br"}}

    assert find_referral_contact("Expresso Logística", contacts) is None
    assert find_referral_contact("XP Investimentos", contacts) == contacts["xp"]
