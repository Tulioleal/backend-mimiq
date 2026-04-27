from __future__ import annotations

from pathlib import Path


EXTENSION_TO_MEDIA_TYPE = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}

MEDIA_TYPE_TO_EXTENSION = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
}


def guess_audio_extension(filename: str | None, content_type: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in EXTENSION_TO_MEDIA_TYPE:
            return suffix
    if content_type and content_type in MEDIA_TYPE_TO_EXTENSION:
        return MEDIA_TYPE_TO_EXTENSION[content_type]
    return ".wav"


def guess_audio_media_type(path_or_filename: str) -> str:
    suffix = Path(path_or_filename).suffix.lower()
    return EXTENSION_TO_MEDIA_TYPE.get(suffix, "application/octet-stream")
