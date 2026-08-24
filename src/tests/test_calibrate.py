from voice.calibrate import format_reading


def test_format_reading_above_threshold_says_would_detect():
    assert "detectaria como palma" in format_reading(5000, clap_threshold=3500)


def test_format_reading_below_threshold_says_would_not_detect():
    assert "NÃO detectaria" in format_reading(2000, clap_threshold=3500)


def test_format_reading_includes_the_measured_peak():
    assert "4321" in format_reading(4321, clap_threshold=3500)
