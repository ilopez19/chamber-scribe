from abc import ABC, abstractmethod


class BaseDownloadStrategy(ABC):
    """
    Every download strategy extends this.
    Adding a new strategy = one new file, zero changes to the downloader.
    """

    @abstractmethod
    async def download(self, url: str, destination: str) -> bool:
        """
        Download a file from url to destination path.

        Returns:
            True if successful, False if failed
        """
        pass