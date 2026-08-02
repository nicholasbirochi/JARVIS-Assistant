import pytest

from jarvis.sites.base import (
    ChangePreview,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
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
