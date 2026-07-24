from abc import ABC, abstractmethod


class BaseTranscriptionEngine(ABC):
    """All transcription engines extend this."""

    @abstractmethod
    async def transcribe(self, audio_path: str) -> dict:
        """
        Transcribe an audio file.

        Returns:
            {
                "text": str,           # full transcript
                "segments": list,      # [{start, end, text}]
                "language": str,       # detected language
                "engine": str,         # which engine produced this
            }
        """
        pass