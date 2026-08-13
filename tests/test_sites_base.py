import pytest

from jarvis.sites.base import (
    ChangePreview,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
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
