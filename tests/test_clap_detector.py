from jarvis.voice.engines.clap_detector import ClapDetector

LOUD = [20_000] * 10
QUIET = [0] * 10
FRAME_SECONDS = 0.05


def make_detector(**kwargs) -> ClapDetector:
    kwargs.setdefault("threshold", 6000)
    kwargs.setdefault("clap_window_seconds", 1.5)
    return ClapDetector(**kwargs)


def test_two_claps_within_window_triggers():
    detector = make_detector()

    assert detector.process(LOUD, FRAME_SECONDS) is False  # first clap onset
    assert detector.process(QUIET, FRAME_SECONDS) is False
    assert detector.process(QUIET, FRAME_SECONDS) is False
    assert detector.process(LOUD, FRAME_SECONDS) is True  # second clap onset -- fires


def test_single_clap_never_triggers():
    detector = make_detector()

    assert detector.process(LOUD, FRAME_SECONDS) is False
    for _ in range(50):
        assert detector.process(QUIET, FRAME_SECONDS) is False


def test_sustained_loud_frame_counts_as_one_onset_not_two():
    detector = make_detector()

    assert detector.process(LOUD, FRAME_SECONDS) is False  # onset
    assert detector.process(LOUD, FRAME_SECONDS) is False  # still loud -- not a new onset
    assert detector.process(LOUD, FRAME_SECONDS) is False  # still loud -- not a new onset


def test_claps_too_far_apart_do_not_pair(monkeypatch):
    detector = make_detector(clap_window_seconds=1.0)

    assert detector.process(LOUD, FRAME_SECONDS) is False
    assert detector.process(QUIET, 5.0) is False  # a big silent gap -- window expires
    assert detector.process(LOUD, FRAME_SECONDS) is False  # starts a new pairing attempt instead of firing


def test_claps_too_close_together_treated_as_echo():
    detector = make_detector(min_gap_seconds=0.2)

    assert detector.process(LOUD, FRAME_SECONDS) is False
    assert detector.process(QUIET, 0.01) is False
    assert detector.process(LOUD, 0.01) is False  # onset again too soon -- likely reverb of the same clap


def test_three_onsets_second_and_third_pair_up():
    detector = make_detector()

    assert detector.process(LOUD, FRAME_SECONDS) is False  # 1st onset
    assert detector.process(QUIET, FRAME_SECONDS) is False
    assert detector.process(LOUD, FRAME_SECONDS) is True  # 2nd onset pairs with 1st -- fires
    assert detector.process(QUIET, FRAME_SECONDS) is False
    assert detector.process(LOUD, FRAME_SECONDS) is False  # 3rd onset -- starts a fresh attempt, no pair yet


def test_short_transient_in_mostly_silent_frame_is_still_detected():
    # This is the actual real-world bug: a clap's transient only lasts a few
    # ms inside an 80ms frame. RMS over the whole frame would dilute this
    # far below threshold; peak amplitude catches it directly.
    detector = make_detector(threshold=6000)
    transient_frame = [0] * 1270 + [30_000] * 10  # spike buried in near-silence

    assert detector.process(transient_frame, FRAME_SECONDS) is False  # 1st onset
    assert detector.process(QUIET, FRAME_SECONDS) is False
    assert detector.process(transient_frame, FRAME_SECONDS) is True  # 2nd onset -- fires
