# API docs: https://anilist-api.readthedocs.org/en/latest/

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from data.models import Link, Show, UnprocessedShow

from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "https://anilist.co/anime/{id}"
    _show_link_matcher = "https?://anilist\\.co/anime/([0-9]+)"
    _season_url = (
        "https://anilist.co/api/browse/anime?year={year}&season={season}&type=Tv"
    )

    def __init__(self) -> None:
        super().__init__("anilist", "AniList")
        self.rate_limit_wait = 2

    def get_link(self, link: Link | None) -> str | None:
        if not link:
            return None
        return self._show_link_base.format(id=link.site_key)

    def extract_show_id(self, url: str) -> str | None:
        if match := re.match(self._show_link_matcher, url, re.I):
            return match.group(1)
        return None

    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        return None

    def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
        return None

    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        # logger.debug("Getting season shows: year=%s, season=%s", year, season)

        # Request season page from AniDB
        # url = self._season_url.format(year=year, season=season)
        # response = self._site_request(url, **kwargs)
        # if response is None:
        # 	logger.error("Cannot get show list")
        # 	return list()

        # Parse page
        # TODO
        return []

    def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
        return []

    def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
        return None

    def _site_request(self, url: str, **kwargs: Any) -> BeautifulSoup:
        return self.request(url, html=True, **kwargs)
