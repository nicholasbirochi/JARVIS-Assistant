import os
import subprocess
import threading
import time

from jarvis import config
from jarvis.menubar import JarvisMenuBarApp, VoiceLoopController, _acquire_singleton_lock, _pid_is_alive


def _cooperative_target(stop_event: threading.Event, wake_event: threading.Event | None = None) -> None:
    """Stands in for run_voice_loop: exits promptly once stop_event is set,
    without touching any real audio/model/TTS. Accepts wake_event to match
    start()'s real call signature, even though this fake never uses it."""
    while not stop_event.is_set():
        time.sleep(0.01)


def _wait_until(predicate, timeout=2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_start_launches_a_running_thread():
    controller = VoiceLoopController(target=_cooperative_target)

    controller.start()

    assert _wait_until(lambda: controller.is_running)
    controller.stop()


def test_start_twice_does_not_launch_a_second_thread():
    controller = VoiceLoopController(target=_cooperative_target)
    controller.start()
    assert _wait_until(lambda: controller.is_running)
    first_thread = controller._thread

    controller.start()

    assert controller._thread is first_thread
    controller.stop()


def test_stop_signals_the_thread_to_exit():
    controller = VoiceLoopController(target=_cooperative_target)
    controller.start()
    assert _wait_until(lambda: controller.is_running)

    controller.stop()

    assert _wait_until(lambda: not controller.is_running)


def test_stop_before_start_is_a_safe_no_op():
    controller = VoiceLoopController(target=_cooperative_target)

    controller.stop()  # must not raise

    assert controller.is_running is False


def test_is_running_false_before_start():
    controller = VoiceLoopController(target=_cooperative_target)

    assert controller.is_running is False


def test_notify_system_wake_sets_the_wake_event_while_running():
    controller = VoiceLoopController(target=_cooperative_target)
    controller.start()
    assert _wait_until(lambda: controller.is_running)

    controller.notify_system_wake()

    assert controller._wake_event.is_set()
    controller.stop()


def test_notify_system_wake_before_start_is_a_safe_no_op():
    controller = VoiceLoopController(target=_cooperative_target)

    controller.notify_system_wake()  # must not raise -- no listener exists yet to refresh

    assert controller.is_running is False


def test_restart_after_stop_runs_again():
    controller = VoiceLoopController(target=_cooperative_target)
    controller.start()
    assert _wait_until(lambda: controller.is_running)
    controller.stop()
    assert _wait_until(lambda: not controller.is_running)

    controller.start()

    assert _wait_until(lambda: controller.is_running)
    controller.stop()


# ---- singleton lock -- guards against the real bug this session found:
# two real instances (LaunchAgent + a manually-opened JARVIS.app) running
# at once, both fighting over the microphone ----


def test_pid_is_alive_true_for_this_process():
    assert _pid_is_alive(os.getpid()) is True


def test_pid_is_alive_false_for_a_pid_that_does_not_exist():
    # A PID vanishingly unlikely to be in use.
    assert _pid_is_alive(2**30) is False


def test_acquire_singleton_lock_succeeds_when_no_lock_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert _acquire_singleton_lock() is True
    assert (tmp_path / "jarvis.pid").read_text().strip() == str(os.getpid())


def test_acquire_singleton_lock_fails_when_another_live_process_holds_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    # A real, definitely-alive process that isn't us.
    proc = subprocess.Popen(["sleep", "30"])
    try:
        (tmp_path / "jarvis.pid").write_text(str(proc.pid), encoding="utf-8")

        assert _acquire_singleton_lock() is False
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_acquire_singleton_lock_succeeds_when_lock_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "jarvis.pid").write_text(str(2**30), encoding="utf-8")  # dead PID

    assert _acquire_singleton_lock() is True
    assert (tmp_path / "jarvis.pid").read_text().strip() == str(os.getpid())


def test_acquire_singleton_lock_succeeds_when_file_is_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "jarvis.pid").write_text("not-a-pid", encoding="utf-8")

    assert _acquire_singleton_lock() is True


def test_run_daily_job_search_worker_calls_run_daily_search_if_due_with_the_loaded_resume(monkeypatch):
    # A staticmethod, so it's callable directly without building a real
    # rumps.App/AppKit instance -- same reasoning VoiceLoopController was
    # split out for.
    calls = []
    fake_resume = object()
    monkeypatch.setattr("jarvis.resume.store.load", lambda: fake_resume)
    monkeypatch.setattr("jarvis.job_search.run_daily_search_if_due", lambda resume: calls.append(resume))

    JarvisMenuBarApp._run_daily_job_search_worker()

    assert calls == [fake_resume]


def test_run_daily_job_search_worker_swallows_exceptions(monkeypatch):
    # Best-effort background refresh -- a broken site adapter or a network
    # hiccup must never crash the menu bar app it runs inside.
    monkeypatch.setattr("jarvis.resume.store.load", lambda: object())

    def _boom(resume):
        raise RuntimeError("site indisponível")

    monkeypatch.setattr("jarvis.job_search.run_daily_search_if_due", _boom)

    JarvisMenuBarApp._run_daily_job_search_worker()  # must not raise


def test_refresh_job_portal_worker_calls_refresh_if_due_with_the_loaded_resume(monkeypatch):
    # Independent daily mechanism from the one above -- the deep portal
    # sweep, added 2026-08-17 ("faça essa varredura diária").
    calls = []
    fake_resume = object()
    monkeypatch.setattr("jarvis.resume.store.load", lambda: fake_resume)
    monkeypatch.setattr("jarvis.job_portal.server.refresh_if_due", lambda resume: calls.append(resume))

    JarvisMenuBarApp._refresh_job_portal_worker()

    assert calls == [fake_resume]


def test_refresh_job_portal_worker_swallows_exceptions(monkeypatch):
    monkeypatch.setattr("jarvis.resume.store.load", lambda: object())

    def _boom(resume):
        raise RuntimeError("site indisponível")

    monkeypatch.setattr("jarvis.job_portal.server.refresh_if_due", _boom)

    JarvisMenuBarApp._refresh_job_portal_worker()  # must not raise
