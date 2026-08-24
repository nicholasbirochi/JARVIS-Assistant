"""Lets JARVIS add an idea to this project's own README.md "## Roadmap"
section by voice/text, instead of that only being something a human (or
Claude Code) edits directly. Deliberately narrow: appends a plain bullet
to an existing section in a real, git-tracked file -- never rewrites
anything else in the README, never creates the section if it's missing
(that would mean the README changed shape in a way this should be
revisited for, not silently patched around).
"""

from __future__ import annotations

_SECTION_HEADING = "## Roadmap"


class RoadmapSectionMissing(Exception):
    pass


def add_item(description: str, *, readme_path=None) -> None:
    """Appends `description` as a new bullet at the end of README.md's
    Roadmap section (right before the next "## " heading, or end of file
    if Roadmap is the last section). Raises RoadmapSectionMissing if the
    heading isn't found, rather than guessing where to put it."""
    if readme_path is None:
        from config import PROJECT_ROOT

        readme_path = PROJECT_ROOT / "README.md"

    text = readme_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    try:
        heading_index = next(i for i, line in enumerate(lines) if line.strip() == _SECTION_HEADING)
    except StopIteration:
        raise RoadmapSectionMissing(f'"{_SECTION_HEADING}" não encontrado em {readme_path}') from None

    insert_at = len(lines)
    for i in range(heading_index + 1, len(lines)):
        if lines[i].startswith("## "):
            insert_at = i
            break
    while insert_at > heading_index + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    new_line = f"- {description}"
    lines.insert(insert_at, new_line)
    readme_path.write_text("\n".join(lines), encoding="utf-8")
