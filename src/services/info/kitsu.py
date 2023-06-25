# API docs: https://kitsu.docs.apiary.io

import logging
import re
from typing import Any

from data.models import Link, Show, UnprocessedShow

from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "https://kitsu.io/anime/{slug}"
    _show_link_matcher = r"https?://kitsu\.io/anime/([a-zA-Z0-9-]+)"
    _season_url = "https://kitsu.io/api/edge/anime?filter[year]={year}&filter[season]={season}&filter[subtype]=tv&page[limit]=20"

    _api_base = "https:///kitsu.io/api/edge/anime"

    def __init__(self) -> None:
        super().__init__(key="kitsu", name="Kitsu")

    def get_link(self, link: Link | None) -> str | None:
        if not link:
            return None
        return self._show_link_base.format(slug=link.site_key)

    def extract_show_id(self, url: str) -> str | None:
        if match := re.match(self._show_link_matcher, url, re.I):
            return match.group(1)
        return None

    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        # logger.debug("Getting episode count")

        # Request show data from Kitsu
        # url = self._api_base + "?filter[slug]=" + link.site_key + "&fields[anime]=episodeCount"
        # response = self._site_request(url, **kwargs)
        # if not response:
        # 	logger.error("Cannot get show data")
        # 	return None

        # Parse show data
        # count = response["data"][0]["attributes"]["episodeCount"]
        # if not count:
        # 	logger.warning("  Count not found")
        # 	return None

        # return count
        return None

    def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
        # logger.debug("Getting show score")

        # Request show data
        # url = self._api_base + "?filter[slug]=" + link.site_key + "&fields[anime]=averageRating"
        # response = self._site_request(url, **kwargs)
        # if not response:
        # 	logger.error("Cannot get show data")
        # 	return None

        # Find score
        # score = response["data"][0]["attributes"]["averageRating"]
        # if not score:
        # 	logger.warning("  Score not found")
        # 	return None

        # return score
        return None

    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        # logger.debug("Getting season shows: year=%s, season=%s", year, season)

        # Request season data from Kitsu
        # url = self._season_url.format(year=year, season=season)
        # response = self._site_request(url, **kwargs)
        # if not response:
        # 	logger.error("Cannot get show list")
        # 	return []

        # Parse data
        # TODO
        return []

    def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
        # url = self._api_base + "?filter[text]=" + show_name
        # result = self._site_request(url, **kwargs)
        # if not result:
        # 	logger.error("Failed to find show")
        # 	return []

        # shows: list[Show] = []
        # TODO

        # return shows
        return []

    def find_show_info(self, show_id: str, **kwargs: Any) -> None:
        # logger.debug("Getting show info for %s", show_id)

        # Request show data from Kitsu
        # url = self._api_base + "?filter[slug]=" + show_id + "&fields[anime]=titles,abbreviatedTitles"
        # response = self._site_request(url, **kwargs)
        # if not response:
        # 	logger.error("Cannot get show data")
        # 	return None

        # Parse show data
        # name_english = response["data"][0]["attributes"]["titles"]["en"]
        # if not name_english:
        # 	logger.warning("  English name was not found")
        # 	return None

        # names = [name_english]
        # return UnprocessedShow(self.key, id, None, names, ShowType.UNKNOWN, 0, False)
        return None

    def _site_request(self, url: str, **kwargs: Any) -> Any:
        return self.request_json(url, **kwargs)
