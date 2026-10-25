from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VideoMeta:
    video_id: str
    platform: str
    url: str
    title: str
    duration: float
    author: str = ""
    description: str = ""


class PlatformAdapter(ABC):
    name: str
    capabilities: set[str] = set()

    @abstractmethod
    def get_metadata(self, url: str) -> VideoMeta: ...

    def get_subtitles(self, meta: VideoMeta) -> list[dict]:
        return []

    def get_danmaku(self, meta: VideoMeta) -> list[dict]:
        return []

    def get_comments(self, meta: VideoMeta) -> list[dict]:
        return []

    def download_media(self, meta: VideoMeta) -> str | None:
        return None