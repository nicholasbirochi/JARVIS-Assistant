"""Incremental document indexer: scans authorized directories (résumés,
completed courses, personal/academic projects), proposes profile updates
with evidence attached -- never writes to data/resume.json directly. See
jarvis/indexing/runner.py (orchestration) and review.py (human approval)."""
