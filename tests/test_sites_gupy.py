import pytest

from jarvis.resume.schema import Bilingual, PersonalInfo, Resume
from jarvis.sites.base import SiteProfileSnapshot
from jarvis.sites.gupy import GupyAdapter, _map_resume_to_gupy_fields


def make_resume(**personal_info_overrides) -> Resume:
    defaults = {
        "full_name": "Nicholas Birochi",
        "phone": "+55 11 90000-0000",
        "email": "nicholas@example.com",
    }
    defaults.update(personal_info_overrides)
    return Resume(
        personal_info=PersonalInfo(**defaults),
        summary=Bilingual(pt="Resumo em português."),
    )


def test_map_resume_to_gupy_fields():
    resume = make_resume()

    fields = _map_resume_to_gupy_fields(resume)

    assert fields == {
        "full_name": "Nicholas Birochi",
        "phone": "+55 11 90000-0000",
        "email": "nicholas@example.com",
        "summary": "Resumo em português.",
    }


def test_build_update_plan_only_includes_differing_fields():
    resume = make_resume()
    current = SiteProfileSnapshot(
        site_name="gupy",
        fields={
            "full_name": "Nicholas Birochi",  # same -- no change needed
            "phone": "+55 11 99999-9999",  # different -- change needed
            "email": "nicholas@example.com",  # same
            "summary": "Resumo antigo.",  # different
        },
    )
    adapter = GupyAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.site_name == "gupy"
    changed_fields = {c.site_field for c in plan.changes}
    assert changed_fields == {"phone", "summary"}


def test_build_update_plan_empty_when_nothing_differs():
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields=_map_resume_to_gupy_fields(resume))
    adapter = GupyAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.changes == []


def test_build_update_plan_skips_fields_missing_locally():
    # phone is None locally -- don't propose overwriting Gupy's value with
    # nothing just because the local résumé hasn't got it filled in.
    resume = make_resume(phone=None)
    current = SiteProfileSnapshot(
        site_name="gupy",
        fields={**_map_resume_to_gupy_fields(resume), "phone": "+55 11 99999-9999"},
    )
    adapter = GupyAdapter()

    plan = adapter.build_update_plan(resume, current)

    assert plan.changes == []


def test_preview_changes_reports_no_changes():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields=_map_resume_to_gupy_fields(resume))
    plan = adapter.build_update_plan(resume, current)

    preview = adapter.preview_changes(plan)

    assert "Nenhuma mudança" in preview.summary_text


def test_preview_changes_lists_each_change():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields={"phone": "+55 11 99999-9999"})
    plan = adapter.build_update_plan(resume, current)

    preview = adapter.preview_changes(plan)

    assert "phone" in preview.summary_text
    assert "+55 11 90000-0000" in preview.summary_text  # the new value
    assert "personal_info.phone" in preview.summary_text  # traceable to the source


def test_apply_changes_refuses_without_confirmation():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields={"phone": "+55 11 99999-9999"})
    plan = adapter.build_update_plan(resume, current)

    result = adapter.apply_changes(plan, confirmed=False)

    assert result.applied is False
    assert "confirmed=True" in result.error


def test_apply_changes_succeeds_trivially_with_no_changes_even_if_confirmed():
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields=_map_resume_to_gupy_fields(resume))
    plan = adapter.build_update_plan(resume, current)

    result = adapter.apply_changes(plan, confirmed=True)

    assert result.applied is True
    assert result.changes_applied == []


def test_apply_changes_raises_not_implemented_for_real_submission():
    # The actual form-filling against Gupy's live DOM hasn't been verified
    # yet (see gupy.py's module docstring) -- must fail loudly, not
    # silently pretend to have submitted something.
    adapter = GupyAdapter()
    resume = make_resume()
    current = SiteProfileSnapshot(site_name="gupy", fields={"phone": "+55 11 99999-9999"})
    plan = adapter.build_update_plan(resume, current)

    with pytest.raises(NotImplementedError):
        adapter.apply_changes(plan, confirmed=True)


def test_inspect_current_profile_scrape_not_yet_implemented():
    adapter = GupyAdapter()
    with pytest.raises(NotImplementedError):
        adapter._scrape_profile_fields(page=None)
