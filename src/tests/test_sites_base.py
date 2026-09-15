import pytest

from sites.base import (
    ChangePreview,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
    apply_resume_backed_profile_fields,
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
    # (2026-09-14: same thing happened again -- "Como você avalia seu
    # nível de inglês?" became classified as "ingles_nivel" the same day
    # this comment first warned about it. Switched to a question about a
    # completely different, still-genuinely-unclassified subjective
    # trait so this canary keeps doing its job.)
    assert classify_question_field("Qual sua data de nascimento?") is None
    assert classify_question_field("Como você avalia sua capacidade de trabalhar em equipe?") is None


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


def test_classify_question_field_recognizes_round_3_found_live_at_vivo():
    assert (
        classify_question_field("Você tem parente(s) (cônjuges ou pessoa análoga, pai, mãe, avós, filhos) na Vivo?")
        == "parentes_na_empresa"
    )
    assert (
        classify_question_field("Informe seu nome completo, sem abreviações e conforme documento oficial.")
        == "nome_completo"
    )


def test_classify_question_field_recognizes_the_parentesco_followup_found_live_at_pagbank():
    # 2026-08-22, real gap found live (PagBank): a conditional follow-up
    # to "parentes_na_empresa", asking for the actual name/degree of
    # kinship -- distinct field, since it's skipped (not filled) when
    # the parent answer is "Não" -- see gupy.py's _CONDITIONAL_SKIP_FIELDS.
    assert classify_question_field("Qual nome e grau de parentesco?") == "parentes_nome_grau"
    # Must not collide with the parent question's own classification.
    assert (
        classify_question_field("Possui parentes que trabalham ou estejam em fase de seleção na empresa?")
        == "parentes_na_empresa"
    )


def test_classify_question_field_recognizes_hibrido_availability_found_live():
    # 2026-08-27, real gap found live (Núclea/Stefanini): hybrid/
    # in-person work arrangement -- two real phrasings, distinct from
    # disponibilidade_viagem (travel) and disponibilidade_fds (weekends).
    assert (
        classify_question_field("Possui disponibilidade para atuar em modelo híbrido (presencial 2x por semana) em São Paulo - SP?")
        == "disponibilidade_hibrido"
    )
    assert (
        classify_question_field("Aceita trabalhar no modelo hibrido, sendo 3 x semana em Osasco - SP?")
        == "disponibilidade_hibrido"
    )


def test_classify_question_field_pcd_no_longer_false_positives_on_mere_mentions():
    # 2026-08-27, real bug found live (Stefanini): a referral-institution
    # radio-group question ("Você chegou até esta oportunidade por meio
    # de alguma instituição... (PcD ou não PcD)?") was misclassified as
    # "pcd" purely because it mentions the abbreviation parenthetically
    # -- nothing to do with disability status. The code then believed
    # it had answered a radio group with Nicholas's real pcd="Não"
    # value without ever actually testing whether it could be filled
    # (_fill_company_answer() can't fill a radio group either way, but
    # the preview text claimed success). A genuine PCD question still
    # matches via the full phrase.
    assert classify_question_field("Você é uma pessoa com deficiência (PcD)?") == "pcd"
    assert (
        classify_question_field(
            "Você chegou até esta oportunidade por meio de alguma instituição, parceiro ou "
            "comunidade de inclusão e empregabilidade (PcD ou não PcD)?"
        )
        is None
    )


def test_classify_question_field_recognizes_round_4_found_live_in_the_gupy_batch_apply_run():
    # 2026-09-07: "nome DA SUA mãe"/"nome DO SEU pai" don't contain
    # "nome da mãe"/"nome do pai" as substrings -- the inserted
    # "sua"/"seu" broke the old match entirely.
    assert classify_question_field("Informe o nome da sua mãe:") == "nome_mae"
    assert classify_question_field("Informe o nome do seu pai:") == "nome_pai"
    # "cidade e estado de nascimento" -- same naturalidade question,
    # never mentions the word "naturalidade" at all.
    assert classify_question_field("Qual é a sua cidade e estado de nascimento?") == "naturalidade"
    # "familiar ou parente que atualmente trabalha" -- same nepotism-
    # disclosure question as parentes_na_empresa's other phrasings.
    assert (
        classify_question_field(
            "Você possui algum familiar ou parente que atualmente trabalha em alguma empresa da AI/R Company?"
        )
        == "parentes_na_empresa"
    )
    # "expectativa salarial" -- same salary question as "pretensão
    # salarial", never mentions "salário"/"pretensão" as whole words.
    assert classify_question_field("Qual sua expectativa salarial (para o modelo CLT)?") == "salary_expectation"
    # "atuou" instead of "trabalhou" -- same ja_trabalhou_aqui question.
    assert classify_question_field("Você já atuou em alguma empresa do Grupo?") == "ja_trabalhou_aqui"


def test_classify_question_field_recognizes_the_telemont_uniform_questions():
    # 2026-09-07, found live across 4 real TELEMONT postings in the same
    # batch-apply run -- a physical-uniform question pair. "numeração"
    # turned out to be a letter-size radio group (PP/P/M/G/GG), not shoe
    # size -- confirmed live and renamed from "numeracao_calcado".
    assert classify_question_field("Em caso de utilização de uniforme, informe sua altura:") == "altura"
    assert (
        classify_question_field("Em caso de utilização de uniforme, informe qual a numeração:")
        == "tamanho_uniforme"
    )


def test_classify_question_field_recognizes_the_telemont_cnh_categoria_radio():
    # 2026-09-07, found live (TELEMONT): a SEPARATE radio-only follow-up
    # asking just for the CNH category letter, distinct from the
    # ordinary free-text "cnh" question (which holds the full "Sim,
    # categoria B" sentence -- the wrong shape for a bare-letter radio).
    assert classify_question_field("Possui CNH? Se SIM, informe a categoria.") == "cnh_categoria"
    # A plain CNH question elsewhere must still classify as "cnh", not
    # "cnh_categoria" -- the more specific term only wins when its own
    # exact phrase is present.
    assert classify_question_field("Você possui CNH?") == "cnh"


def test_classify_question_field_distinguishes_current_from_desired_salary():
    # 2026-09-07, real classification bug found live (InfoJobs, "Monitor
    # De Qualidade Jr E Pl" and others): "Qual foi seu último salário?"
    # asks for a CURRENT/PAST fact, not the desired figure -- the old
    # code answered it with the DESIRED salary (salary_junior etc.), a
    # real, factually wrong answer sent to a real employer.
    assert classify_question_field("Qual foi seu último salário?") == "salary_current"
    assert classify_question_field("Qual sua última remuneração?") == "salary_current"
    assert classify_question_field("Qual sua remuneração atual?") == "salary_current"
    # The ordinary desired-salary phrasing must still classify as
    # "salary_expectation", not get swallowed by the new, more specific
    # field.
    assert classify_question_field("Qual sua pretensão salarial?") == "salary_expectation"


def test_classify_question_field_distinguishes_rg_orgao_estado_from_bare_rg():
    # Real risk: "Órgão e Estado de emissão do RG" contains "RG" as its
    # own whole word too -- checking bare "rg" first would misclassify
    # this and try to fill the RG NUMBER selector with an issuing-
    # authority value.
    assert classify_question_field("Órgão e Estado de emissão do RG") == "rg_orgao_estado"
    assert classify_question_field("Qual é o seu RG?") == "rg"


def test_classify_question_field_recognizes_the_2026_09_14_infojobs_batch_fields():
    # 2026-09-14: compiled after Nicholas had a separate Claude instance
    # (with access to his OneDrive résumé) answer a batch of real,
    # live-blocked InfoJobs questions -- all of these were genuine
    # classification gaps (the question appeared for real, but had no
    # field to resolve it to at all).
    assert classify_question_field("Informe seu numero de whatsapp") == "telefone"
    assert classify_question_field("Nosso primeiro contato será via whatsapp.") == "telefone"
    assert classify_question_field("Qual o nome do seu curso superior atual?") == "curso_nome"
    assert classify_question_field("Qual o nível do seu conhecimento em Inglês?") == "ingles_nivel"
    assert classify_question_field("Você possui inglês em nível intermediário ou superior?") == "ingles_nivel"
    assert classify_question_field("Link do seu portfólio ou projetos de referência") == "portfolio_link"
    assert classify_question_field("Qual seu nível de conhecimento em Excel?") == "excel_nivel"
    assert classify_question_field("Possui Excel avançado?") == "excel_nivel"
    assert classify_question_field("Você tem conhecimentos em SQL?") == "sql_nivel"
    assert classify_question_field("Possui conhecimento avançado em Power Bi e Power Automate?") == "powerbi_nivel"
    assert classify_question_field("Possui Graduação Completa?") == "graduacao_completa"
    # Same batch: a bare "Nome completo" with no "sem abreviações"
    # qualifier at all -- distinct from the existing, more specific
    # phrasing test at test_classify_question_field_recognizes_round_3_found_live_at_vivo.
    assert classify_question_field("Nome completo") == "nome_completo"
    # The longer-form escolaridade phrasing must keep winning over the
    # new, more generic "graduação completa" term when it's the one
    # that's actually present (dict order matters here).
    assert (
        classify_question_field("Possui graduação completa ou em andamento?") == "escolaridade"
    )
    # Same real miss as the semestre_formatura comment above -- worded
    # without "previsão de formatura" at all.
    assert (
        classify_question_field("Qual o seu semestre atual e a previsão de conclusão acadêmica (mês/ano)?")
        == "semestre_formatura"
    )


def test_apply_resume_backed_profile_fields_fills_only_missing_fields_from_the_resume():
    from resume.schema import (
        Availability,
        Bilingual,
        Education,
        JobPreferences,
        LanguageSkill,
        Links,
        PersonalInfo,
        Resume,
    )

    resume = Resume(
        personal_info=PersonalInfo(
            full_name="Nicholas Birochi",
            phone="+55 (11) 95827-5250",
            links=Links(
                linkedin="https://www.linkedin.com/in/nicholasbirochi/",
                github="https://github.com/nicholasbirochi/",
                portfolio="https://app.rocketseat.com.br/me/nicholasbirochi/",
            ),
        ),
        summary=Bilingual(pt="Resumo."),
        education=[
            Education(
                degree=Bilingual(pt="Engenharia da Computação"),
                institution="Faculdade Engenheiro Salvador Arena",
                status="in_progress",
            )
        ],
        languages=[LanguageSkill(name="English", proficiency="Upper-Intermediate (B2 First - Score 153)")],
        job_preferences=JobPreferences(availability=Availability(status="immediate")),
    )

    profile: dict[str, str | None] = {
        "linkedin": None,
        "nome_completo": None,
        "disponibilidade_inicio_imediato": None,
        "telefone": None,
        "curso_nome": None,
        "ingles_nivel": None,
        "portfolio_link": None,
        "graduacao_completa": None,
        "semestre_formatura": "8º semestre, formatura prevista para dezembro de 2027",
    }
    apply_resume_backed_profile_fields(profile, resume)

    assert profile["linkedin"] == "https://www.linkedin.com/in/nicholasbirochi/"
    assert profile["nome_completo"] == "Nicholas Birochi"
    assert profile["disponibilidade_inicio_imediato"] == "Sim"
    assert profile["telefone"] == "+55 (11) 95827-5250"
    assert profile["curso_nome"] == (
        "Engenharia da Computação (Faculdade Engenheiro Salvador Arena) -- "
        "8º semestre, formatura prevista para dezembro de 2027"
    )
    assert profile["ingles_nivel"] == "Sim. Intermediário-avançado (B2 First - Score 153)"
    assert profile["portfolio_link"] == "https://app.rocketseat.com.br/me/nicholasbirochi/"
    assert profile["graduacao_completa"] == "Não -- 8º semestre, formatura prevista para dezembro de 2027"


def test_apply_resume_backed_profile_fields_never_overwrites_a_real_env_value():
    # A field Nicholas already set explicitly in application_profile.env
    # must never be silently replaced by a résumé-derived guess.
    from resume.schema import Bilingual, Links, PersonalInfo, Resume

    resume = Resume(
        personal_info=PersonalInfo(
            full_name="Nicholas Birochi",
            links=Links(linkedin="https://www.linkedin.com/in/nicholasbirochi/"),
        ),
        summary=Bilingual(pt="Resumo."),
    )
    profile: dict[str, str | None] = {"linkedin": "https://www.linkedin.com/in/ja-preenchido/"}
    apply_resume_backed_profile_fields(profile, resume)

    assert profile["linkedin"] == "https://www.linkedin.com/in/ja-preenchido/"


def test_apply_resume_backed_profile_fields_leaves_graduacao_completa_unset_without_education():
    from resume.schema import Bilingual, PersonalInfo, Resume

    resume = Resume(personal_info=PersonalInfo(full_name="Nicholas Birochi"), summary=Bilingual(pt="Resumo."))
    profile: dict[str, str | None] = {"graduacao_completa": None}
    apply_resume_backed_profile_fields(profile, resume)

    assert profile["graduacao_completa"] is None


def test_classify_question_field_recognizes_the_2026_09_14_chatgpt_drafted_batch():
    # 2026-09-14: Nicholas had a separate assistant (web access to his
    # public LinkedIn, cross-checked against his résumé) draft real,
    # honest answers -- including real negatives -- for a batch of real,
    # live-blocked InfoJobs listings. Every one of these was a genuine
    # classification gap (the question appeared for real, no field
    # matched it at all).
    assert classify_question_field("Tem disponibilidade para estagiar das 09h00 às 16h00?") == "disponibilidade_estagio_09_16"
    assert (
        classify_question_field("Tem conhecimento em estatística e matemática financeira? Comente.")
        == "estatistica_matematica_financeira"
    )
    assert classify_question_field("Já atuou na área de call center?") == "call_center_experiencia"
    assert classify_question_field("Possui experiência com Power Query e DAX?") == "power_query_dax"
    assert classify_question_field("Possui experiência com Power Automate?") == "power_automate_nivel"
    assert classify_question_field("Você possuo conhecimento em Google Planilhas avançado?") == "google_sheets_nivel"
    assert classify_question_field("Você possui experiência prévia com Inteligência Artificial (IA)?") == "ia_experiencia"
    assert (
        classify_question_field("Como você utiliza ferramentas de IA no seu dia a dia profissional?")
        == "ia_experiencia"
    )
    assert classify_question_field("Possui vivência ou conhecimento de trâmites da SUSEP?") == "susep_conhecimento"
    assert classify_question_field("Possui conhecimento e vivência com arquivos TXT, CSV ou similares?") == "txt_csv_conhecimento"
    assert (
        classify_question_field("Você possui experiência com análise de KPIs comerciais, dashboards e indicadores de vendas?")
        == "kpis_comerciais_experiencia"
    )
    assert classify_question_field("Possui disponibilidade para atuar em contrato temporário?") == "disponibilidade_temporario"
    assert classify_question_field("Possui interesse em vaga temporária 180 dias?") == "disponibilidade_temporario"
    assert classify_question_field("Quais ferramentas de análise você domina?") == "ferramentas_analise_dominadas"
    assert classify_question_field("Quais ferramentas de visualização você domina?") == "ferramentas_visualizacao_dominadas"
    assert classify_question_field("Como você constrói seus relatórios e dashboards?") == "como_constroi_dashboards"
    assert (
        classify_question_field("Me conta sobre um resultado real que você gerou com dados.") == "resultado_real_dados"
    )
    assert classify_question_field("Qual é o seu diferencial como analista de dados?") == "diferencial_analista"
    assert classify_question_field("Possui experiência com as atividades da vaga? Comente.") == "atividades_vaga_experiencia"
    assert classify_question_field("Quantas ferramentas ETL você utilizou em projetos de BI?") == "etl_ferramentas_experiencia"
    assert (
        classify_question_field("Possui conhecimento prático ou teórico com Python ou DBT?") == "python_dbt_conhecimento"
    )
    assert (
        classify_question_field("Você possui experiência prática com contas a pagar, contas a receber?")
        == "contas_pagar_receber"
    )
    assert (
        classify_question_field("Qual alternativa melhor representa sua experiência com DRE e relatórios financeiros gerenciais?")
        == "dre_relatorios_financeiros"
    )
    assert (
        classify_question_field("Qual alternativa melhor representa sua experiência com tecnologia aplicada à área financeira?")
        == "tecnologia_area_financeira"
    )
    assert classify_question_field("Você tem experiência em análise de dados financeiros?") == "analise_dados_financeiros"
    assert classify_question_field("Quantos anos de experiencia voce tem com Marketing Mix Modeling (MMM)") == "mmm_experiencia"
    assert (
        classify_question_field("Você possui experiência em Inteligência de Mercado, Planejamento Comercial?")
        == "inteligencia_mercado_experiencia"
    )
    assert classify_question_field("Já trabalhou com indicadores de desempenho, market share?") == "market_share_indicadores"
    assert (
        classify_question_field("Você possui experiência na elaboração de relatórios gerenciais e apresentações executivas?")
        == "relatorios_executivos_experiencia"
    )
    assert classify_question_field("Você já utilizou CRM em sua rotina profissional?") == "crm_experiencia"
    assert classify_question_field("Possui conhecimento em Looker e Google Apps Script?") == "looker_apps_script"
    assert (
        classify_question_field("Possui experiência com Python ou outras linguagens de programação aplicadas à análise de dados?")
        == "python_dados_nivel"
    )
    assert (
        classify_question_field("Cite um exemplo de melhoria contínua que você implementou ou sugeriu com base em dados.")
        == "melhoria_continua_exemplo"
    )
    assert (
        classify_question_field("Você possui graduação em Engenharia, Economia, Administração, Ciências Exatas, Dados?")
        == "graduacao_area_tecnica"
    )
    assert classify_question_field("Possui Graduação em áreas de exatas, computação e correlatas?") == "graduacao_area_tecnica"
    assert classify_question_field("Concluiu seu mestrado?") == "mestrado_concluido"
    # Résumé-backed extensions to already-existing fields (no new .env
    # key needed -- see apply_resume_backed_profile_fields()).
    assert classify_question_field("Está trabalhando no momento?") == "cargo_atual"
    assert classify_question_field("Qual a sua formação acadêmica?") == "curso_nome"
    assert classify_question_field("Qual a sua titulação (nome do curso, nível e mês e ano de conclusão)?") == "curso_nome"
    assert (
        classify_question_field("Comente sobre sua experiência com indicadores e análises gerenciais.")
        == "indicadores_experiencia"
    )
    # The generic catch-all must stay LAST -- a more specific field
    # covering the exact same real listing's OWN question keeps winning.
    assert classify_question_field("Nos conte a respeito da sua experiência") == "conte_sua_experiencia"
    assert classify_question_field("Comente brevemente suas experiência na área.") == "conte_sua_experiencia"


def test_classify_question_field_recognizes_round_2_of_the_chatgpt_drafted_batch():
    # 2026-09-14, found offline-checking which of the 25 remaining
    # blocked InfoJobs listings the first batch actually unblocked --
    # several real phrasing variants slipped through the first pass.
    assert (
        classify_question_field("Já estruturou indicadores desde a coleta até o dashboard?")
        == "indicadores_experiencia"
    )
    assert (
        classify_question_field("Já atuou com automação ou digitalização de processos? Descreva.")
        == "projeto_automacao_digitalizacao"
    )
    assert classify_question_field("Inglês avançado ?") == "ingles_nivel"
    # "Power B.I" (a literal dot between B and I) doesn't contain the
    # bare "power bi" substring.
    assert classify_question_field("Possui vivência com análise e validação de dados em Power B.I?") == "powerbi_nivel"
    assert (
        classify_question_field(
            "Você possui experiência profissional com análise de dados em empresas de tecnologia, "
            "consultorias, recursos humanos, varejo, finanças ou segmentos similares?"
        )
        == "experiencia_setores_diversos"
    )
    assert (
        classify_question_field("Você ou algum familiar próximo é considerado Pessoa Politicamente Exposta (PEP)?")
        == "pep_status"
    )
    # A parenthetical relationship-degree list breaks the two existing
    # parentes_na_empresa phrasings -- this fragment survives it.
    assert (
        classify_question_field(
            "Você possui parentesco (cônjuge, pais, filhos, irmãos) com algum colaborador atual da Ânima Educação?"
        )
        == "parentes_na_empresa"
    )
    assert (
        classify_question_field(
            "Você possui vínculo comercial com empresa que seja fornecedora, cliente, concorrente ou "
            "parceira da Ânima Educação?"
        )
        == "anima_vinculo_comercial"
    )
    assert (
        classify_question_field("Você já foi colaborador(a) CLT da Ânima Educação nos últimos 5 anos?")
        == "anima_clt_historico"
    )
    # The two Ânima-specific fields must stay scoped to Ânima's own real
    # phrasing -- a differently-worded, unrelated company's conflict-of-
    # interest question must not accidentally reuse Ânima-specific
    # answer content.
    assert classify_question_field("Possui vínculo comercial com algum cliente ou fornecedor da empresa?") is None
    assert (
        classify_question_field("Comente sua experiência com automação de processos e dados?")
        == "projeto_automacao_digitalizacao"
    )
    assert classify_question_field("Possui vivência com construção de dashboards?") == "como_constroi_dashboards"


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
