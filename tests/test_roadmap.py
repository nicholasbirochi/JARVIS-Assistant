import pytest

from jarvis.roadmap import RoadmapSectionMissing, add_item

SAMPLE_README = """# Projeto

Texto qualquer.

## Uso

Instruções de uso.

## Roadmap

- Item existente um.
- Item existente dois.

"""

SAMPLE_README_WITH_TRAILING_SECTION = """# Projeto

## Roadmap

- Item único.

## Licença

MIT.
"""


def test_add_item_appends_after_last_bullet(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(SAMPLE_README, encoding="utf-8")

    add_item("Ideia nova", readme_path=readme)

    text = readme.read_text(encoding="utf-8")
    lines = text.split("\n")
    roadmap_index = lines.index("## Roadmap")
    # The new item is the last bullet in the Roadmap section, still before
    # the trailing blank line -- not appended past the end of the file.
    assert lines[roadmap_index + 1] == ""
    assert lines[roadmap_index + 2] == "- Item existente um."
    assert lines[roadmap_index + 3] == "- Item existente dois."
    assert lines[roadmap_index + 4] == "- Ideia nova"


def test_add_item_inserts_before_a_later_section_not_at_end_of_file(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(SAMPLE_README_WITH_TRAILING_SECTION, encoding="utf-8")

    add_item("Segunda ideia", readme_path=readme)

    text = readme.read_text(encoding="utf-8")
    assert "- Item único.\n- Segunda ideia\n\n## Licença" in text


def test_add_item_raises_when_roadmap_heading_missing(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Projeto sem roadmap\n", encoding="utf-8")

    with pytest.raises(RoadmapSectionMissing):
        add_item("Qualquer coisa", readme_path=readme)


def test_add_item_preserves_a_trailing_newline(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(SAMPLE_README, encoding="utf-8")

    add_item("Mais uma", readme_path=readme)

    assert readme.read_text(encoding="utf-8").endswith("\n")
