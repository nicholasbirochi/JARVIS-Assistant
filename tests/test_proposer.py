from pathlib import Path

from jarvis.indexing import proposer
from jarvis.indexing.proposals import LLMProposalBatch, LLMProposedChange
from jarvis.resume.schema import Bilingual, Certification, PersonalInfo, Resume


def make_resume() -> Resume:
    return Resume(
        personal_info=PersonalInfo(full_name="Nicholas Birochi", phone="+55 11 90000-0000"),
        summary=Bilingual(pt="Resumo."),
    )


def test_attach_evidence_detects_conflict_on_differing_value(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                value="+55 11 99999-9999",
                quote="telefone: (11) 99999-9999",
                confidence=0.8,
            )
        ]
    )
    path = tmp_path / "cert.pdf"
    text = "Contato -- telefone: (11) 99999-9999"

    changes = proposer.attach_evidence(batch, path, text, resume)

    assert len(changes) == 1
    assert changes[0].conflict is True
    assert changes[0].existing_value == "+55 11 90000-0000"
    assert changes[0].evidence[0].confidence == 0.8
    assert changes[0].evidence[0].snippet == "telefone: (11) 99999-9999"


def test_attach_evidence_no_conflict_when_value_matches(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                value="+55 11 90000-0000",
                quote="+55 11 90000-0000",
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "+55 11 90000-0000", resume)

    assert changes[0].conflict is False


def test_attach_evidence_drops_change_without_a_quote(tmp_path):
    # The model returning a value with no supporting quote at all is exactly
    # the failure mode observed in practice: a real fact from a *different*
    # file leaking into an unrelated document's proposal, at full
    # confidence, with nothing in this document backing it up.
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[LLMProposedChange(kind="update_field", field_path="personal_info.phone", value="+55 11 99999-9999")]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "documento sem nada relevante", resume)

    assert changes == []


def test_attach_evidence_drops_change_whose_quote_is_not_in_the_document(tmp_path):
    # A quote that doesn't literally appear in the source text can't be a
    # real excerpt from it -- the model fabricated or misattributed it.
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field",
                field_path="personal_info.phone",
                value="+55 11 99999-9999",
                quote="telefone: (11) 99999-9999",
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "este documento fala de outra coisa", resume)

    assert changes == []


def test_attach_evidence_drops_change_with_unresolvable_field_path(tmp_path):
    # A field path that doesn't resolve at all (hallucinated by the model)
    # can never be applied -- drop it instead of surfacing it for the human
    # to reject by hand.
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(kind="update_field", field_path="not.a.real.path", value="x", quote="algo")
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "documento com algo escrito", resume)

    assert changes == []


def test_attach_evidence_drops_update_with_wrong_shape_for_field(tmp_path):
    # certifications.N.hours expects a number -- a value that can't coerce
    # into one (garbage/placeholder text from the model) must not reach
    # the human reviewer as if it were a real proposal.
    resume = make_resume()
    resume.certifications.append(Certification(name="Python", hours=10))
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field",
                field_path="certifications.0.hours",
                value="Some value here",
                quote="algum trecho",
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "documento com algum trecho relevante", resume)

    assert changes == []


def test_attach_evidence_drops_new_item_missing_required_field(tmp_path):
    # Certification.name is required -- an item missing it can never
    # actually be appended, so don't propose it.
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="new_item", list_field="certifications", item={"hours": 5}, quote="5 horas"
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "curso com carga de 5 horas", resume)

    assert changes == []


def test_attach_evidence_new_item_embeds_evidence_in_proposed_value(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="new_item",
                list_field="certifications",
                item={"name": "Curso X", "status": "completed"},
                quote="Certificado do Curso X",
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "cert.pdf", "Certificado do Curso X, concluído.", resume)

    assert changes[0].proposed_value["name"] == "Curso X"
    assert len(changes[0].proposed_value["evidence"]) == 1
    assert changes[0].conflict is False


def test_attach_evidence_coerces_json_string_value_to_real_type(tmp_path):
    resume = make_resume()
    batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field", field_path="experience", value="[]", quote="nenhuma experiência"
            )
        ]
    )

    changes = proposer.attach_evidence(batch, tmp_path / "x.docx", "nenhuma experiência registrada", resume)

    assert changes[0].proposed_value == []


