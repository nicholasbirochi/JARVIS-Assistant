from jarvis.resume.schema import Bilingual, JobPreferences, PersonalInfo, Resume
from jarvis.sites.base import JobListing
from jarvis.sites.job_matching import (
    company_tier,
    dedupe,
    derive_search_terms,
    filter_by_location,
    filter_relevant,
    filter_remote,
    group_by_tier,
    has_international_signal,
    has_junior_signal,
    is_affirmative_action_only,
    is_full_remote,
    is_in_target_region,
    is_relevant_match,
    is_remote,
    rank_bank_bigtech_first,
    rank_junior_first,
)


def make_resume(**job_preferences_overrides) -> Resume:
    return Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi", phone=None, email="n@example.com"),
        summary=Bilingual(pt="Resumo."),
        job_preferences=JobPreferences(**job_preferences_overrides),
    )


def test_derive_search_terms_prefers_explicit_target_roles():
    resume = make_resume(target_roles=["Cientista de Dados"])

    assert derive_search_terms(resume) == ["Cientista de Dados"]


def test_derive_search_terms_falls_back_to_data_analyst_defaults():
    resume = make_resume()  # target_roles empty by default

    terms = derive_search_terms(resume)

    assert "Analista de Dados" in terms
    assert len(terms) >= 1


def test_is_relevant_match_true_for_real_data_role():
    assert is_relevant_match("Analista De Dados - Comercial", "Trabalhe com Python e SQL", ["Analista de Dados"])


def test_is_relevant_match_false_for_unrelated_role_matched_only_on_a_common_word():
    # The real bug found live on InfoJobs: searching "Analista de Dados
    # Júnior" returned "Analista Financeiro Junior" -- matches "Analista"
    # and "Junior" but has nothing to do with data.
    assert not is_relevant_match("Analista Financeiro Junior", "Contas a pagar", ["Analista de Dados"])


def test_is_relevant_match_false_for_senior_roles():
    assert not is_relevant_match("Analista De Dados Pleno", "5 anos de experiência", ["Analista de Dados"])
    assert not is_relevant_match("Analista De Dados SR (Python e SQL)", None, ["Analista de Dados"])
    assert not is_relevant_match("Coordenador De Business Intelligence", None, ["Business Intelligence"])


def test_is_affirmative_action_only_true_for_real_exclusive_listings():
    # Real listings found live, 2026-08-19.
    assert is_affirmative_action_only(
        "Sênior Analista Negocios - Growth - Vaga Afirmativa para Pessoa com Deficiência (PCD)"
    )
    assert is_affirmative_action_only("Advogado Consultivo e Contratos Sênior (Afirmativa para Pessoas Negras)")
    assert is_affirmative_action_only(
        "Engenharia de Software Backend Java/Python Pleno | Exclusiva para Pessoas com deficiência"
    )
    assert is_affirmative_action_only("Analista Administrativo | Campinas -SP ( Vaga Exclusiva PCD )")


def test_is_affirmative_action_only_false_for_a_merely_inclusive_listing():
    # Real, confirmed-live distinction: "também" (also/inclusive) means
    # the role is open to everyone, PCD candidates included -- not an
    # exclusive quota posting. Must NOT be excluded.
    assert not is_affirmative_action_only("Tech Lead | Engenharia de Software", "Vaga também para PcD")
    assert not is_affirmative_action_only("Analista de Dados Júnior", None)


def test_is_affirmative_action_only_true_for_lgbtqia_and_women_exclusive_listings():
    # 2026-08-19: "sem vagas PCD ou LGBTQI+ e demais minorias... sou
    # branco padrão" -- widened past PCD/race to cover these too.
    assert is_affirmative_action_only("Analista de Dados Pleno - Exclusiva para LGBTQIA+")
    assert is_affirmative_action_only("Analista Jurídico - Vaga Afirmativa para Mulheres")
    assert is_affirmative_action_only("Estágio em Dados - Cota Feminina")


