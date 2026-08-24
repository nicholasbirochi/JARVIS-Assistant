"""Regression coverage for the DATA_DIR vs. LOCAL_STATE_DIR split -- the
whole project lives inside an actively-synced OneDrive folder, so anything
that must never leave this machine (site-adapter login sessions, and any
future evidence with incidental PII) has to live outside PROJECT_ROOT
entirely, not just be .gitignore'd. See config.py's LOCAL_STATE_DIR
comment for the full story."""

import config


def test_local_state_dir_is_not_inside_project_root():
    assert config.PROJECT_ROOT not in config.LOCAL_STATE_DIR.parents
    assert config.LOCAL_STATE_DIR != config.PROJECT_ROOT


def test_sites_state_dir_lives_under_local_state_dir_not_data_dir():
    assert config.LOCAL_STATE_DIR in config.SITES_STATE_DIR.parents
    assert config.DATA_DIR not in config.SITES_STATE_DIR.parents


def test_sites_evidence_dir_lives_under_sites_state_dir():
    assert config.SITES_STATE_DIR in config.SITES_EVIDENCE_DIR.parents
