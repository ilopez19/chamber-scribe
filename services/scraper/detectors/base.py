from abc import ABC, abstractmethod

class BaseDetector(ABC):

    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @abstractmethod
    async def get_new_videos(self) -> list[dict]:
        pass