def test_is_affirmative_action_only_true_for_the_real_banco_bv_talent_bank_phrasing():
    # Real listings found live 2026-08-19 (Banco BV, during the
    # Rochaverá lookup) -- a distinct exclusive phrasing from "vaga
    # afirmativa"/"exclusiva", not assumed to be the only one companies
    # use.
    assert is_affirmative_action_only("BV com Elas: banco de candidatura para mulheres")
    assert is_affirmative_action_only("BV fora do armário: banco de candidatura para LGBTQIAP+")
    assert is_affirmative_action_only("BV Além da Cota: banco de candidatura para PcD")
    assert is_affirmative_action_only("BV Raízes: banco de candidatura para pessoas negras")


def test_is_relevant_match_false_for_affirmative_action_exclusive_listings():
    assert not is_relevant_match(
        "Analista de Dados Júnior - Vaga Afirmativa para Pessoa com Deficiência (PCD)",
        None,
        ["Analista de Dados"],
    )


def test_is_relevant_match_true_for_a_merely_inclusive_listing():
    assert is_relevant_match("Analista de Dados Júnior", "Vaga também para PcD", ["Analista de Dados"])


def test_is_relevant_match_short_acronym_keyword_does_not_false_positive_on_substring():
    # The real bug found live: "bi" (from "Power BI") as a bare substring
    # matched inside ordinary words like "recebimento".
    assert not is_relevant_match("Assistente De Recebimento", "Conferência de mercadorias", ["Power BI"])
    assert is_relevant_match("Analista De Power BI", "Dashboards e relatórios", ["Power BI"])


def make_listing(external_id: str, title: str, snippet: str | None = None, site_name: str = "infojobs") -> JobListing:
    return JobListing(
        site_name=site_name,
        external_id=external_id,
        title=title,
        company="Empresa",
        location="São Paulo - SP",
        url=f"https://example.com/{external_id}",
        snippet=snippet,
    )


def test_filter_relevant_keeps_only_matching_listings():
    listings = [
        make_listing("1", "Analista De Dados"),
        make_listing("2", "Analista Financeiro Junior"),
    ]

    result = filter_relevant(listings, ["Analista de Dados"])

    assert [listing.external_id for listing in result] == ["1"]


def test_dedupe_keeps_first_occurrence_per_site_and_id():
    listings = [
        make_listing("1", "Analista De Dados"),
        make_listing("1", "Analista De Dados (duplicado por outra busca)"),
        make_listing("2", "Analista De BI"),
    ]

    result = dedupe(listings)

    assert [listing.external_id for listing in result] == ["1", "2"]


def test_has_junior_signal_true_for_explicit_level_words():
    assert has_junior_signal("Analista De Dados Júnior", None)
    assert has_junior_signal("Analista De Dados Jr", None)
    assert has_junior_signal("Estagiário De BI", None)
    assert has_junior_signal("Programa Trainee 2026", None)


def test_has_junior_signal_false_when_level_is_unstated():
    assert not has_junior_signal("Analista De Dados", "Trabalhe com Python e SQL")


def test_is_in_target_region_true_for_home_city_and_abc_neighbors():
    assert is_in_target_region("São Bernardo do Campo - SP")
    assert is_in_target_region("Santo André - SP")
    assert is_in_target_region("São Caetano do Sul - SP")
    assert is_in_target_region("Diadema - SP")
    assert is_in_target_region("São Paulo - SP")


def test_is_in_target_region_true_for_osasco_and_cajamar():
    # Narrow, explicit exception added 2026-08-13: real bigtech listings
    # (Amazon) kept showing up in these two specifically, and the user
    # confirmed he wants them counted as "perto de você" -- unlike
    # Guarulhos/Barueri/Jundiaí, which stay excluded (see the module's
    # own docstring for the reasoning).
    assert is_in_target_region("Osasco, SP")
    assert is_in_target_region("Cajamar, SP, BRA")


