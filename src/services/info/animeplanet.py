import logging
import re
from typing import Any

from data.models import EpisodeScore, Link, Show, UnprocessedShow

from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "https://www.anime-planet.com/anime/{name}"
    _show_link_matcher = (
        r"(?:https?://)?(?:www\.)?anime-planet\.com/anime/([a-zA-Z0-9-]+)"
    )

    def __init__(self) -> None:
        super().__init__("animeplanet", "Anime-Planet")

    def get_link(self, link: Link | None) -> str | None:
        if link is None:
            return None
        return self._show_link_base.format(name=link.site_key)

    def extract_show_id(self, url: str) -> str | None:
        if url:
            match = re.match(self._show_link_matcher, url, re.I)
            if match:
                return match.group(1)
        return None

    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        return None

    def get_show_score(
        self, show: Show, link: Link, **kwargs: Any
    ) -> EpisodeScore | None:
        return None

    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        return []

    def find_show(self, show_name: str, **kwargs: Any) -> list[Show]:
        return []

    def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
        return None
