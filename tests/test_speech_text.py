from jarvis.voice.speech_text import prepare_for_speech, spell_out_acronyms, strip_markdown


def test_strip_markdown_removes_bold():
    assert strip_markdown("Isso é **muito** importante.") == "Isso é muito importante."


def test_strip_markdown_removes_bold_underscore_style():
    assert strip_markdown("Isso é __muito__ importante.") == "Isso é muito importante."


def test_strip_markdown_removes_italic():
    assert strip_markdown("Isso é *meio* importante.") == "Isso é meio importante."


def test_strip_markdown_removes_inline_code():
    assert strip_markdown("Rode `pytest tests/` antes.") == "Rode pytest tests/ antes."


def test_strip_markdown_removes_link_keeps_visible_text():
    assert strip_markdown("Veja o [Gupy](https://gupy.io).") == "Veja o Gupy."


def test_strip_markdown_removes_header_marker():
    assert strip_markdown("### Resumo") == "Resumo"


def test_strip_markdown_removes_bullet_marker():
    assert strip_markdown("- primeiro item") == "primeiro item"


def test_strip_markdown_leaves_plain_text_untouched():
    text = "Tudo certo por aqui, Senhor Nicholas."
    assert strip_markdown(text) == text


def test_spell_out_acronyms_inserts_dots():
    assert spell_out_acronyms("Isso é sobre IA.") == "Isso é sobre I.A."


def test_spell_out_acronyms_collapses_double_period_at_sentence_end():
    # "IA" + the sentence's own final "." would naively produce "I.A..";
    # a single period reads/sounds cleaner and is just as unambiguous.
    assert spell_out_acronyms("Falamos de IA.") == "Falamos de I.A."


def test_spell_out_acronyms_handles_multiple_acronyms():
    result = spell_out_acronyms("A LLM usa IA para gerar texto.")
    assert result == "A L.L.M. usa I.A. para gerar texto."


def test_spell_out_acronyms_does_not_touch_normal_capitalized_words():
    assert spell_out_acronyms("Nicholas mora em Belo Horizonte.") == "Nicholas mora em Belo Horizonte."


def test_spell_out_acronyms_does_not_touch_single_capital_letter():
    assert spell_out_acronyms("O relatório é o Anexo A.") == "O relatório é o Anexo A."


def test_prepare_for_speech_strips_markdown_and_spells_out_acronyms_together():
    assert prepare_for_speech("Isso é sobre **IA**.") == "Isso é sobre I.A."


def test_prepare_for_speech_leaves_plain_short_reply_untouched():
    text = "Sim, adoro trabalhar com dados."
    assert prepare_for_speech(text) == text