def test_is_in_target_region_false_for_the_state_suffix_alone():
    # The real risk: every location string ends in "- SP" (the state
    # abbreviation), which must never itself count as a match -- only the
    # city name "São Paulo" should.
    assert not is_in_target_region("Piracicaba - SP")
    assert not is_in_target_region("Guarulhos - SP")
    assert not is_in_target_region("Jundiaí - SP")


def test_is_in_target_region_false_for_missing_location():
    assert not is_in_target_region(None)
    assert not is_in_target_region("")


def test_filter_by_location_keeps_only_nearby_listings():
    listings = [
        make_listing("1", "Analista De Dados"),  # location defaults to São Paulo - SP in make_listing
        make_listing("2", "Analista De BI", site_name="catho"),
    ]
    listings[1].location = "Piracicaba - SP"

    result = filter_by_location(listings)

    assert [listing.external_id for listing in result] == ["1"]


def test_is_remote_true_for_common_phrasings():
    assert is_remote("Analista de Dados", "100% Remoto, home office", None)
    assert is_remote("Work From Home Business Intelligence", None, None)
    assert is_remote("Analista de Dados", None, "Remoto")


def test_is_remote_false_without_a_remote_signal():
    assert not is_remote("Analista de Dados", "Presencial, São Paulo", "São Paulo - SP")


def test_has_international_signal_true_for_foreign_currency_or_framing():
    assert has_international_signal("Analista de Dados", "Salário em USD, cliente internacional")
    assert has_international_signal("Data Analyst", "Global team, worldwide clients")


def test_has_international_signal_false_for_a_plain_local_listing():
    assert not has_international_signal("Analista de Dados", "Salário R$ 4.000, CLT")


def test_filter_remote_keeps_only_remote_listings():
    listings = [
        make_listing("1", "Analista De Dados", snippet="100% remoto"),
        make_listing("2", "Analista De BI", snippet="Presencial"),
    ]

    result = filter_remote(listings)

    assert [listing.external_id for listing in result] == ["1"]


def test_is_full_remote_false_when_also_hybrid():
    # Real request, 2026-08-14: a listing mentioning "remoto" AND
    # "híbrido" isn't the full home-office role Nicholas wants -- mixed/
    # inconsistent listing text seen live shouldn't count.
    assert not is_full_remote("Analista de Dados", "Remoto, modelo híbrido 2x/semana", None)
    assert not is_full_remote("Data Analyst", "Hybrid remote role", None)


def test_is_full_remote_true_for_a_genuinely_remote_listing():
    assert is_full_remote("Analista de Dados", "100% remoto, trabalhe de qualquer lugar do Brasil", None)


def test_is_full_remote_false_without_any_remote_signal():
    assert not is_full_remote("Analista de Dados", "Presencial", "São Paulo - SP")


def test_filter_remote_excludes_hybrid_listings():
    listings = [
        make_listing("1", "Analista De Dados", snippet="100% remoto"),
        make_listing("2", "Analista De BI", snippet="Remoto, mas híbrido 1x por semana"),
    ]

    result = filter_remote(listings)

    assert [listing.external_id for listing in result] == ["1"]


def test_rank_junior_first_moves_explicit_junior_signals_to_the_front():
    listings = [
        make_listing("1", "Analista De Dados"),  # unspecified level
        make_listing("2", "Analista De Dados Júnior"),
        make_listing("3", "Analista De BI"),  # unspecified level
        make_listing("4", "Estagiário De Dados"),
    ]

    result = rank_junior_first(listings)

    assert [listing.external_id for listing in result] == ["2", "4", "1", "3"]


def test_company_tier_recognizes_known_banks_case_insensitively():
    assert company_tier("Itaú Unibanco") == "banco"
    assert company_tier("BRADESCO") == "banco"
    assert company_tier("Banrisul") == "banco"


