from abc import ABC, abstractmethod


# Every download strategy extends this; adding a new strategy means one
# new file and zero changes to the downloader.
class BaseDownloadStrategy(ABC):

    def __init__(self, verify_ssl: bool = True):
        # Only HTTPAudioExtractStrategy reads self._verify (skips cert
        # checking for House's broken TLS); living here means any future
        # HTTP-based strategy inherits it for free.
        self._verify = verify_ssl

    # Downloads url to destination; returns True on success, False on failure.
    @abstractmethod
    async def download(self, url: str, destination: str) -> bool:
        pass
