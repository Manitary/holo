# API information
# 	https://myanimelist.net/modules.php?go=api

import logging
import re
from typing import Any
from xml.etree.ElementTree import Element

from bs4 import BeautifulSoup
from data.models import Link, Show, ShowType, UnprocessedShow

from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "https://myanimelist.net/anime/{id}/"
    _show_link_matcher = r"https?://(?:.+?\.)?myanimelist\.net/anime/([0-9]+)"
    _season_show_url = "https://myanimelist.net/anime/season"

    _api_search_base = "https://myanimelist.net/api/anime/search.xml?q={q}"

    def __init__(self) -> None:
        super().__init__(key="mal", name="MyAnimeList")

    def get_link(self, link: Link | None) -> str | None:
        if not link:
            return None
        return self._show_link_base.format(id=link.site_key)

    def extract_show_id(self, url: str) -> str | None:
        if match := re.match(self._show_link_matcher, url, re.I):
            return match.group(1)
        return None

    def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
        url = self._api_search_base.format(q=show_name)
        result = self._mal_api_request(url, **kwargs)
        if not result:
            logger.error("Failed to find show")
            return []

        assert result.tag == "anime"
        shows: list[UnprocessedShow] = []
        for child in result:
            print(child)
            assert child.tag == "entry"

            id: str = child.find("id").text
            name: str = child.find("title").text
            more_names = [child.find("english").text]
            show = UnprocessedShow(
                site_key=self.key,
                show_key=id,
                name=name,
                show_type=ShowType.UNKNOWN,
                episode_count=0,
                has_source=False,
                more_names=more_names,
            )
            shows.append(show)

        return shows

    def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
        logger.debug("Getting show info for %s", show_id)

        # Request show page from MAL
        url = self._show_link_base.format(id=show_id)
        response = self._mal_request(url, **kwargs)
        if not response:
            logger.error("Cannot get show page")
            return None

        # Parse show page
        names_sib = response.find("h2", string="Alternative Titles")
        # English
        name_elem = names_sib.find_next_sibling("div")
        if not name_elem:
            logger.warning("  Name elem not found")
            return None
        name_english = name_elem.string
        logger.info("  English: %s", name_english)

        names = [name_english]
        return UnprocessedShow(
            site_key=self.key,
            show_key=show_id,
            name=None,
            show_type=ShowType.UNKNOWN,
            episode_count=0,
            has_source=False,
            more_names=names,
        )

    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        logger.debug("Getting episode count")

        # Request show page from MAL
        url = self._show_link_base.format(id=link.site_key)
        response = self._mal_request(url, **kwargs)
        if not response:
            logger.error("Cannot get show page")
            return None

        # Parse show page (ugh, HTML parsing)
        count_sib = response.find("span", string="Episodes:")
        if not count_sib:
            logger.error("Failed to find episode count sibling")
            return None
        count_elem = count_sib.find_next_sibling(string=re.compile(r"\d+"))
        if not count_elem:
            logger.warning("  Count not found")
            return None
        count = int(count_elem.strip())
        logger.debug("  Count: %d", count)

        return count

    def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
        logger.debug("Getting show score")

        # Request show page
        url = self._show_link_base.format(id=link.site_key)
        response = self._mal_request(url, **kwargs)
        if not response:
            logger.error("Cannot get show page")
            return None

        # Find score
        score_elem = response.find("span", attrs={"itemprop": "ratingValue"})
        try:
            score = float(score_elem.string)
        except Exception:
            logger.warning("  Count not found")
            return None
        logger.debug("  Score: %f", score)

        return score

    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        # TODO: use year and season if provided
        logger.debug("Getting season shows: year=%s, season=%s", year, season)

        # Request season page from MAL
        response = self._mal_request(self._season_show_url, **kwargs)
        if not response:
            logger.error("Cannot get show list")
            return []

        # Parse page (ugh, HTML parsing. Where's the useful API, MAL?)
        lists = response.find_all(class_="seasonal-anime-list")
        if not lists:
            logger.error("Invalid page? Lists not found")
            return []
        new_list = lists[0].find_all(class_="seasonal-anime")
        if not new_list:
            logger.error("Invalid page? Shows not found in list")
            return []

        new_shows: list[UnprocessedShow] = []
        episode_count_regex = re.compile(r"(\d+|\?) eps?")
        for show in new_list:
            show_key = show.find(class_="genres")["id"]
            title = str(show.find("a", class_="link-title").string)
            title = _normalize_title(title)
            more_names = [title[:-11]] if title.lower().endswith("2nd season") else []
            show_type = ShowType.TV  # TODO, changes based on section/list
            if match := episode_count_regex.search(
                show.find(class_="eps").find(string=episode_count_regex)
            ):
                episode_count = match.group(1)
            else:
                logger.warning("Invalid episode count for show %s", show)
                continue
            episode_count = 0 if episode_count == "?" else int(episode_count)
            has_source = show.find(class_="source").string != "Original"

            new_shows.append(
                UnprocessedShow(
                    site_key=self.key,
                    show_key=show_key,
                    name=title,
                    more_names=more_names,
                    show_type=show_type,
                    episode_count=episode_count,
                    has_source=has_source,
                )
            )

        return new_shows

    # Private

    def _mal_request(self, url: str, **kwargs: Any) -> BeautifulSoup | None:
        return self.request_html(url, **kwargs)

    def _mal_api_request(self, url: str, **kwargs: Any) -> Element | None:
        if "username" not in self.config or "password" not in self.config:
            logger.error("Username and password required for MAL requests")
            return None

        auth = (self.config["username"], self.config["password"])
        return self.request_xml(url, auth=auth, **kwargs)


def _convert_type(mal_type):
    return None


def _normalize_title(title: str) -> str:
    return re.sub(r" \(TV\)", "", title)