def test_company_tier_recognizes_known_fintechs():
    # Split out from _BANK_COMPANIES 2026-08-17 at the user's explicit
    # request ("quero Fin techs também agora!") -- digital-native
    # financial-tech companies, a real, distinct category from a
    # traditional full-license bank like Itaú/Bradesco.
    assert company_tier("Nubank") == "fintech"
    assert company_tier("C6 Bank") == "fintech"
    assert company_tier("Cora") == "fintech"
    # Stone moved here from _BIGTECH_COMPANIES -- it's a payments
    # fintech, not a general tech platform; being publicly traded (the
    # original reason it sat with TOTVS/VTEX) doesn't make it "bigtech"
    # any more than Nubank's own public listing would.
    assert company_tier("Stone Pagamentos") == "fintech"


def test_company_tier_recognizes_known_bigtechs():
    assert company_tier("Google Brasil") == "bigtech"
    assert company_tier("iFood") == "bigtech"
    # 2026-08-19, "cade o google? IBM?" -- both were already listed;
    # widened the list anyway (see job_matching.py's note) with, among
    # others, the two tools literally named in the résumé's own
    # target_roles/skills.
    assert company_tier("Databricks") == "bigtech"
    assert company_tier("Snowflake") == "bigtech"


def test_company_tier_recognizes_the_2026_08_19_expansion():
    # One spot-check per tier for that round's expansion ("MELHORE AINDA
    # MAISSSSS! TEM MUITO POUCAS OPÇÕES DE EMPRESAS").
    assert company_tier("Banco BV") == "banco"
    assert company_tier("QI Tech") == "fintech"
    assert company_tier("Mottu") == "startup"


def test_company_tier_recognizes_the_round_3_bank_and_fintech_expansion():
    # 2026-08-19, round 3 ("foque bastante em colocar bancos!! e
    # fintechs!!!").
    assert company_tier("Banco Master") == "banco"
    assert company_tier("ING Bank N.V.") == "banco"
    assert company_tier("Meliuz") == "fintech"
    assert company_tier("Mercado Bitcoin") == "fintech"


def test_company_tier_does_not_false_positive_on_bare_ing_substring():
    # Real risk this project has already been bitten by once (see
    # _matches_known_name's docstring): "ing" as a bare 3-letter
    # fragment appears inside ordinary words like "banking"/"training".
    # "ing bank" (multi-word) is safe; bare "ing" was deliberately never
    # added.
    assert company_tier("Training Corp Consultoria") is None
    assert company_tier("Banking Solutions LTDA") is None


def test_company_tier_recognizes_companies_found_in_that_days_real_results():
    # Round 2, same day: found by actually inspecting the "outras"
    # bucket's real company names that the first widening pass still
    # missed, not guessed.
    assert company_tier("XP Inc.") == "fintech"
    assert company_tier("Infosys") == "bigtech"
    assert company_tier("Tata Consultancy Services") == "bigtech"
    # "vem pra vivo" (Vivo's own recruiting campaign brand) sidesteps
    # the false-positive risk of matching bare "vivo" (an ordinary
    # Portuguese word) directly.
    assert company_tier("Vem Pra Vivo") == "bigtech"
    assert company_tier("Apenas Vivo Mesmo") is None


def test_company_tier_none_for_an_unrecognized_or_missing_company():
    assert company_tier("Empresa Qualquer Ltda") is None
    assert company_tier(None) is None


def test_company_tier_recognizes_known_startups():
    assert company_tier("Gupy") == "startup"
    assert company_tier("Semantix Tecnologia") == "startup"
    assert company_tier("BAIRESDEV") == "startup"


