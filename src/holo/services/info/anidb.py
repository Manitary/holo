# API information
# 	https://wiki.anidb.net/w/HTTP_API_Definition
# Limits
# 	- 1 page every 2 seconds
# 	- Avoid calling same function multiple times per day
#
# Season page
# 	https://anidb.net/perl-bin/animedb.pl?tvseries=1&show=calendar
# 	- Based on year and month, defaults to current month

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from ...data.models import Link, Show, ShowType, UnprocessedShow
from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "https://anidb.net/perl-bin/animedb.pl?show=anime&aid={id}"
    _show_link_matcher = re.compile(
        r"https?://anidb\.net/a([0-9]+)"
        r"|https?://anidb\.net/perl-bin/animedb\.pl\?(?:[^/]+&)aid=([0-9]+)"
        r"|https?://anidb\.net/anime/([0-9]+)",
        re.I,
    )
    _season_url = (
        "https://anidb.net/perl-bin/animedb.pl"
        "?show=calendar&tvseries=1&ova=1&last.anime.month=1&last.anime.year=2016"
    )

    _api_base = (
        "http://api.anidb.net:9001/httpapi"
        "?client={client}&clientver={ver}&protover=1&request={request}"
    )

    def __init__(self) -> None:
        super().__init__(key="anidb", name="AniDB")
        self.rate_limit_wait = 2

    def get_link(self, link: Link | None) -> str | None:
        if not link:
            return None
        return self._show_link_base.format(id=link.site_key)

    def extract_show_id(self, url: str) -> str | None:
        if match := self._show_link_matcher.match(url):
            return match.group(1) or match.group(2) or match.group(3)
        return None

    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        return None

    def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
        return None

    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        return []

        # TODO: use year and season if provided
        logger.debug("Getting season shows: year=%s, season=%s", year, season)

        # Request season page from AniDB
        response = self._site_request(self._season_url, **kwargs)
        if not response:
            logger.error("Cannot get show list")
            return []

        # Parse page
        shows_list = response.select(".calendar_all .g_section.middle .content .box")
        new_shows: list[UnprocessedShow] = []
        for show in shows_list:
            top = show.find(class_="top")
            title_e = top.find("a")
            title = str(title_e.string)
            title = _normalize_title(title)
            show_link = title_e["href"]
            key = re.search("aid=([0-9]+)", show_link).group(1)

            data = show.find(class_="data")
            more_names = list()
            show_info_str = data.find(class_="series").string.strip()
            logger.debug("Show info: %s", show_info_str)
            show_info = show_info_str.split(", ")
            show_type = _convert_show_type(show_info[0])
            if len(show_info) == 1:
                episode_count = 1
            else:
                ec_match = re.match("([0-9]+) eps", show_info[1])
                episode_count = int(ec_match.group(1)) if ec_match else None
            tags = data.find(class_="tags")
            has_source = (
                tags.find("a", string=re.compile("manga|novel|visual novel"))
                is not None
            )

            new_shows.append(
                UnprocessedShow(
                    self.key,
                    key,
                    title,
                    more_names,
                    show_type,
                    episode_count,
                    has_source,
                )
            )

        return new_shows

    def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
        return []

    def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
        return None

    def _site_request(self, url: str, **kwargs: Any) -> BeautifulSoup | None:
        return self.request_html(url, **kwargs)


def _convert_show_type(type_str: str) -> ShowType:
    type_str = type_str.lower()
    if type_str == "tv series":
        return ShowType.TV
    if type_str == "movie":
        return ShowType.MOVIE
    if type_str == "ova":
        return ShowType.OVA
    return ShowType.UNKNOWN


def _normalize_title(title: str) -> str:
    year_match = re.match(r"(.*) \([0-9]+\)", title)
    if year_match:
        title = year_match.group(1)
    title = re.sub(": second season", " 2nd Season", title, flags=re.I)
    title = re.sub(": third season", " 3rd Season", title, flags=re.I)
    title = re.sub(": fourth season", " 4th Season", title, flags=re.I)
    title = re.sub(": fifth season", " 5th Season", title, flags=re.I)
    title = re.sub(": sixth season", " 6th Season", title, flags=re.I)
    return title
