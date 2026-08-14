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
    assert company_tier("Nubank") == "banco"


def test_company_tier_recognizes_known_bigtechs():
    assert company_tier("Google Brasil") == "bigtech"
    assert company_tier("iFood") == "bigtech"


def test_company_tier_none_for_an_unrecognized_or_missing_company():
    assert company_tier("Empresa Qualquer Ltda") is None
    assert company_tier(None) is None


def test_company_tier_recognizes_known_startups():
    assert company_tier("Gupy") == "startup"
    assert company_tier("Semantix Tecnologia") == "startup"
    assert company_tier("BAIRESDEV") == "startup"


def test_company_tier_none_for_an_unrecognized_named_company():
    # Real limitation, not a bug: a genuine, real startup that just isn't
    # in the curated list (e.g. "Housi") comes back None, same as any
    # other unrecognized name -- there's no company-size database here to
    # check against, only the three named lists.
    assert company_tier("Housi") is None


def test_company_tier_does_not_false_positive_on_a_bare_substring():
    # Real bugs found live, 2026-08-12: "CADERNO INTELIGENTE" matched
    # _BIGTECH_COMPANIES's "intel" as a substring of "INTELIGENTE", and
    # "REDE ANCORA" matched _STARTUP_COMPANIES's "cora" (the fintech Cora)
    # as a substring of "ANCORA" -- neither is related to the real
    # company. Both must come back None now that matching is whole-word.
    assert company_tier("CADERNO INTELIGENTE") is None
    assert company_tier("REDE ANCORA") is None


def test_rank_bank_bigtech_first_orders_banco_then_bigtech_then_startup_then_rest():
    listings = [make_listing(str(i), "X") for i in range(1, 5)]
    listings[0].company = "Empresa Qualquer"
    listings[1].company = "Google"
    listings[2].company = "Itaú"
    listings[3].company = "Gupy"

    result = rank_bank_bigtech_first(listings)

    assert [listing.external_id for listing in result] == ["3", "2", "4", "1"]


def test_group_by_tier_buckets_and_drops_unrecognized_companies():
    unranked = make_listing("1", "X")
    unranked.company = "Empresa Qualquer"
    bigtech = make_listing("2", "X")
    bigtech.company = "Google"
    bank = make_listing("3", "X")
    bank.company = "Itaú"
    startup = make_listing("4", "X")
    startup.company = "Gupy"

    buckets = group_by_tier([unranked, bigtech, bank, startup])

    assert {l.external_id for l in buckets["banco"]} == {"3"}
    assert {l.external_id for l in buckets["bigtech"]} == {"2"}
    assert {l.external_id for l in buckets["startup"]} == {"4"}
    assert set(buckets.keys()) == {"banco", "bigtech", "startup"}


def test_group_by_tier_ranks_junior_first_within_each_bucket():
    unlabeled = make_listing("1", "Analista De Dados")
    unlabeled.company = "Itaú"
    junior = make_listing("2", "Analista De Dados Júnior")
    junior.company = "Bradesco"

    buckets = group_by_tier([unlabeled, junior])

    assert [l.external_id for l in buckets["banco"]] == ["2", "1"]
