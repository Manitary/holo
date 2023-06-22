import logging
import re
from datetime import datetime, timedelta
from typing import Any
from bs4 import BeautifulSoup

import dateutil.parser

from data.models import Episode, Stream, UnprocessedStream

from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


class ServiceHandler(AbstractServiceHandler):
    _show_url = "https://www.adultswim.com/videos/{id}/"
    _show_re = re.compile(r"adultswim.com/videos/([\w-]+)", re.I)

    def __init__(self) -> None:
        super().__init__("adultswim", "Adult Swim", False)

    # Episode finding

    def get_all_episodes(self, stream: Stream, **kwargs: Any) -> list[Episode]:
        logger.info("Getting live episodes for %s/%s", self.name, stream.show_key)
        episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

        # Check episode validity and digest
        episodes: list[Episode] = []
        for episode_data in episode_datas:
            if _is_valid_episode(episode_data, stream.show_key):
                try:
                    episodes.append(_digest_episode(episode_data))
                except Exception:
                    logger.exception(
                        "Problem digesting episode for %s/%s",
                        self.name,
                        stream.show_key,
                    )

        if len(episode_datas) > 0:
            logger.debug(
                "  %d episodes found, %d valid", len(episode_datas), len(episodes)
            )
        else:
            logger.debug("  No episode found")
        return episodes

    def _get_feed_episodes(self, show_key: str, **kwargs: Any):
        logger.info("Getting episodes for %s/%s", self.name, show_key)

        url = self._get_feed_url(show_key)

        # Send request
        response: BeautifulSoup | None = self.request(url, html=True, **kwargs)
        if response is None:
            logger.error("Cannot get show page for %s/%s", self.name, show_key)
            return []

        # Parse html page
        sections = response.find_all("div", itemprop="episode")
        return sections

    @classmethod
    def _get_feed_url(cls, show_key: str) -> str | None:
        if show_key:
            return cls._show_url.format(id=show_key)
        else:
            return None

    # Remove info getting

    def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
        logger.info("Getting stream info for %s/%s", self.name, stream.show_key)

        url = self._get_feed_url(stream.show_key)
        response: BeautifulSoup | None = self.request(url, html=True, **kwargs)
        if response is None:
            logger.error("Cannot get feed")
            return None

        stream.name = response.find("h1", itemprop="name").text
        return stream

    def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
        # What is this for again ?
        return []

    def get_stream_link(self, stream: Stream) -> str:
        return self._show_url.format(id=stream.show_key)

    def extract_show_key(self, url: str) -> str | None:
        match = self._show_re.search(url)
        if match:
            return match.group(1)
        return None


def _is_valid_episode(episode_data, show_key: str) -> bool:
    # Don't check old episodes (possible wrong season !)
    date_string = episode_data.find("meta", itemprop="datePublished")["content"]
    date = datetime.fromordinal(dateutil.parser.parse(date_string).toordinal())

    if date > datetime.utcnow():
        return False

    date_diff = datetime.utcnow() - date
    if date_diff >= timedelta(days=2):
        logger.debug("  Episode too old")
        return False

    return True


def _digest_episode(feed_episode):
    logger.debug("Digesting episode")

    name = feed_episode.find("h4", itemprop="name", class_="episode__title").text
    link = feed_episode.find("a", itemprop="url", class_="episode__link").href
    num = int(feed_episode.find("meta", itemprop="episodeNumber")["content"])

    date_string = feed_episode.find("meta", itemprop="dateCreated")["content"]
    date = datetime.fromordinal(dateutil.parser.parse(date_string).toordinal())

    return Episode(number=num, name=name, link=link, date=date)
