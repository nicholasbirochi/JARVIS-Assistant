"""Standalone diagnostic: `python src/cli.py calibrate-claps` prints the
live peak amplitude of every sound loud enough to stand out from silence,
so CLAP_PEAK_THRESHOLD can be set to a real measured value for this mic and
room instead of guessed blind. Amplitude-based clap detection is
inherently environment-sensitive (mic gain, distance, room noise) -- this
is the tool for turning "claps aren't detected" into a five-second fix.

Not used by the real voice loop -- this is a manual, opt-in command only.
"""

from __future__ import annotations

from voice.engines.clap_detector import peak

# Ignore near-silence (keyboard clicks, room hum) -- only report sounds loud
# enough that a human would call them a deliberate noise, well below even a
# very permissive clap threshold.
_REPORT_FLOOR = 800


def format_reading(level: int, clap_threshold: float) -> str:
    verdict = "detectaria como palma" if level >= clap_threshold else "abaixo do limiar -- NÃO detectaria"
    return f"pico: {level:6d}   ({verdict})"


def run() -> None:
    from pvrecorder import PvRecorder

    from config import CLAP_PEAK_THRESHOLD
    from voice.wake_word import get_wake_word_engine

    engine = get_wake_word_engine()
    recorder = PvRecorder(device_index=-1, frame_length=engine.frame_length)
    recorder.start()

    print(f"Limiar atual (CLAP_PEAK_THRESHOLD): {CLAP_PEAK_THRESHOLD:.0f}")
    print("Bata palmas isoladas (uma de cada vez, com uma pausa entre elas)")
    print("e observe os picos abaixo. Ctrl+C para sair.\n")

    was_loud = False
    try:
        while True:
            frame = recorder.read()
            level = peak(frame)
            loud = level >= _REPORT_FLOOR
            is_onset = loud and not was_loud
            was_loud = loud
            if not is_onset:
                continue

            print(format_reading(level, CLAP_PEAK_THRESHOLD))
    except KeyboardInterrupt:
        print("\nEncerrado.")
        print(
            "Se os picos das suas palmas ficaram abaixo do limiar, defina "
            "CLAP_PEAK_THRESHOLD no .env com um valor um pouco abaixo do "
            "menor pico observado."
        )
    finally:
        recorder.stop()
        recorder.delete()
        engine.close()


if __name__ == "__main__":
    run()
