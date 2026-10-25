from app.adapters.base import PlatformAdapter, VideoMeta


class BilibiliAdapter(PlatformAdapter):
    """佔位：MVP 不啟用。"""
    name = "bilibili"
    capabilities = {"metadata"}

    def get_metadata(self, url: str) -> VideoMeta:
        raise NotImplementedError("B站適配器佔位，config.platform.bilibili.enabled=false")
