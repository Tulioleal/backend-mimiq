from __future__ import annotations

from io import BytesIO

import numpy as np
import soundfile as sf

from services.audio_health import AudioHealthAnalyzer


def render_wav_bytes(duration_seconds: float, sample_rate: int = 22050) -> bytes:
    total_samples = int(duration_seconds * sample_rate)
    time = np.arange(total_samples) / sample_rate
    waveform = 0.2 * np.sin(2 * np.pi * 220 * time)
    if duration_seconds >= 10:
        silence_samples = sample_rate * 2
        waveform[:silence_samples] = 0
        waveform[-silence_samples:] = 0

    buffer = BytesIO()
    sf.write(buffer, waveform, sample_rate, format="WAV")
    return buffer.getvalue()


def test_audio_health_accepts_clean_sample() -> None:
    analyzer = AudioHealthAnalyzer()
    report = analyzer.analyze_bytes(render_wav_bytes(61), "sample.wav")

    assert report.passed is True
    assert report.duration_seconds >= 60
    assert report.issues == []


def test_audio_health_rejects_short_sample() -> None:
    analyzer = AudioHealthAnalyzer()
    report = analyzer.analyze_bytes(render_wav_bytes(10), "sample.wav")

    assert report.passed is False
    assert any(issue.code == "duration_too_short" for issue in report.issues)
