from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import librosa
import numpy as np
from fastapi import UploadFile

from models.voice import AudioHealthIssue, AudioHealthReport


class AudioHealthAnalyzer:
    async def analyze_upload(self, upload: UploadFile) -> tuple[bytes, AudioHealthReport]:
        content = await upload.read()
        report = await asyncio.to_thread(self.analyze_bytes, content, upload.filename or "sample.wav")
        return content, report

    def analyze_bytes(self, audio_bytes: bytes, filename: str) -> AudioHealthReport:
        suffix = Path(filename).suffix or ".wav"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name

            signal, sample_rate = librosa.load(temp_path, sr=None, mono=True)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        signal = np.nan_to_num(signal)
        if signal.size == 0:
            raise ValueError("Uploaded audio is empty")

        epsilon = 1e-10
        duration_seconds = float(signal.size / sample_rate)
        absolute_signal = np.abs(signal)
        peak = float(np.max(absolute_signal))
        clipped_ratio = float(np.mean(absolute_signal >= 0.99))
        rms_frames = librosa.feature.rms(y=signal, frame_length=2048, hop_length=512).flatten()
        rms_db_frames = 20 * np.log10(np.maximum(rms_frames, epsilon))
        average_db = float(20 * np.log10(max(float(np.sqrt(np.mean(signal**2))), epsilon)))
        peak_db = float(20 * np.log10(max(peak, epsilon)))
        noise_floor_db = float(np.percentile(rms_db_frames, 5))

        active_threshold = max(float(np.percentile(rms_frames, 65)) * 0.35, 0.01)
        active_frames = rms_frames > active_threshold
        speech_db = (
            float(np.mean(rms_db_frames[active_frames])) if np.any(active_frames) else average_db
        )
        estimated_snr_db = float(speech_db - noise_floor_db)

        issues: list[AudioHealthIssue] = []
        recommendations: list[str] = []

        if duration_seconds < 60:
            issues.append(
                AudioHealthIssue(
                    code="duration_too_short",
                    message="Voice sample must be at least 60 seconds long.",
                )
            )
            recommendations.append("Record at least 60 seconds of continuous speech.")

        if average_db < -32 or peak < 0.15:
            issues.append(
                AudioHealthIssue(
                    code="volume_too_low",
                    message="Input volume is too low for reliable cloning.",
                )
            )
            recommendations.append("Move closer to the microphone or increase input gain.")

        if clipped_ratio > 0.005 or peak >= 0.999:
            issues.append(
                AudioHealthIssue(
                    code="clipping_detected",
                    message="Audio appears clipped or distorted.",
                )
            )
            recommendations.append("Lower the recording gain to avoid clipping.")

        if noise_floor_db > -35 or estimated_snr_db < 18:
            issues.append(
                AudioHealthIssue(
                    code="background_noise",
                    message="Background noise is too prominent for a clean voice sample.",
                )
            )
            recommendations.append("Record in a quieter room with a more isolated microphone setup.")

        return AudioHealthReport(
            passed=not issues,
            duration_seconds=round(duration_seconds, 2),
            average_db=round(average_db, 2),
            peak_db=round(peak_db, 2),
            noise_floor_db=round(noise_floor_db, 2),
            estimated_snr_db=round(estimated_snr_db, 2),
            clipped_ratio=round(clipped_ratio, 6),
            issues=issues,
            recommendations=recommendations,
        )
