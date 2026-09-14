from __future__ import annotations


class SpeechToTextError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class VoiceAudioError(SpeechToTextError):
    pass
