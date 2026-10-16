import array
import wave

from hyprwhispr import audio


def _write_wav(path, samples, rate=16000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(array.array("h", samples).tobytes())


def test_probe_silence(tmp_path):
    path = tmp_path / "silence.wav"
    _write_wav(path, [0] * 16000)  # 1 second of silence
    duration_ms, peak_db = audio.probe_wav(path)
    assert 900 <= duration_ms <= 1100
    assert peak_db == float("-inf")


def test_probe_loud(tmp_path):
    path = tmp_path / "loud.wav"
    _write_wav(path, [30000, -30000] * 8000)
    duration_ms, peak_db = audio.probe_wav(path)
    assert duration_ms > 0
    assert peak_db > -5  # near full scale


def test_probe_missing_file(tmp_path):
    duration_ms, peak_db = audio.probe_wav(tmp_path / "nope.wav")
    assert duration_ms == 0
    assert peak_db == float("-inf")