def test_attach_evidence_normalizes_bracket_notation_field_path(tmp_path):
    resume = make_resume()
    resume.certifications.append(Certification(name="Python", hours=5))
    bracket_batch = LLMProposalBatch(
        changes=[
            LLMProposedChange(
                kind="update_field", field_path="certifications[0].hours", value="10", quote="10 horas"
            )
        ]
    )

    changes = proposer.attach_evidence(bracket_batch, tmp_path / "x.docx", "curso de 10 horas", resume)

    assert changes[0].field_path == "certifications.0.hours"


def test_dedupe_update_field_changes_merges_identical_proposals(tmp_path):
    # Same fact (personal_info.phone -> the same new number), proposed
    # independently from two different résumé file variants.
    resume = make_resume()
    from_file_a = proposer.attach_evidence(
        LLMProposalBatch(
            changes=[
                LLMProposedChange(
                    kind="update_field",
                    field_path="personal_info.phone",
                    value="+55 11 91111-1111",
                    quote="+55 11 91111-1111",
                )
            ]
        ),
        tmp_path / "brasil.docx",
        "contato: +55 11 91111-1111",
        resume,
    )
    from_file_b = proposer.attach_evidence(
        LLMProposalBatch(
            changes=[
                LLMProposedChange(
                    kind="update_field",
                    field_path="personal_info.phone",
                    value="+55 11 91111-1111",
                    quote="+55 11 91111-1111",
                )
            ]
        ),
        tmp_path / "international.docx",
        "phone: +55 11 91111-1111",
        resume,
    )

    merged = proposer.dedupe_update_field_changes(from_file_a + from_file_b)

    assert len(merged) == 1
    assert len(merged[0].evidence) == 2
    sources = {e.source_path for e in merged[0].evidence}
    assert sources == {
        str(tmp_path / "brasil.docx"),
        str(tmp_path / "international.docx"),
    }


def test_dedupe_update_field_changes_keeps_different_values_separate(tmp_path):
    resume = make_resume()
    resume.certifications.append(Certification(name="Python", hours=10))
    changes = proposer.attach_evidence(
        LLMProposalBatch(
            changes=[
                LLMProposedChange(
                    kind="update_field", field_path="certifications.0.hours", value="12", quote="12 horas"
                ),
                LLMProposedChange(
                    kind="update_field", field_path="certifications.0.hours", value="15", quote="15 horas"
                ),
            ]
        ),
        tmp_path / "x.docx",
        "curso com 12 horas em uma versão e 15 horas em outra",
        resume,
    )

    merged = proposer.dedupe_update_field_changes(changes)

    assert len(merged) == 2  # genuinely different proposed values -- not merged


def test_dedupe_update_field_changes_leaves_new_item_changes_alone(tmp_path):
    resume = make_resume()
    changes = proposer.attach_evidence(
        LLMProposalBatch(
            changes=[
                LLMProposedChange(
                    kind="new_item", list_field="certifications", item={"name": "A"}, quote="Certificado A"
                ),
                LLMProposedChange(
                    kind="new_item", list_field="certifications", item={"name": "A"}, quote="Certificado A"
                ),
            ]
        ),
        tmp_path / "x.docx",
        "Certificado A concluído.",
        resume,
    )

    merged = proposer.dedupe_update_field_changes(changes)

    assert len(merged) == 2  # new_item deduplication is out of scope


class FakeProvider:
    def __init__(self, result: dict):
        self._result = result
        self.calls: list[dict] = []

    def structured_chat(self, messages, json_schema):
        self.calls.append({"messages": messages, "json_schema": json_schema})
        return self._result

    def chat(self, messages, tool_specs):  # pragma: no cover - not used here
        raise NotImplementedError


def test_propose_changes_for_file_calls_provider_with_batch_schema(tmp_path, monkeypatch):
    fake_provider = FakeProvider({"changes": []})
    monkeypatch.setattr(proposer, "get_provider", lambda: fake_provider)

    resume = make_resume()
    result = proposer.propose_changes_for_file(Path("/x/cert.pdf"), "algum texto", resume)

    assert isinstance(result, LLMProposalBatch)
    assert result.changes == []
    assert len(fake_provider.calls) == 1
    assert fake_provider.calls[0]["json_schema"] == LLMProposalBatch.model_json_schema()
