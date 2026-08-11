from jarvis.resume.schema import Bilingual, JobPreferences, PersonalInfo, Resume
from jarvis.sites.base import JobListing
from jarvis.sites.job_matching import (
    dedupe,
    derive_search_terms,
    filter_by_location,
    filter_relevant,
    has_junior_signal,
    is_in_target_region,
    is_relevant_match,
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


def test_rank_junior_first_moves_explicit_junior_signals_to_the_front():
    listings = [
        make_listing("1", "Analista De Dados"),  # unspecified level
        make_listing("2", "Analista De Dados Júnior"),
        make_listing("3", "Analista De BI"),  # unspecified level
        make_listing("4", "Estagiário De Dados"),
    ]

    result = rank_junior_first(listings)

    assert [listing.external_id for listing in result] == ["2", "4", "1", "3"]
