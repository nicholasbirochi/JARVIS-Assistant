import threading
import time

from jarvis.menubar import VoiceLoopController


def _cooperative_target(stop_event: threading.Event) -> None:
    """Stands in for run_voice_loop: exits promptly once stop_event is set,
    without touching any real audio/model/TTS."""
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


def test_restart_after_stop_runs_again():
    controller = VoiceLoopController(target=_cooperative_target)
    controller.start()
    assert _wait_until(lambda: controller.is_running)
    controller.stop()
    assert _wait_until(lambda: not controller.is_running)

    controller.start()

    assert _wait_until(lambda: controller.is_running)
    controller.stop()