def test_company_tier_none_for_an_unrecognized_named_company():
    # Real limitation, not a bug: a genuine company that just isn't in
    # the curated list comes back None, same as any other unrecognized
    # name -- there's no company-size database here to check against,
    # only the four named lists. (2026-08-19: this test previously used
    # "Housi" as its example of an unlisted company -- it got added to
    # _STARTUP_COMPANIES the same day, which silently flipped this
    # test's assertion. Using an obviously fictional name instead so a
    # future list expansion can't do that again.)
    assert company_tier("Empresa Fictícia Qualquer LTDA") is None


def test_company_tier_does_not_false_positive_on_a_bare_substring():
    # Real bugs found live, 2026-08-12: "CADERNO INTELIGENTE" matched
    # _BIGTECH_COMPANIES's "intel" as a substring of "INTELIGENTE", and
    # "REDE ANCORA" matched _STARTUP_COMPANIES's "cora" (the fintech Cora)
    # as a substring of "ANCORA" -- neither is related to the real
    # company. Both must come back None now that matching is whole-word.
    assert company_tier("CADERNO INTELIGENTE") is None
    assert company_tier("REDE ANCORA") is None


def test_rank_bank_bigtech_first_orders_banco_then_fintech_then_bigtech_then_startup_then_rest():
    listings = [make_listing(str(i), "X") for i in range(1, 6)]
    listings[0].company = "Empresa Qualquer"
    listings[1].company = "Google"
    listings[2].company = "Itaú"
    listings[3].company = "Gupy"
    listings[4].company = "Nubank"

    result = rank_bank_bigtech_first(listings)

    assert [listing.external_id for listing in result] == ["3", "5", "2", "4", "1"]


def test_group_by_tier_buckets_and_drops_unrecognized_companies():
    unranked = make_listing("1", "X")
    unranked.company = "Empresa Qualquer"
    bigtech = make_listing("2", "X")
    bigtech.company = "Google"
    bank = make_listing("3", "X")
    bank.company = "Itaú"
    startup = make_listing("4", "X")
    startup.company = "Gupy"
    fintech = make_listing("5", "X")
    fintech.company = "Nubank"

    buckets = group_by_tier([unranked, bigtech, bank, startup, fintech])

    assert {l.external_id for l in buckets["banco"]} == {"3"}
    assert {l.external_id for l in buckets["bigtech"]} == {"2"}
    assert {l.external_id for l in buckets["startup"]} == {"4"}
    assert {l.external_id for l in buckets["fintech"]} == {"5"}
    assert set(buckets.keys()) == {"banco", "fintech", "bigtech", "startup"}


def test_group_by_tier_include_other_keeps_unrecognized_companies():
    # Added 2026-08-17: the named-tier lists alone are gated by real
    # market openings at ~100 curated companies -- include_other=True
    # surfaces every OTHER relevant listing instead of silently
    # dropping it, for when real volume matters more than curation.
    known = make_listing("1", "X")
    known.company = "Itaú"
    unknown = make_listing("2", "X")
    unknown.company = "Empresa Qualquer Ltda"
    no_company = make_listing("3", "X")
    no_company.company = None

    buckets = group_by_tier([known, unknown, no_company], include_other=True)

    assert {l.external_id for l in buckets["banco"]} == {"1"}
    assert {l.external_id for l in buckets["outras"]} == {"2", "3"}


def test_group_by_tier_default_still_drops_unrecognized_companies():
    unknown = make_listing("1", "X")
    unknown.company = "Empresa Qualquer Ltda"

    buckets = group_by_tier([unknown])

    assert "outras" not in buckets
    assert all(len(v) == 0 for v in buckets.values())


def test_group_by_tier_ranks_junior_first_within_each_bucket():
    unlabeled = make_listing("1", "Analista De Dados")
    unlabeled.company = "Itaú"
    junior = make_listing("2", "Analista De Dados Júnior")
    junior.company = "Bradesco"

    buckets = group_by_tier([unlabeled, junior])

    assert [l.external_id for l in buckets["banco"]] == ["2", "1"]
