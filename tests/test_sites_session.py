from jarvis import config
from jarvis.sites import session


def test_state_path_is_scoped_per_site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert session.state_path("gupy") == tmp_path / "gupy_state.json"
    assert session.state_path("catho") == tmp_path / "catho_state.json"


def test_has_saved_session_false_when_never_logged_in(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)

    assert session.has_saved_session("gupy") is False


def test_has_saved_session_true_once_state_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_STATE_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "gupy_state.json").write_text("{}", encoding="utf-8")

    assert session.has_saved_session("gupy") is True
