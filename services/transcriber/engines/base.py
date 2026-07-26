from abc import ABC, abstractmethod


# All transcription engines extend this.
class BaseTranscriptionEngine(ABC):

    # Transcribes audio_path; returns {text, segments: [{start, end, text}],
    # language, engine}.
    @abstractmethod
    async def transcribe(self, audio_path: str) -> dict:
        pass
